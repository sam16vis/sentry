import logging
from typing import Dict

from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import audit_log
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.organization import OrganizationEndpoint, OrganizationPermission
from sentry.api.paginator import OffsetPaginator
from sentry.api.serializers.base import serialize
from sentry.api.serializers.rest_framework.notification_action import NotificationActionSerializer
from sentry.models.notificationaction import NotificationAction
from sentry.models.organization import Organization

logger = logging.getLogger(__name__)


class NotificationActionsPermission(OrganizationPermission):
    scope_map = {
        "GET": ["org:read", "org:write", "org:admin"],
        "POST": [
            "org:read",
            "org:write",
            "org:admin",
        ],
        "PUT": [
            "org:read",
            "org:write",
            "org:admin",
        ],
        "DELETE": [
            "org:read",
            "org:write",
            "org:admin",
        ],
    }


@region_silo_endpoint
class NotificationActionsIndexEndpoint(OrganizationEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.EXPERIMENTAL,
        "POST": ApiPublishStatus.EXPERIMENTAL,
    }

    owner = ApiOwner.ENTERPRISE

    """
    View existing NotificationActions or create a new one.
    GET: Returns paginated, serialized NotificationActions for an organization
    POST: Create a new NotificationAction
    """

    permission_classes = (NotificationActionsPermission,)

    def get(self, request: Request, organization: Organization) -> Response:
        queryset = NotificationAction.objects.filter(organization_id=organization.id)
        # If a project query is specified, filter out non-project-specific actions
        # otherwise, include them but still ensure project permissions are enforced
        project_query = (
            Q(projects__in=self.get_projects(request, organization))
            if self.get_requested_project_ids_unchecked(request)
            else Q(projects=None) | Q(projects__in=self.get_projects(request, organization))
        )
        queryset = queryset.filter(project_query).distinct()
        trigger_type_query = request.GET.getlist("triggerType")
        if trigger_type_query:
            triggers: Dict[str, int] = {v: k for k, v in NotificationAction.get_trigger_types()}
            trigger_types = map(lambda t: triggers.get(t), trigger_type_query)
            queryset = queryset.filter(trigger_type__in=trigger_types)
        logger.info(
            "notification_action.get_all",
            extra={
                "organization_id": organization.id,
                "trigger_type_query": trigger_type_query,
                "project_query": self.get_requested_project_ids_unchecked(request),
            },
        )
        return self.paginate(
            request=request,
            queryset=queryset,
            on_results=lambda action: serialize(action, request.user),
            paginator_cls=OffsetPaginator,
        )

    def post(self, request: Request, organization: Organization) -> Response:
        # team admins and regular org members don't have project:write on an org level
        if not request.access.has_scope("project:write"):
            # check if user has access to create notification actions for all requested projects
            requested_projects = request.data.get("projects", [])
            projects = self.get_projects(request, organization)
            project_slugs = [project.slug for project in projects]
            missing_access_projects = set(requested_projects).difference(set(project_slugs))

            if missing_access_projects:
                raise PermissionDenied(
                    detail="You do not have permission to create notification actions for projects "
                    + str(list(missing_access_projects))
                )
            # team admins will have project:write scoped to their projects, members will not
            team_admin_has_access = all(
                [request.access.has_project_scope(project, "project:write") for project in projects]
            )
            # all() returns True for empty list, so include a check for it
            if not team_admin_has_access or not projects:
                raise PermissionDenied

        serializer = NotificationActionSerializer(
            context={"access": request.access, "organization": organization},
            data=request.data,
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        action = serializer.save()
        logger.info(
            "notification_action.create",
            extra={"organization_id": organization.id, "action_id": action.id},
        )
        self.create_audit_entry(
            request=request,
            organization=organization,
            target_object=action.id,
            event=audit_log.get_event_id("NOTIFICATION_ACTION_ADD"),
            data=action.get_audit_log_data(),
        )
        return Response(serialize(action, request.user), status=status.HTTP_201_CREATED)
