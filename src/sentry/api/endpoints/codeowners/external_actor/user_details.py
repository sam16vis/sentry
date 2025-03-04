from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.external_actor import ExternalActorEndpointMixin, ExternalUserSerializer
from sentry.api.bases.organization import OrganizationEndpoint
from sentry.api.serializers import serialize
from sentry.models import ExternalActor, Organization

logger = logging.getLogger(__name__)


@region_silo_endpoint
class ExternalUserDetailsEndpoint(OrganizationEndpoint, ExternalActorEndpointMixin):
    publish_status = {
        "DELETE": ApiPublishStatus.UNKNOWN,
        "PUT": ApiPublishStatus.UNKNOWN,
    }

    def convert_args(  # type: ignore[override]
        self,
        request: Request,
        organization_slug: str,
        external_user_id: int,
        *args: Any,
        **kwargs: Any,
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        args, kwargs = super().convert_args(request, organization_slug, *args, **kwargs)
        kwargs["external_user"] = self.get_external_actor_or_404(
            external_user_id, kwargs["organization"]
        )
        return args, kwargs

    def put(
        self, request: Request, organization: Organization, external_user: ExternalActor
    ) -> Response:
        """
        Update an External User
        `````````````

        :pparam string organization_slug: the slug of the organization the
                                          user belongs to.
        :pparam int user_id: the User id.
        :pparam string external_user_id: id of external_user object
        :param string external_id: the associated user ID for this provider
        :param string external_name: the Github/Gitlab user name.
        :param string provider: enum("github","gitlab")
        :auth: required
        """
        self.assert_has_feature(request, organization)

        serializer = ExternalUserSerializer(
            instance=external_user,
            data=request.data,
            context={"organization": organization},
            partial=True,
        )
        if serializer.is_valid():
            updated_external_user = serializer.save()

            return Response(
                serialize(updated_external_user, request.user), status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(
        self, request: Request, organization: Organization, external_user: ExternalActor
    ) -> Response:
        """
        Delete an External Team
        """
        external_user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
