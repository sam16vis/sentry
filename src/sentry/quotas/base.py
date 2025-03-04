from __future__ import annotations

from enum import IntEnum, unique
from typing import TYPE_CHECKING, Any, Optional, Tuple

from django.conf import settings
from django.core.cache import cache

from sentry import features, options
from sentry.constants import DataCategory
from sentry.utils.json import prune_empty_keys
from sentry.utils.services import Service

if TYPE_CHECKING:
    from sentry.models import Project


@unique
class QuotaScope(IntEnum):
    ORGANIZATION = 1
    PROJECT = 2
    KEY = 3

    def api_name(self):
        return self.name.lower()


class QuotaConfig:
    """
    Abstract configuration for a quota.

    Sentry applies multiple quotas to an event before accepting it, some of
    which can be configured by the user depending on plan. An event will be
    counted against all quotas that it matches with based on the ``category``.

    The `QuotaConfig` object is not persisted, but is the contract between
    Sentry and Relay. Most importantly, a `QuotaConfig` instance does not
    contain information about how many events can still be accepted, it only
    represents settings that should be applied. The actual counts are in the
    rate limiter (e.g. implemented via Redis caches).

    :param id:          The unique identifier for counting this quota. Required
                        except for quotas with ``limit=0``, since they are
                        statically enforced.
    :param categories:  A set of data categories that this quota applies to. If
                        missing or empty, this quota applies to all data.
    :param scope:       A scope for this quota. This quota is enforced
                        separately within each instance of this scope (e.g. for
                        each project key separately). Defaults to ORGANIZATION.
    :param scope_id:    Identifier of the scope to apply to. If set, then this
                        quota will only apply to the specified scope instance
                        (e.g. a project key). Requires ``scope`` to be set
                        explicitly.
    :param limit:       Maximum number of matching events allowed. Can be ``0``
                        to reject all events, ``None`` for an unlimited counted
                        quota, or a positive number for enforcement. Requires
                        ``window`` if the limit is not ``0``.
    :param window:      The time window in seconds to enforce this quota in.
                        Required in all cases except ``limit=0``, since those
                        quotas are not measured.
    :param reason_code: A machine readable reason returned when this quota is
                        exceeded. Required in all cases except ``limit=None``,
                        since unlimited quotas can never be exceeded.
    """

    __slots__ = ["id", "categories", "scope", "scope_id", "limit", "window", "reason_code"]

    def __init__(
        self,
        id=None,
        categories=None,
        scope=None,
        scope_id=None,
        limit: int | None = None,
        window=None,
        reason_code=None,
    ):
        if limit is not None:
            assert reason_code, "reason code required for fallible quotas"
            assert isinstance(limit, int), "limit must be an integer"

        if limit == 0:
            assert id is None, "reject-all quotas cannot be tracked"
            assert window is None, "tracked quotas must specify a window"
        else:
            assert id, "measured quotas require an identifier"
            assert window and window > 0, "window cannot be zero"

        if scope_id is not None:
            assert scope, "scope must be declared explicitly when scope_id is given"
        elif scope is None:
            scope = QuotaScope.ORGANIZATION

        self.id = id
        self.scope = scope
        self.scope_id = str(scope_id) if scope_id is not None else None
        self.categories = set(categories or [])
        # NOTE: Use `quotas.base._limit_from_settings` to map from settings
        self.limit = limit
        self.window = window
        self.reason_code = reason_code

    @property
    def should_track(self):
        """
        Whether the quotas service should track this quota.
        """

        return self.id is not None and self.window is not None

    def to_json(self):
        categories = None
        if self.categories:
            categories = [c.api_name() for c in self.categories]

        data = {
            "id": str(self.id) if self.id is not None else None,
            "scope": self.scope.api_name(),
            "scopeId": self.scope_id,
            "categories": categories,
            "limit": self.limit,
            "window": self.window,
            "reasonCode": self.reason_code,
        }

        return prune_empty_keys(data)


class RateLimit:
    """
    Return value of ``quotas.is_rate_limited``.
    """

    __slots__ = ["is_limited", "retry_after", "reason", "reason_code"]

    def __init__(self, is_limited, retry_after=None, reason=None, reason_code=None):
        self.is_limited = is_limited
        # delta of seconds in the future to retry
        self.retry_after = retry_after
        # human readable description
        self.reason = reason
        # machine readable description
        self.reason_code = reason_code

    def to_dict(self):
        """
        Converts the object into a plain dictionary
        :return: a dict containing the non None elm of the RateLimit

        >>> x = RateLimit(is_limited = False, retry_after = 33)
        >>> x.to_dict() == {'is_limited': False, 'retry_after': 33}
        True

        """
        return {
            name: getattr(self, name, None)
            for name in self.__slots__
            if getattr(self, name, None) is not None
        }


class NotRateLimited(RateLimit):
    def __init__(self, **kwargs):
        super().__init__(False, **kwargs)


class RateLimited(RateLimit):
    def __init__(self, **kwargs):
        super().__init__(True, **kwargs)


def _limit_from_settings(x: Any) -> int | None:
    """
    limit=0 (or any falsy value) in database means "no limit". Convert that to
    limit=None as limit=0 in code means "reject all".
    """

    return int(x or 0) or None


def index_data_category(event_type: Optional[str], organization) -> DataCategory:
    if event_type == "transaction" and features.has(
        "organizations:transaction-metrics-extraction", organization
    ):
        # TODO: This logic should move into sentry-relay, once the consequences
        # of making `from_event_type` return `TRANSACTION_INDEXED` are clear.
        # https://github.com/getsentry/relay/blob/d77c489292123e53831e10281bd310c6a85c63cc/relay-server/src/envelope.rs#L121
        return DataCategory.TRANSACTION_INDEXED

    return DataCategory.from_event_type(event_type)


class Quota(Service):
    """
    Quotas handle tracking a project's usage and respond whether or not a
    project has been configured to throttle incoming data if they go beyond the
    specified quota.

    Quotas can specify a window to be tracked in, such as per minute or per
    hour. Additionally, quotas allow to specify the data categories they apply
    to, for example error events or attachments. For more information on quota
    parameters, see ``QuotaConfig``.

    To retrieve a list of active quotas, use ``quotas.get_quotas``. Also, to
    check the current status of quota usage, call ``quotas.get_usage``.
    """

    __all__ = (
        "get_maximum_quota",
        "get_project_abuse_quotas",
        "get_project_quota",
        "get_organization_quota",
        "is_rate_limited",
        "validate",
        "refund",
        "get_event_retention",
        "get_quotas",
        "get_blended_sample_rate",
        "get_transaction_sampling_tier_for_volume",
    )

    def __init__(self, **options):
        pass

    def get_quotas(self, project, key=None, keys=None):
        """
        Returns a quotas for the given project and its organization.

        The return values are instances of ``QuotaConfig``. See its
        documentation for more information about the values.

        :param project: The project instance that is used to determine quotas.
        :param key:     A project project key to obtain quotas for. If omitted,
                        only project and organization quotas are used.
        :param keys:    Similar to ``key``, except for multiple keys.
        """
        return []

    def is_rate_limited(self, project, key=None):
        """
        Checks whether any of the quotas in effect for the given project and
        project key has been exceeded and records consumption of the quota.

        By invoking this method, the caller signals that data is being ingested
        and needs to be counted against the quota. This increment happens
        atomically if none of the quotas have been exceeded. Otherwise, a rate
        limit is returned and data is not counted against the quotas.

        When an event or any other data is dropped after ``is_rate_limited`` has
        been called, use ``quotas.refund``.

        If no key is specified, then only organization-wide and project-wide
        quotas are checked. If a key is specified, then key-quotas are also
        checked.

        The return value is a subclass of ``RateLimit``:

         - ``RateLimited``, if at least one quota has been exceeded. The event
           should not be ingested by the caller, and none of the quotas have
           been counted.

         - ``NotRateLimited``, if consumption is within all quotas. Data must be
           ingested by the caller, and the counters for all counters have been
           incremented.

        :param project: The project instance that is used to determine quotas.
        :param key:     A project key to obtain quotas for. If omitted, only
                        project and organization quotas are used.
        """
        return NotRateLimited()

    def refund(self, project, key=None, timestamp=None, category=None, quantity=None):
        """
        Signals event rejection after ``quotas.is_rate_limited`` has been called
        successfully, and refunds the previously consumed quota.

        :param project:   The project that the dropped data belonged to.
        :param key:       The project key that was used to ingest the data. If
                          omitted, then only project and organization quotas are
                          refunded.
        :param timestamp: The timestamp at which data was ingested. This is used
                          to determine the correct quota window to refund the
                          previously consumed data to.
        :param category:  The data category of the item to refund. This is used
                          to determine the quotas that should be refunded.
                          Defaults to ``DataCategory.ERROR``.
        :param quantity:  The quantity to refund. Defaults to ``1``, which is
                          the only value that should be used for events. For
                          attachments, this should be set to the size of the
                          attachment in bytes.
        """

    def get_event_retention(self, organization):
        """
        Returns the retention for events in the given organization in days.
        Returns ``None`` if events are to be stored indefinitely.

        :param organization: The organization model.
        """
        return _limit_from_settings(options.get("system.event-retention-days"))

    def validate(self):
        """
        Validates that the quota service is operational.
        """

    def _translate_quota(self, quota, parent_quota):
        if str(quota).endswith("%"):
            pct = int(quota[:-1])
            quota = int(parent_quota or 0) * pct / 100

        return _limit_from_settings(quota or parent_quota)

    def get_key_quota(self, key):
        from sentry import features

        # XXX(epurkhiser): Avoid excessive feature manager checks (which can be
        # expensive depending on feature handlers) for project rate limits.
        # This happens on /store.
        cache_key = f"project:{key.project.id}:features:rate-limits"

        has_rate_limits = cache.get(cache_key)
        if has_rate_limits is None:
            has_rate_limits = features.has("projects:rate-limits", key.project)
            cache.set(cache_key, has_rate_limits, 600)

        if not has_rate_limits:
            return (None, None)

        limit, window = key.rate_limit
        return _limit_from_settings(limit), window

    def get_project_abuse_quotas(self, org):
        # Per-project abuse quotas for errors, transactions, attachments, sessions.
        global_abuse_window = options.get("project-abuse-quota.window")

        for option, compat_options, id, categories in (
            (
                "project-abuse-quota.error-limit",
                (
                    "sentry:project-error-limit",
                    "getsentry.rate-limit.project-errors",
                ),
                "pae",
                DataCategory.error_categories(),
            ),
            (
                "project-abuse-quota.transaction-limit",
                (
                    "sentry:project-transaction-limit",
                    "getsentry.rate-limit.project-transactions",
                ),
                "pati",  # project abuse transaction indexed limit
                (index_data_category("transaction", org),),
            ),
            (
                "project-abuse-quota.attachment-limit",
                (),
                "paa",
                (DataCategory.ATTACHMENT,),
            ),
            (
                "project-abuse-quota.session-limit",
                (),
                "pas",
                (DataCategory.SESSION,),
            ),
        ):
            limit: int | None = 0
            abuse_window = global_abuse_window
            # compat_options were previously present in getsentry
            # for errors and transactions. The first one is the org
            # option for overriding the global option, the second one.
            # For now, these deprecated ones take precedence over the new
            # to preserve existing behavior.
            if compat_options:
                limit = org.get_option(compat_options[0])
                if not limit:
                    limit = options.get(compat_options[1])

            if not limit:
                limit = org.get_option(option)
                if not limit:
                    limit = options.get(option)

            limit = _limit_from_settings(limit)
            if limit is None:
                # Unlimited.
                continue

            # Negative limits in config mean a reject-all quota.
            if limit < 0:
                yield QuotaConfig(
                    scope=QuotaScope.PROJECT,
                    categories=categories,
                    limit=0,
                    reason_code="disabled",
                )

            else:
                yield QuotaConfig(
                    id=id,
                    limit=limit * abuse_window,
                    scope=QuotaScope.PROJECT,
                    categories=categories,
                    window=abuse_window,
                    # XXX: This reason code is hardcoded RateLimitReasonLabel.PROJECT_ABUSE_LIMIT
                    #      from getsentry. Don't change it here.
                    #      If it's changed in getsentry, it needs to be synced here.
                    reason_code="project_abuse_limit",
                )

    def get_project_quota(self, project):
        from sentry.models import Organization, OrganizationOption

        if not project.is_field_cached("organization"):
            project.set_cached_field_value(
                "organization", Organization.objects.get_from_cache(id=project.organization_id)
            )

        org = project.organization

        max_quota_share = int(
            OrganizationOption.objects.get_value(org, "sentry:project-rate-limit", 100)
        )

        org_quota, window = self.get_organization_quota(org)

        if max_quota_share != 100 and org_quota:
            quota = self._translate_quota(f"{max_quota_share}%", org_quota)
        else:
            quota = None

        return (quota, window)

    def get_organization_quota(self, organization):
        from sentry.models import OrganizationOption

        account_limit = _limit_from_settings(
            OrganizationOption.objects.get_value(
                organization=organization, key="sentry:account-rate-limit", default=0
            )
        )

        system_limit = _limit_from_settings(options.get("system.rate-limit"))

        # If there is only a single org, this one org should
        # be allowed to consume the entire quota.
        if settings.SENTRY_SINGLE_ORGANIZATION or account_limit:
            if system_limit and (not account_limit or system_limit < account_limit / 60):
                return (system_limit, 60)
            # an account limit is enforced, which is set as a fixed value and cannot
            # utilize percentage based limits
            return (account_limit, 3600)

        default_limit = self._translate_quota(
            settings.SENTRY_DEFAULT_MAX_EVENTS_PER_MINUTE, system_limit
        )
        return (default_limit, 60)

    def get_maximum_quota(self, organization):
        """
        Return the maximum capable rate for an organization.
        """
        return (_limit_from_settings(options.get("system.rate-limit")), 60)

    def get_blended_sample_rate(
        self, project: Optional[Project] = None, organization_id: Optional[int] = None
    ) -> Optional[float]:
        """
        Returns the blended sample rate for an org based on the package that they are currently on. Returns ``None``
        if the the organization doesn't have dynamic sampling.

        The reasoning for having two params as `Optional` is because this method was first designed to work with
        `Project` but due to requirements change the `Organization` was needed and since we can get the `Organization`
        from the `Project` we allow one or the other to be passed.

        :param project: The project model.
        :param organization_id: The organization id.
        """

    def get_transaction_sampling_tier_for_volume(
        self, organization_id: int, volume: int
    ) -> Optional[Tuple[int, float]]:
        """
        Returns the transaction sampling tier closest to a specific volume.

        The organization_id is required because the tier is based on the organization's plan, and we have to check
        whether the organization has dynamic sampling.

        :param organization_id: The organization id.
        :param volume: The volume of transaction of the given project.
        """
