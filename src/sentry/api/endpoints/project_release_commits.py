from rest_framework.request import Request
from rest_framework.response import Response

from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.project import ProjectEndpoint, ProjectReleasePermission
from sentry.api.exceptions import ResourceDoesNotExist
from sentry.api.serializers import serialize
from sentry.constants import ObjectStatus
from sentry.models import Release, ReleaseCommit, Repository


@region_silo_endpoint
class ProjectReleaseCommitsEndpoint(ProjectEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
    }
    permission_classes = (ProjectReleasePermission,)

    def get(self, request: Request, project, version) -> Response:
        """
        List a Project Release's Commits
        ````````````````````````````````

        Retrieve a list of commits for a given release.

        :pparam string organization_slug: the slug of the organization the
                                          release belongs to.
        :pparam string project_slug: the slug of the project to list the
                                     release files of.
        :pparam string version: the version identifier of the release.

        :pparam string repo_name: the repository name

        :auth: required
        """

        organization_id = project.organization_id

        try:
            release = Release.objects.get(
                organization_id=organization_id, projects=project, version=version
            )
        except Release.DoesNotExist:
            raise ResourceDoesNotExist

        queryset = ReleaseCommit.objects.filter(release=release).select_related(
            "commit", "commit__author"
        )

        repo_id = request.query_params.get("repo_id")
        repo_name = request.query_params.get("repo_name")

        # prefer repo external ID to name
        if repo_id:
            try:
                repo = Repository.objects.get(
                    organization_id=organization_id, external_id=repo_id, status=ObjectStatus.ACTIVE
                )
                queryset = queryset.filter(commit__repository_id=repo.id)
            except Repository.DoesNotExist:
                raise ResourceDoesNotExist

        elif repo_name:
            try:
                repo = Repository.objects.get(
                    organization_id=organization_id, name=repo_name, status=ObjectStatus.ACTIVE
                )
                queryset = queryset.filter(commit__repository_id=repo.id)
            except Repository.DoesNotExist:
                raise ResourceDoesNotExist

        return self.paginate(
            request=request,
            queryset=queryset,
            order_by="order",
            on_results=lambda x: serialize([rc.commit for rc in x], request.user),
        )
