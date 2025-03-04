import logging
from enum import Enum

import jsonschema
import sentry_sdk
from django.db import models
from django.utils import timezone

from sentry.backup.scopes import RelocationScope
from sentry.db.models import FlexibleForeignKey, JSONField, Model, region_silo_only_model
from sentry.models import Activity
from sentry.models.grouphistory import (
    GroupHistoryStatus,
    bulk_record_group_history,
    record_group_history,
)
from sentry.types.activity import ActivityType

INBOX_REASON_DETAILS = {
    "type": ["object", "null"],
    "properties": {
        "until": {"type": ["string", "null"], "format": "date-time"},
        "count": {"type": ["integer", "null"]},
        "window": {"type": ["integer", "null"]},
        "user_count": {"type": ["integer", "null"]},
        "user_window": {"type": ["integer", "null"]},
    },
    "required": [],
    "additionalProperties": False,
}


class GroupInboxReason(Enum):
    NEW = 0
    REGRESSION = 2
    MANUAL = 3
    REPROCESSED = 4
    ESCALATING = 5
    ONGOING = 6

    # DEPRECATED: Use ONGOING instead
    UNIGNORED = 1


class GroupInboxRemoveAction(Enum):
    RESOLVED = "resolved"
    IGNORED = "ignored"
    MARK_REVIEWED = "mark_reviewed"


@region_silo_only_model
class GroupInbox(Model):
    """
    A Group that is in the inbox.
    """

    __relocation_scope__ = RelocationScope.Excluded

    group = FlexibleForeignKey("sentry.Group", unique=True, db_constraint=False)
    project = FlexibleForeignKey("sentry.Project", null=True, db_constraint=False)
    organization = FlexibleForeignKey("sentry.Organization", null=True, db_constraint=False)
    reason = models.PositiveSmallIntegerField(null=False, default=GroupInboxReason.NEW.value)
    reason_details = JSONField(null=True)
    date_added = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label = "sentry"
        db_table = "sentry_groupinbox"
        index_together = (("project", "date_added"),)


def add_group_to_inbox(group, reason, reason_details=None):
    if reason_details is not None:
        if "until" in reason_details and reason_details["until"] is not None:
            reason_details["until"] = reason_details["until"].replace(microsecond=0).isoformat()

    try:
        jsonschema.validate(reason_details, INBOX_REASON_DETAILS)
    except jsonschema.ValidationError:
        logging.error(f"GroupInbox invalid jsonschema: {reason_details}")
        reason_details = None

    group_inbox, created = GroupInbox.objects.get_or_create(
        group=group,
        defaults={
            "project": group.project,
            "organization_id": group.project.organization_id,
            "reason": reason.value,
            "reason_details": reason_details,
        },
    )

    return group_inbox


def remove_group_from_inbox(group, action=None, user=None, referrer=None):
    try:
        group_inbox = GroupInbox.objects.get(group=group)
        group_inbox.delete()

        if action is GroupInboxRemoveAction.MARK_REVIEWED and user is not None:
            Activity.objects.create(
                project_id=group_inbox.group.project_id,
                group_id=group_inbox.group_id,
                type=ActivityType.MARK_REVIEWED.value,
                user_id=user.id,
            )
            record_group_history(group, GroupHistoryStatus.REVIEWED, actor=user)
    except GroupInbox.DoesNotExist:
        pass


def bulk_remove_groups_from_inbox(groups, action=None, user=None, referrer=None):
    with sentry_sdk.start_span(description="bulk_remove_groups_from_inbox"):
        try:
            group_inbox = GroupInbox.objects.filter(group__in=groups)
            group_inbox.delete()

            if action is GroupInboxRemoveAction.MARK_REVIEWED and user is not None:
                Activity.objects.bulk_create(
                    [
                        Activity(
                            project_id=group_inbox_item.group.project_id,
                            group_id=group_inbox_item.group.id,
                            type=ActivityType.MARK_REVIEWED.value,
                            user_id=user.id,
                        )
                        for group_inbox_item in group_inbox
                    ]
                )

                bulk_record_group_history(groups, GroupHistoryStatus.REVIEWED, actor=user)
        except GroupInbox.DoesNotExist:
            pass


def get_inbox_details(group_list):
    group_ids = [g.id for g in group_list]
    group_inboxes = GroupInbox.objects.filter(group__in=group_ids)
    inbox_stats = {
        gi.group_id: {
            "reason": gi.reason,
            "reason_details": gi.reason_details,
            "date_added": gi.date_added,
        }
        for gi in group_inboxes
    }

    return inbox_stats
