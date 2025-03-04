from typing import Any, Dict

from django.http import HttpResponse
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import features
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint

# from sentry.api.bases.organization import OrganizationEndpoint
from sentry.api.bases import NoProjects, OrganizationEventsV2EndpointBase
from sentry.exceptions import InvalidSearchQuery
from sentry.models import Organization
from sentry.profiles.flamegraph import (
    get_profile_ids,
    get_profile_ids_for_span_op,
    get_profile_ids_with_spans,
    get_profiles_with_function,
)
from sentry.profiles.utils import parse_profile_filters, proxy_profiling_service


class OrganizationProfilingBaseEndpoint(OrganizationEventsV2EndpointBase):
    owner = ApiOwner.PROFILING

    def get_profiling_params(self, request: Request, organization: Organization) -> Dict[str, Any]:
        try:
            params: Dict[str, Any] = parse_profile_filters(request.query_params.get("query", ""))
        except InvalidSearchQuery as err:
            raise ParseError(detail=str(err))

        params.update(self.get_filter_params(request, organization))

        return params


@region_silo_endpoint
class OrganizationProfilingFiltersEndpoint(OrganizationProfilingBaseEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
    }

    def get(self, request: Request, organization: Organization) -> HttpResponse:
        if not features.has("organizations:profiling", organization, actor=request.user):
            return Response(status=404)

        try:
            params = self.get_profiling_params(request, organization)
        except NoProjects:
            return Response([])

        kwargs = {"params": params}

        return proxy_profiling_service("GET", f"/organizations/{organization.id}/filters", **kwargs)


@region_silo_endpoint
class OrganizationProfilingFlamegraphEndpoint(OrganizationProfilingBaseEndpoint):
    publish_status = {
        "GET": ApiPublishStatus.UNKNOWN,
    }

    def get(self, request: Request, organization: Organization) -> HttpResponse:
        if not features.has("organizations:profiling", organization, actor=request.user):
            return Response(status=404)

        has_starfish = features.has("organizations:starfish-view", organization, actor=request.user)

        params = self.get_snuba_params(request, organization, check_global_views=False)
        project_ids = params["project_id"]
        if len(project_ids) > 1:
            raise ParseError(detail="You cannot get a flamegraph from multiple projects.")

        span_group = request.query_params.get("spans.group", None)
        span_op = request.query_params.get("spans.op", None)
        if span_group is not None:
            backend = request.query_params.get("backend", "indexed_spans")
            profile_ids = get_profile_ids_with_spans(
                organization.id,
                project_ids[0],
                params,
                span_group,
                backend,
                request.query_params.get("query", None),
            )
        elif span_op is not None and has_starfish:
            backend = "indexed_spans"
            profile_ids = get_profile_ids_for_span_op(
                organization.id,
                project_ids[0],
                params,
                span_op,
                backend,
                request.query_params.get("query", None),
            )
        elif "fingerprint" in request.query_params:
            function_fingerprint = int(request.query_params["fingerprint"])
            profile_ids = get_profiles_with_function(
                organization.id, project_ids[0], function_fingerprint, params
            )
        else:
            profile_ids = get_profile_ids(params, request.query_params.get("query", None))

        kwargs: Dict[str, Any] = {
            "method": "POST",
            "path": f"/organizations/{organization.id}/projects/{project_ids[0]}/flamegraph",
            "json_data": profile_ids,
        }
        return proxy_profiling_service(**kwargs)
