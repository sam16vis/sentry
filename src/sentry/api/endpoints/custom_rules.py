from datetime import datetime, timedelta, timezone
from typing import List, Optional, cast

from django.db import DatabaseError
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import features
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases import OrganizationEndpoint
from sentry.api.event_search import parse_search_query
from sentry.exceptions import InvalidSearchQuery
from sentry.models import CustomDynamicSamplingRule, TooManyRules
from sentry.models.dynamicsampling import CUSTOM_RULE_DATE_FORMAT
from sentry.models.organization import Organization
from sentry.models.project import Project
from sentry.snuba.metrics.extraction import RuleCondition, SearchQueryConverter
from sentry.utils import json
from sentry.utils.dates import parse_stats_period

MAX_RULE_PERIOD_STRING = "6h"
MAX_RULE_PERIOD = parse_stats_period(MAX_RULE_PERIOD_STRING)
DEFAULT_PERIOD_STRING = "1h"
# the number of samples to collect per custom rule
NUM_SAMPLES_PER_CUSTOM_RULE = 100


class CustomRulesInputSerializer(serializers.Serializer):
    """
    Request data serializer
    """

    # the query string in the same format as the Discover query
    query = serializers.CharField(required=False, allow_blank=True)
    # desired time period for collection (it may be overriden if too long)
    period = serializers.CharField(required=False)
    # list of project ids to collect data from
    projects = serializers.ListField(child=serializers.IntegerField(), required=False)

    def validate(self, data):
        """
        Optional fields cannot be validated with validate_<FIELD_NAME> so we need to do it here for the
        `period` & 'projects' & overrideExisting fields
        """
        if data.get("projects") is None:
            data["projects"] = []

        # check that the project exists
        invalid_projects = []

        data["projects"] = _clean_project_list(data["projects"])
        requested_projects = data["projects"]

        available_projects = {p.id for p in Project.objects.get_many_from_cache(data["projects"])}
        for project_id in requested_projects:
            if project_id not in available_projects:
                invalid_projects.append(f"invalid project id: {project_id}")

        if invalid_projects:
            raise serializers.ValidationError({"projects": invalid_projects})

        period = data.get("period")
        if period is None:
            data["period"] = DEFAULT_PERIOD_STRING
        else:
            try:
                period = parse_stats_period(period)
            except OverflowError:
                data["period"] = MAX_RULE_PERIOD_STRING
            if period is None:
                raise serializers.ValidationError("Invalid period")
            if period > MAX_RULE_PERIOD:
                # limit the expiry period
                data["period"] = MAX_RULE_PERIOD_STRING
        return data


@region_silo_endpoint
class CustomRulesEndpoint(OrganizationEndpoint):
    owner = ApiOwner.TELEMETRY_EXPERIENCE

    publish_status = {
        "POST": ApiPublishStatus.EXPERIMENTAL,
        "GET": ApiPublishStatus.EXPERIMENTAL,
    }

    def post(self, request: Request, organization: Organization) -> Response:

        if not features.has("organizations:investigation-bias", organization, actor=request.user):
            return Response(status=404)

        serializer = CustomRulesInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        query = serializer.validated_data["query"]
        projects = serializer.validated_data.get("projects")
        period = serializer.validated_data.get("period")
        try:
            condition = _get_condition(query)

            # the parsing must succeed (it passed validation)
            delta = cast(timedelta, parse_stats_period(period))
            now = datetime.now(tz=timezone.utc)
            start = now
            end = now + delta

            rule = CustomDynamicSamplingRule.update_or_create(
                condition=condition,
                start=start,
                end=end,
                project_ids=projects,
                organization_id=organization.id,
                num_samples=NUM_SAMPLES_PER_CUSTOM_RULE,
                sample_rate=1.0,
            )

            return _rule_to_response(rule)
        except InvalidSearchQuery as e:
            return Response({"query": [str(e)]}, status=400)

        except DatabaseError:
            return Response(
                {"projects": ["Could not save rule, probably wrong project ids"]}, status=400
            )
        except TooManyRules:
            return Response(
                {
                    "error": [
                        "Too many investigation rules active for this organization."
                        "Wait until some expire or delete some rules."
                    ]
                },
                status=429,
            )
        except ValueError as e:
            return Response({"query": ["Could not convert to rule", str(e)]}, status=400)

    def get(self, request: Request, organization: Organization) -> Response:
        requested_projects = request.GET.getlist("project")
        query = request.GET.get("query")

        try:
            requested_projects_ids = [int(project_id) for project_id in requested_projects]
            requested_projects_ids = _clean_project_list(requested_projects_ids)
        except ValueError:
            return Response({"projects": ["Invalid project id"]}, status=400)

        if requested_projects_ids:
            org_rule = False
            invalid_projects = []
            available_projects = {
                p.id for p in Project.objects.get_many_from_cache(requested_projects_ids)
            }
            for project_id in requested_projects_ids:
                if project_id not in available_projects:
                    invalid_projects.append(f"invalid project id: {project_id}")

            if invalid_projects:
                raise serializers.ValidationError({"projects": invalid_projects})
        else:
            # no project specified (it is an org rule)
            org_rule = True

        try:
            condition = _get_condition(query)
        except InvalidSearchQuery as e:
            return Response({"query": [str(e)]}, status=400)
        except ValueError as e:
            return Response({"query": ["Could not convert to rule", str(e)]}, status=400)

        rule = CustomDynamicSamplingRule.get_rule_for_org(condition, organization.id)

        if rule is None:
            return Response(status=204)  # no rule found, nothing to reutrn

        # we have a rule, check to see if the projects match

        if rule.is_org_level:
            # a rule org covers all projects
            return _rule_to_response(rule)

        if not rule.is_org_level and org_rule:
            # we need an org rule and we have a simple rule return not found
            return Response(status=204)

        # project rule request and project rule found # see if we have all projects
        available_projects = {p.id for p in rule.projects.all()}
        for project_id in requested_projects_ids:
            if project_id not in available_projects:
                return Response(status=204)

        # the rule covers all projects
        return _rule_to_response(rule)


def _rule_to_response(rule: CustomDynamicSamplingRule) -> Response:
    response_data = {
        "ruleId": rule.external_rule_id,
        "condition": json.loads(rule.condition),
        "startDate": rule.start_date.strftime(CUSTOM_RULE_DATE_FORMAT),
        "endDate": rule.end_date.strftime(CUSTOM_RULE_DATE_FORMAT),
        "numSamples": rule.num_samples,
        "sampleRate": rule.sample_rate,
        "dateAdded": rule.date_added.strftime(CUSTOM_RULE_DATE_FORMAT),
        "projects": [project.id for project in rule.projects.all()],
        "orgId": rule.organization.id,
    }
    return Response(response_data, status=200)


def _get_condition(query: Optional[str]) -> RuleCondition:
    if not query:
        # True condition when query not specified
        condition: RuleCondition = {"op": "and", "inner": []}
    else:
        tokens = parse_search_query(query)
        converter = SearchQueryConverter(tokens)
        condition = converter.convert()
    return condition


def _clean_project_list(project_ids: List[int]) -> List[int]:
    if len(project_ids) == 1 and project_ids[0] == -1:
        # special case for all projects convention ( sends a project id of -1)
        return []
    return project_ids
