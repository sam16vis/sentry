from copy import deepcopy
from datetime import datetime

from django.db.models import DateTimeField, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.timezone import make_aware
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import features
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import Endpoint, region_silo_endpoint
from sentry.api.bases.organization import OrganizationAlertRulePermission, OrganizationEndpoint
from sentry.api.exceptions import ResourceDoesNotExist
from sentry.api.paginator import (
    CombinedQuerysetIntermediary,
    CombinedQuerysetPaginator,
    OffsetPaginator,
)
from sentry.api.serializers import serialize
from sentry.api.serializers.models.alert_rule import CombinedRuleSerializer
from sentry.api.utils import InvalidParams
from sentry.constants import ObjectStatus
from sentry.incidents.logic import get_slack_actions_with_async_lookups
from sentry.incidents.models import AlertRule, Incident
from sentry.incidents.serializers import AlertRuleSerializer
from sentry.incidents.utils.sentry_apps import trigger_sentry_app_action_creators_for_incidents
from sentry.integrations.slack.utils import RedisRuleStatus
from sentry.models import OrganizationMemberTeam, Project, Rule, Team
from sentry.models.rule import RuleSource
from sentry.services.hybrid_cloud.app import app_service
from sentry.signals import alert_rule_created
from sentry.snuba.dataset import Dataset
from sentry.tasks.integrations.slack import find_channel_id_for_alert_rule
from sentry.utils.cursors import Cursor, StringCursor

from .utils import parse_team_params


class AlertRuleIndexMixin(Endpoint):
    def fetch_metric_alert(self, request, organization, project=None):
        if not features.has("organizations:incidents", organization, actor=request.user):
            raise ResourceDoesNotExist

        if not project:
            projects = self.get_projects(request, organization)
            alert_rules = AlertRule.objects.fetch_for_organization(organization, projects)
        else:
            alert_rules = AlertRule.objects.fetch_for_project(project)
        if not features.has("organizations:performance-view", organization):
            # Filter to only error alert rules
            alert_rules = alert_rules.filter(snuba_query__dataset=Dataset.Events.value)

        return self.paginate(
            request,
            queryset=alert_rules,
            order_by="-date_added",
            paginator_cls=OffsetPaginator,
            on_results=lambda x: serialize(x, request.user),
            default_per_page=25,
        )

    def create_metric_alert(self, request, organization, project=None):
        if not features.has("organizations:incidents", organization, actor=request.user):
            raise ResourceDoesNotExist

        data = deepcopy(request.data)
        if project:
            data["projects"] = [project.slug]

        serializer = AlertRuleSerializer(
            context={
                "organization": organization,
                "access": request.access,
                "user": request.user,
                "ip_address": request.META.get("REMOTE_ADDR"),
                "installations": app_service.get_installed_for_organization(
                    organization_id=organization.id
                ),
            },
            data=data,
        )
        if serializer.is_valid():
            trigger_sentry_app_action_creators_for_incidents(serializer.validated_data)
            if get_slack_actions_with_async_lookups(organization, request.user, request.data):
                # need to kick off an async job for Slack
                client = RedisRuleStatus()
                task_args = {
                    "organization_id": organization.id,
                    "uuid": client.uuid,
                    "data": request.data,
                    "user_id": request.user.id,
                }
                find_channel_id_for_alert_rule.apply_async(kwargs=task_args)
                return Response({"uuid": client.uuid}, status=202)
            else:
                alert_rule = serializer.save()
                referrer = request.query_params.get("referrer")
                session_id = request.query_params.get("sessionId")
                duplicate_rule = request.query_params.get("duplicateRule")
                wizard_v3 = request.query_params.get("wizardV3")
                subscriptions = alert_rule.snuba_query.subscriptions.all()
                for sub in subscriptions:
                    alert_rule_created.send_robust(
                        user=request.user,
                        project=sub.project,
                        rule=alert_rule,
                        rule_type="metric",
                        sender=self,
                        referrer=referrer,
                        session_id=session_id,
                        is_api_token=request.auth is not None,
                        duplicate_rule=duplicate_rule,
                        wizard_v3=wizard_v3,
                    )
                return Response(serialize(alert_rule, request.user), status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@region_silo_endpoint
class OrganizationCombinedRuleIndexEndpoint(OrganizationEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
    }

    def get(self, request: Request, organization) -> Response:
        """
        Fetches (metric) alert rules and legacy (issue alert) rules for an organization
        """
        project_ids = self.get_requested_project_ids_unchecked(request) or None
        if project_ids == {-1}:  # All projects for org:
            project_ids = Project.objects.filter(
                organization=organization, status=ObjectStatus.ACTIVE
            ).values_list("id", flat=True)
        elif project_ids is None:  # All projects for user
            org_team_list = Team.objects.filter(organization=organization).values_list(
                "id", flat=True
            )
            user_team_list = OrganizationMemberTeam.objects.filter(
                organizationmember__user_id=request.user.id, team__in=org_team_list
            ).values_list("team", flat=True)
            project_ids = Project.objects.filter(
                teams__in=user_team_list, status=ObjectStatus.ACTIVE
            ).values_list("id", flat=True)

        # Materialize the project ids here. This helps us to not overwhelm the query planner with
        # overcomplicated subqueries. Previously, this was causing Postgres to use a suboptimal
        # index to filter on. Also enforces permission checks.
        projects = self.get_projects(request, organization, project_ids=set(project_ids))

        teams = request.GET.getlist("team", [])
        team_filter_query = None
        if len(teams) > 0:
            try:
                teams_query, unassigned = parse_team_params(request, organization, teams)
            except InvalidParams as err:
                return Response(str(err), status=status.HTTP_400_BAD_REQUEST)

            team_filter_query = Q(owner_id__in=teams_query.values_list("actor_id", flat=True))
            if unassigned:
                team_filter_query = team_filter_query | Q(owner_id=None)

        alert_rules = AlertRule.objects.fetch_for_organization(organization, projects)
        if not features.has("organizations:performance-view", organization):
            # Filter to only error alert rules
            alert_rules = alert_rules.filter(snuba_query__dataset=Dataset.Events.value)
        issue_rules = Rule.objects.filter(
            status__in=[ObjectStatus.ACTIVE, ObjectStatus.DISABLED],
            source__in=[RuleSource.ISSUE],
            project__in=projects,
        )
        name = request.GET.get("name", None)
        if name:
            alert_rules = alert_rules.filter(Q(name__icontains=name))
            issue_rules = issue_rules.filter(Q(label__icontains=name))

        if team_filter_query:
            alert_rules = alert_rules.filter(team_filter_query)
            issue_rules = issue_rules.filter(team_filter_query)

        expand = request.GET.getlist("expand", [])
        if "latestIncident" in expand:
            alert_rules = alert_rules.annotate(
                incident_id=Coalesce(
                    Subquery(
                        Incident.objects.filter(alert_rule=OuterRef("pk"))
                        .order_by("-date_started")
                        .values("id")[:1]
                    ),
                    Value(-1),
                )
            )

        is_asc = request.GET.get("asc", False) == "1"
        sort_key = request.GET.getlist("sort", ["date_added"])
        rule_sort_key = [
            "label" if x == "name" else x for x in sort_key
        ]  # Rule's don't share the same field name for their title/label/name...so we account for that here.
        case_insensitive = sort_key == ["name"]

        if "incident_status" in sort_key:
            alert_rules = alert_rules.annotate(
                incident_status=Coalesce(
                    Subquery(
                        Incident.objects.filter(alert_rule=OuterRef("pk"))
                        .order_by("-date_started")
                        .values("status")[:1]
                    ),
                    Value(-1, output_field=IntegerField()),
                )
            )
            issue_rules = issue_rules.annotate(
                incident_status=Value(-2, output_field=IntegerField())
            )

        if "date_triggered" in sort_key:
            far_past_date = Value(make_aware(datetime.min), output_field=DateTimeField())
            alert_rules = alert_rules.annotate(
                date_triggered=Coalesce(
                    Subquery(
                        Incident.objects.filter(alert_rule=OuterRef("pk"))
                        .order_by("-date_started")
                        .values("date_started")[:1]
                    ),
                    far_past_date,
                ),
            )
            issue_rules = issue_rules.annotate(date_triggered=far_past_date)
        alert_rules_count = alert_rules.count()
        issue_rules_count = issue_rules.count()
        alert_rule_intermediary = CombinedQuerysetIntermediary(alert_rules, sort_key)
        rule_intermediary = CombinedQuerysetIntermediary(issue_rules, rule_sort_key)
        response = self.paginate(
            request,
            paginator_cls=CombinedQuerysetPaginator,
            on_results=lambda x: serialize(x, request.user, CombinedRuleSerializer(expand=expand)),
            default_per_page=25,
            intermediaries=[alert_rule_intermediary, rule_intermediary],
            desc=not is_asc,
            cursor_cls=StringCursor if case_insensitive else Cursor,
            case_insensitive=case_insensitive,
        )
        response["X-Sentry-Issue-Rule-Hits"] = issue_rules_count
        response["X-Sentry-Alert-Rule-Hits"] = alert_rules_count
        return response


@region_silo_endpoint
class OrganizationAlertRuleIndexEndpoint(OrganizationEndpoint, AlertRuleIndexMixin):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
        "POST": ApiPublishStatus.UNKNOWN,
    }
    permission_classes = (OrganizationAlertRulePermission,)

    def get(self, request: Request, organization) -> Response:
        """
        Fetches metric alert rules for an organization
        """
        return self.fetch_metric_alert(request, organization)

    def post(self, request: Request, organization) -> Response:
        """
        Create a metric alert rule
        """
        return self.create_metric_alert(request, organization)
