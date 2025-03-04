from typing import Sequence
from unittest.mock import ANY

import pytest

from sentry.incidents.models import AlertRule
from sentry.models import (
    Dashboard,
    DashboardWidget,
    DashboardWidgetDisplayTypes,
    DashboardWidgetQuery,
    DashboardWidgetTypes,
    Project,
    ProjectTransactionThreshold,
    TransactionMetric,
)
from sentry.relay.config.metric_extraction import get_metric_extraction_config
from sentry.snuba.dataset import Dataset
from sentry.snuba.models import QuerySubscription, SnubaQuery
from sentry.testutils.helpers import Feature
from sentry.testutils.pytest.fixtures import django_db_all

ON_DEMAND_METRICS = "organizations:on-demand-metrics-extraction"
ON_DEMAND_METRICS_WIDGETS = "organizations:on-demand-metrics-extraction-experimental"
ON_DEMAND_METRICS_PREFILL = "organizations:on-demand-metrics-prefill"


def create_alert(
    aggregate: str, query: str, project: Project, dataset: Dataset = Dataset.PerformanceMetrics
) -> AlertRule:
    snuba_query = SnubaQuery.objects.create(
        aggregate=aggregate,
        query=query,
        dataset=dataset.value,
        time_window=300,
        resolution=60,
        environment=None,
        type=SnubaQuery.Type.PERFORMANCE.value,
    )

    QuerySubscription.objects.create(
        snuba_query=snuba_query,
        project=project,
    )

    alert_rule = AlertRule.objects.create(
        snuba_query=snuba_query, threshold_period=1, organization=project.organization
    )

    return alert_rule


def create_widget(
    aggregates: Sequence[str], query: str, project: Project, title="Dashboard"
) -> DashboardWidgetQuery:
    dashboard = Dashboard.objects.create(
        organization=project.organization,
        created_by_id=1,
        title=title,
    )

    widget = DashboardWidget.objects.create(
        dashboard=dashboard,
        order=0,
        widget_type=DashboardWidgetTypes.DISCOVER,
        display_type=DashboardWidgetDisplayTypes.LINE_CHART,
    )

    widget_query = DashboardWidgetQuery.objects.create(
        aggregates=aggregates, conditions=query, order=0, widget=widget
    )

    return widget_query


def create_project_threshold(
    project: Project, threshold: int, metric: int
) -> ProjectTransactionThreshold:
    return ProjectTransactionThreshold.objects.create(
        project=project, organization=project.organization, threshold=threshold, metric=metric
    )


@django_db_all
def test_get_metric_extraction_config_empty_no_alerts(default_project):
    with Feature(ON_DEMAND_METRICS):
        assert not get_metric_extraction_config(default_project)


@django_db_all
def test_get_metric_extraction_config_empty_feature_flag_off(default_project):
    create_alert("count()", "transaction.duration:>=1000", default_project)

    assert not get_metric_extraction_config(default_project)


@django_db_all
def test_get_metric_extraction_config_empty_standard_alerts(default_project):
    with Feature(ON_DEMAND_METRICS):
        # standard alerts are not included in the config
        create_alert("count()", "", default_project)

        assert not get_metric_extraction_config(default_project)


@django_db_all
def test_get_metric_extraction_config_single_alert(default_project):
    with Feature(ON_DEMAND_METRICS):
        create_alert("count()", "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_multiple_alerts(default_project):
    with Feature(ON_DEMAND_METRICS):
        create_alert("count()", "transaction.duration:>=1000", default_project)
        create_alert("count()", "transaction.duration:>=2000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 2

        first_hash = config["metrics"][0]["tags"][0]["value"]
        second_hash = config["metrics"][1]["tags"][0]["value"]

        assert first_hash != second_hash


@django_db_all
def test_get_metric_extraction_config_multiple_alerts_duplicated(default_project):
    # alerts with the same query should be deduplicated
    with Feature(ON_DEMAND_METRICS):
        create_alert("count()", "transaction.duration:>=1000", default_project)
        create_alert("count()", "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1


@django_db_all
def test_get_metric_extraction_config_single_standard_widget(default_project):
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(["count()"], "", default_project)

        assert not get_metric_extraction_config(default_project)


@django_db_all
def test_get_metric_extraction_config_single_widget(default_project):
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(["count()"], "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_single_widget_multiple_aggregates(default_project):
    # widget with multiple fields should result in multiple metrics
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(
            ["count()", "avg(transaction.duration)"], "transaction.duration:>=1000", default_project
        )

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 2
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][1] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": "event.duration",
            "mri": "d:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_single_widget_multiple_count_if(default_project):
    # widget with multiple fields should result in multiple metrics
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        aggregates = [
            "count()",
            "count_if(transaction.duration, greater, 2000)",
            "count_if(transaction.duration, greaterOrEquals, 1000)",
        ]
        create_widget(aggregates, "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 3
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][1] == {
            "category": "transaction",
            "condition": {
                "inner": [
                    {"name": "event.duration", "op": "gte", "value": 1000.0},
                    {"name": "event.duration", "op": "gt", "value": 2000.0},
                ],
                "op": "and",
            },
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][2] == {
            "category": "transaction",
            "condition": {
                "inner": [
                    {"name": "event.duration", "op": "gte", "value": 1000.0},
                    {"name": "event.duration", "op": "gte", "value": 1000.0},
                ],
                "op": "and",
            },
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_multiple_aggregates_single_field(default_project):
    # widget with multiple aggregates on the same field in a single metric
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(
            ["sum(transaction.duration)", "avg(transaction.duration)"],
            "transaction.duration:>=1000",
            default_project,
        )

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": "event.duration",
            "mri": "d:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_multiple_widgets_duplicated(default_project):
    # metrics should be deduplicated across widgets
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(
            ["count()", "avg(transaction.duration)"], "transaction.duration:>=1000", default_project
        )
        create_widget(["count()"], "transaction.duration:>=1000", default_project, "Dashboard 2")

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 2
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][1] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": "event.duration",
            "mri": "d:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_alerts_and_widgets_off(default_project):
    # widgets should be skipped if the feature is off
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: False}):
        create_alert("count()", "transaction.duration:>=1000", default_project)
        create_widget(["count()"], "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_alerts_and_widgets(default_project):
    # deduplication should work across alerts and widgets
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_alert("count()", "transaction.duration:>=1000", default_project)
        create_widget(
            ["count()", "avg(transaction.duration)"], "transaction.duration:>=1000", default_project
        )

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 2
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][1] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": "event.duration",
            "mri": "d:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
def test_get_metric_extraction_config_with_failure_count(default_project):
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget(["failure_count()"], "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [
                {
                    "condition": {
                        "inner": {
                            "name": "event.contexts.trace.status",
                            "op": "eq",
                            "value": ["ok", "cancelled", "unknown"],
                        },
                        "op": "not",
                    },
                    "key": "failure",
                    "value": "true",
                },
                {"key": "query_hash", "value": ANY},
            ],
        }


@django_db_all
def test_get_metric_extraction_config_with_apdex(default_project):
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_alert("apdex(10)", "transaction.duration:>=1000", default_project)
        # The threshold stored in the database will not be considered and rather the one from the parameter will be
        # preferred.
        create_project_threshold(default_project, 200, TransactionMetric.DURATION.value)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [
                {
                    "condition": {"name": "event.duration", "op": "lte", "value": 10},
                    "key": "satisfaction",
                    "value": "satisfactory",
                },
                {
                    "condition": {
                        "inner": [
                            {"name": "event.duration", "op": "gt", "value": 10},
                            {"name": "event.duration", "op": "lte", "value": 40},
                        ],
                        "op": "and",
                    },
                    "key": "satisfaction",
                    "value": "tolerable",
                },
                {
                    "condition": {"name": "event.duration", "op": "gt", "value": 40},
                    "key": "satisfaction",
                    "value": "frustrated",
                },
                {"key": "query_hash", "value": ANY},
            ],
        }


@django_db_all
@pytest.mark.parametrize("metric", [("epm()"), ("eps()")])
def test_get_metric_extraction_config_with_no_tag_spec(default_project, metric):
    with Feature({ON_DEMAND_METRICS: True, ON_DEMAND_METRICS_WIDGETS: True}):
        create_widget([metric], "transaction.duration:>=1000", default_project)

        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 1000.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }


@django_db_all
@pytest.mark.parametrize(
    "enabled_features, number_of_metrics",
    [
        ([ON_DEMAND_METRICS], 1),  # Alerts.
        ([ON_DEMAND_METRICS_PREFILL], 1),  # Alerts.
        ([ON_DEMAND_METRICS, ON_DEMAND_METRICS_PREFILL], 1),  # Alerts.
        ([ON_DEMAND_METRICS, ON_DEMAND_METRICS_WIDGETS], 2),  # Alerts and widgets.
        ([ON_DEMAND_METRICS_WIDGETS], 0),  # Nothing.
        ([ON_DEMAND_METRICS_PREFILL, ON_DEMAND_METRICS_WIDGETS], 1),  # Alerts.
        ([], 0),  # Nothing.
    ],
)
def test_get_metrics_extraction_config_features_combinations(
    enabled_features, number_of_metrics, default_project
):
    create_alert("count()", "transaction.duration:>=10", default_project)
    create_widget(["count()"], "transaction.duration:>=20", default_project)

    features = {feature: True for feature in enabled_features}
    with Feature(features):
        config = get_metric_extraction_config(default_project)
        if number_of_metrics == 0:
            assert config is None
        else:
            assert config is not None
            assert len(config["metrics"]) == number_of_metrics


@django_db_all
def test_get_metric_extraction_config_with_transactions_dataset(default_project):
    create_alert(
        "count()", "transaction.duration:>=10", default_project, dataset=Dataset.PerformanceMetrics
    )
    create_alert(
        "count()", "transaction.duration:>=20", default_project, dataset=Dataset.Transactions
    )

    # We test with prefilling, and we expect that both alerts are fetched since we support both datasets.
    with Feature({ON_DEMAND_METRICS_PREFILL: True}):
        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 2
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 10.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
        assert config["metrics"][1] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 20.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }

    # We test without prefilling, and we expect that only alerts for performance metrics are fetched.
    with Feature({ON_DEMAND_METRICS: True}):
        config = get_metric_extraction_config(default_project)

        assert config
        assert len(config["metrics"]) == 1
        assert config["metrics"][0] == {
            "category": "transaction",
            "condition": {"name": "event.duration", "op": "gte", "value": 10.0},
            "field": None,
            "mri": "c:transactions/on_demand@none",
            "tags": [{"key": "query_hash", "value": ANY}],
        }
