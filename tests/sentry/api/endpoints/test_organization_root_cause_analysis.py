from datetime import timedelta

import pytest
from django.urls import reverse

from sentry.snuba.metrics.naming_layer.mri import TransactionMRI
from sentry.testutils.cases import MetricsAPIBaseTestCase
from sentry.testutils.helpers.datetime import freeze_time, iso_format
from sentry.testutils.silo import region_silo_test
from sentry.utils.samples import load_data

FEATURES = ["organizations:performance-duration-regression-visible"]

pytestmark = [pytest.mark.sentry_metrics]


@region_silo_test(stable=True)
@freeze_time(MetricsAPIBaseTestCase.MOCK_DATETIME)
class OrganizationRootCauseAnalysisTest(MetricsAPIBaseTestCase):
    def setUp(self):
        super().setUp()
        self.login_as(self.user)
        self.org = self.create_organization(owner=self.user)
        self.project = self.create_project(organization=self.org)
        self.url = reverse(
            "sentry-api-0-organization-events-root-cause-analysis", args=[self.org.slug]
        )
        self.store_performance_metric(
            name=TransactionMRI.DURATION.value,
            tags={"transaction": "foo"},
            org_id=self.org.id,
            project_id=self.project.id,
            value=1,
        )
        self.trace_id = "a" * 32

    @property
    def now(self):
        return MetricsAPIBaseTestCase.MOCK_DATETIME.replace(tzinfo=None)

    def create_transaction(
        self,
        transaction,
        trace_id,
        span_id,
        parent_span_id,
        spans,
        project_id,
        start_timestamp,
        duration,
        transaction_id=None,
    ):
        timestamp = start_timestamp + timedelta(milliseconds=duration)

        data = load_data(
            "transaction",
            trace=trace_id,
            span_id=span_id,
            spans=spans,
            start_timestamp=start_timestamp,
            timestamp=timestamp,
        )
        if transaction_id is not None:
            data["event_id"] = transaction_id
        data["transaction"] = transaction
        data["contexts"]["trace"]["parent_span_id"] = parent_span_id
        return self.store_event(data, project_id=project_id)

    def test_404s_without_feature_flag(self):
        response = self.client.get(self.url, format="json")
        assert response.status_code == 404, response.content

    def test_transaction_name_required(self):
        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "project": self.project.id,
                    "breakpoint": (self.now - timedelta(days=1)).isoformat(),
                },
            )

        assert response.status_code == 400, response.content

    def test_project_id_required(self):
        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "transaction": "foo",
                },
            )

        assert response.status_code == 400, response.content

    def test_breakpoint_required(self):
        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={"transaction": "foo", "project": self.project.id},
            )

        assert response.status_code == 400, response.content

    def test_transaction_must_exist(self):
        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "transaction": "foo",
                    "project": self.project.id,
                    "breakpoint": self.now - timedelta(days=1),
                    "start": self.now - timedelta(days=3),
                    "end": self.now,
                },
            )

        assert response.status_code == 200, response.content

        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "transaction": "does not exist",
                    "project": self.project.id,
                    "breakpoint": self.now - timedelta(days=1),
                    "start": self.now - timedelta(days=3),
                    "end": self.now,
                },
            )

        assert response.status_code == 400, response.content

    # TODO: Enable this test when adding a serializer to handle validation
    # def test_breakpoint_must_be_in_the_past(self):
    #     with self.feature(FEATURES):
    #         response = self.client.get(
    #             self.url,
    #             format="json",
    #             data={
    #                 "transaction": "foo",
    #                 "project": self.project.id,
    #                 "breakpoint": (self.now + timedelta(days=1)).isoformat(),
    #             },
    #         )

    #     assert response.status_code == 400, response.content

    def test_returns_change_data_for_regressed_spans(self):
        before_timestamp = self.now - timedelta(days=2)
        before_span = {
            "parent_span_id": "a" * 16,
            "span_id": "e" * 16,
            "start_timestamp": iso_format(before_timestamp),
            "timestamp": iso_format(before_timestamp),
            "op": "django.middleware",
            "description": "middleware span",
            "exclusive_time": 60.0,
        }

        # before
        self.create_transaction(
            transaction="foo",
            trace_id=self.trace_id,
            span_id="a" * 16,
            parent_span_id="b" * 16,
            spans=[before_span],
            project_id=self.project.id,
            start_timestamp=before_timestamp,
            duration=60,
        )
        self.create_transaction(
            transaction="foo",
            trace_id=self.trace_id,
            span_id="b" * 16,
            parent_span_id="b" * 16,
            spans=[{**before_span, "op": "db", "description": "db span"}],
            project_id=self.project.id,
            start_timestamp=before_timestamp,
            duration=60,
        )

        # after
        after_timestamp = self.now - timedelta(hours=1)
        self.create_transaction(
            transaction="foo",
            trace_id=self.trace_id,
            span_id="c" * 16,
            parent_span_id="d" * 16,
            spans=[
                {
                    "parent_span_id": "e" * 16,
                    "span_id": "f" * 16,
                    "start_timestamp": iso_format(after_timestamp),
                    "timestamp": iso_format(after_timestamp),
                    "op": "django.middleware",
                    "description": "middleware span",
                    "exclusive_time": 40.0,
                },
                {
                    "parent_span_id": "1" * 16,
                    "span_id": "2" * 16,
                    "start_timestamp": iso_format(after_timestamp),
                    "timestamp": iso_format(after_timestamp),
                    "op": "django.middleware",
                    "description": "middleware span",
                    "exclusive_time": 600.0,
                },
                {
                    "parent_span_id": "1" * 16,
                    "span_id": "3" * 16,
                    "start_timestamp": iso_format(after_timestamp),
                    "timestamp": iso_format(after_timestamp),
                    "op": "django.middleware",
                    "description": "middleware span",
                    "exclusive_time": 60.0,
                },
                # This db span shouldn't appear in the results
                # since there are no changes
                {**before_span, "span_id": "5" * 16, "op": "db", "description": "db span"},
            ],
            project_id=self.project.id,
            start_timestamp=after_timestamp,
            duration=600,
        )

        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "transaction": "foo",
                    "project": self.project.id,
                    "breakpoint": self.now - timedelta(days=1),
                    "start": self.now - timedelta(days=3),
                    "end": self.now,
                },
            )

        assert response.status_code == 200, response.content

        # Check that sample IDs are gathered, but remove them from the data
        # for checking since they are randomized
        assert all("sample_event_id" in row for row in response.data)
        for row in response.data:
            del row["sample_event_id"]
        assert response.data == [
            {
                "span_op": "django.middleware",
                "span_group": "2b9cbb96dbf59baa",
                "span_description": "middleware span",
                "score_delta": 10.666666666666666,
                "freq_before": 1.0,
                "freq_after": 3.0,
                "freq_delta": 2.0,
                "duration_delta": 2.888888888888889,
                "duration_before": 60.0,
                "duration_after": 233.33333333333334,
            }
        ]

    def test_results_are_limited(self):
        # Before
        self.create_transaction(
            transaction="foo",
            trace_id=self.trace_id,
            span_id="a" * 16,
            parent_span_id="b" * 16,
            spans=[
                {
                    "parent_span_id": "a" * 16,
                    "span_id": "e" * 16,
                    "start_timestamp": iso_format(self.now - timedelta(days=2)),
                    "timestamp": iso_format(self.now - timedelta(days=2)),
                    "op": "django.middleware",
                    "description": "middleware span",
                    "exclusive_time": 60.0,
                }
            ],
            project_id=self.project.id,
            start_timestamp=self.now - timedelta(days=2),
            duration=60,
        )

        # After
        self.create_transaction(
            transaction="foo",
            trace_id=self.trace_id,
            span_id="a" * 16,
            parent_span_id="b" * 16,
            spans=[
                {
                    "parent_span_id": "a" * 16,
                    "span_id": "e" * 16,
                    "start_timestamp": iso_format(self.now - timedelta(hours=1)),
                    "timestamp": iso_format(self.now - timedelta(hours=1)),
                    "op": "django.middleware",
                    "description": "middleware span",
                    "exclusive_time": 100.0,
                },
                {
                    "parent_span_id": "a" * 16,
                    "span_id": "f" * 16,
                    "start_timestamp": iso_format(self.now - timedelta(hours=1)),
                    "timestamp": iso_format(self.now - timedelta(hours=1)),
                    "op": "db",
                    "description": "db",
                    "exclusive_time": 100.0,
                },
            ],
            project_id=self.project.id,
            start_timestamp=self.now - timedelta(hours=1),
            duration=200,
        )

        with self.feature(FEATURES):
            response = self.client.get(
                self.url,
                format="json",
                data={
                    "transaction": "foo",
                    "project": self.project.id,
                    "breakpoint": self.now - timedelta(days=1),
                    "start": self.now - timedelta(days=3),
                    "end": self.now,
                    "per_page": 1,
                },
            )

        assert response.status_code == 200, response.content

        for row in response.data:
            del row["sample_event_id"]

        assert len(response.data) == 1
        assert response.data == [
            {
                "span_op": "django.middleware",
                "span_group": "2b9cbb96dbf59baa",
                "score_delta": 0.6666666666666666,
                "freq_before": 1.0,
                "freq_after": 1.0,
                "freq_delta": 0.0,
                "duration_delta": 0.6666666666666666,
                "duration_before": 60.0,
                "duration_after": 100.0,
                "span_description": "middleware span",
            }
        ]
