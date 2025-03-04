from sentry.models.notificationsettingoption import NotificationSettingOption
from sentry.models.notificationsettingprovider import NotificationSettingProvider
from sentry.notifications.notificationcontroller import NotificationController
from sentry.notifications.types import (
    NotificationScopeEnum,
    NotificationSettingEnum,
    NotificationSettingsOptionEnum,
)
from sentry.services.hybrid_cloud.actor import ActorType, RpcActor
from sentry.testutils.cases import TestCase
from sentry.types.integrations import ExternalProviderEnum, ExternalProviders


def add_notification_setting_option(
    scope_type,
    scope_identifier,
    type,
    value,
    user_id=None,
    team_id=None,
):
    return NotificationSettingOption.objects.create(
        scope_type=scope_type.value,
        scope_identifier=scope_identifier,
        type=type.value,
        value=value.value,
        user_id=user_id,
        team_id=team_id,
    )


def add_notification_setting_provider(
    scope_type,
    scope_identifier,
    provider,
    type,
    value,
    user_id=None,
    team_id=None,
):
    return NotificationSettingProvider.objects.create(
        scope_type=scope_type.value,
        scope_identifier=scope_identifier,
        provider=provider.value,
        type=type.value,
        value=value.value,
        user_id=user_id,
        team_id=team_id,
    )


# The tests below are intended to check behavior with the new
# NotificationSettingOption and NotificationSettingProvider tables,
# which will be enabled with the "organization:notification-settings-v2" flag.
class NotificationControllerTest(TestCase):
    def setUp(self):
        super().setUp()
        setting_option_1 = add_notification_setting_option(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            type=NotificationSettingEnum.DEPLOY,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )
        setting_option_2 = add_notification_setting_option(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )
        setting_option_3 = add_notification_setting_option(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        self.setting_options = [setting_option_1, setting_option_2, setting_option_3]

        setting_provider_1 = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            provider=ExternalProviderEnum.SLACK,
            type=NotificationSettingEnum.DEPLOY,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )
        setting_provider_2 = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            provider=ExternalProviderEnum.MSTEAMS,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )
        setting_provider_3 = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            provider=ExternalProviderEnum.EMAIL,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )

        self.setting_providers = [setting_provider_1, setting_provider_2, setting_provider_3]

    def test_get_all_setting_options(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        assert list(controller.get_all_setting_options) == self.setting_options

        NotificationSettingOption.objects.all().delete()
        assert list(controller.get_all_setting_options) == self.setting_options
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        assert list(controller.get_all_setting_options) == []

    def test_get_all_setting_providers(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        assert list(controller.get_all_setting_providers) == self.setting_providers

    def test_without_settings(self):
        rpc_user = RpcActor.from_object(self.user)
        NotificationSettingOption.objects.all().delete()
        NotificationSettingProvider.objects.all().delete()
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        assert controller.get_all_setting_options == []
        assert controller.get_all_setting_providers == []
        scope = (NotificationScopeEnum.PROJECT, self.project.id)
        options = controller._get_layered_setting_options()
        assert (
            options[self.user][scope][NotificationSettingEnum.ISSUE_ALERTS]
            == NotificationSettingsOptionEnum.ALWAYS
        )
        providers = controller._get_layered_setting_providers()
        assert (
            providers[self.user][scope][NotificationSettingEnum.ISSUE_ALERTS][
                ExternalProviderEnum.MSTEAMS
            ]
            == NotificationSettingsOptionEnum.NEVER
        )
        assert (
            providers[self.user][scope][NotificationSettingEnum.DEPLOY][ExternalProviderEnum.SLACK]
            == NotificationSettingsOptionEnum.ALWAYS
        )

        enabled_settings = controller.get_all_enabled_settings()[self.user]
        assert (
            enabled_settings[scope][NotificationSettingEnum.ISSUE_ALERTS][
                ExternalProviderEnum.SLACK
            ]
            == NotificationSettingsOptionEnum.ALWAYS
        )
        assert controller.get_notification_recipients(
            type=NotificationSettingEnum.ISSUE_ALERTS
        ) == {ExternalProviders.EMAIL: {rpc_user}, ExternalProviders.SLACK: {rpc_user}}
        assert not controller.user_has_any_provider_settings(provider=ExternalProviderEnum.SLACK)
        assert not controller.user_has_any_provider_settings(provider=ExternalProviderEnum.MSTEAMS)

    def test_filter_setting_options(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        filtered_options = controller._filter_options(
            settings=self.setting_options, type=NotificationSettingEnum.DEPLOY.value
        )
        assert filtered_options == [self.setting_options[0]]

        filtered_options = controller._filter_options(
            settings=self.setting_options, type=NotificationSettingEnum.ISSUE_ALERTS.value
        )
        assert filtered_options == self.setting_options[1:]

        filtered_options = controller._filter_options(
            settings=self.setting_options,
            type=NotificationSettingEnum.ISSUE_ALERTS.value,
            scope_type=NotificationScopeEnum.PROJECT.value,
        )
        assert filtered_options == [self.setting_options[1]]

    def test_filter_setting_providers(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        filtered_providers = controller._filter_providers(
            settings=self.setting_providers, type=NotificationSettingEnum.DEPLOY.value
        )
        assert filtered_providers == [self.setting_providers[0]]

        filtered_providers = controller._filter_providers(
            settings=self.setting_providers, value=NotificationSettingsOptionEnum.ALWAYS.value
        )
        assert filtered_providers == [self.setting_providers[0], self.setting_providers[2]]

        filtered_providers = controller._filter_providers(
            settings=self.setting_providers,
            type=NotificationSettingEnum.DEPLOY.value,
            value=NotificationSettingsOptionEnum.ALWAYS.value,
        )
        assert filtered_providers == [self.setting_providers[0]]

    def test_layering(self):
        NotificationSettingOption.objects.all().delete()
        top_level_option = add_notification_setting_option(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )
        add_notification_setting_option(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )
        add_notification_setting_option(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.SUBSCRIBE_ONLY,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        options = controller._get_layered_setting_options()
        scope = (NotificationScopeEnum.PROJECT, top_level_option.scope_identifier)
        assert (
            options[self.user][scope][NotificationSettingEnum.WORKFLOW].value
            == top_level_option.value
        )

        NotificationSettingProvider.objects.all().delete()
        top_level_provider = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            provider=ExternalProviderEnum.EMAIL,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.SUBSCRIBE_ONLY,
            user_id=self.user.id,
        )
        add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            provider=ExternalProviderEnum.EMAIL,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=self.user.id,
        )
        add_notification_setting_provider(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            provider=ExternalProviderEnum.EMAIL,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.SUBSCRIBE_ONLY,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        providers = controller._get_layered_setting_providers()
        scope = (NotificationScopeEnum.PROJECT, top_level_provider.scope_identifier)
        assert (
            providers[self.user][scope][NotificationSettingEnum.WORKFLOW][
                ExternalProviderEnum.EMAIL
            ].value
            == top_level_provider.value
        )
        assert (
            providers[self.user][scope][NotificationSettingEnum.DEPLOY][ExternalProviderEnum.EMAIL]
            == NotificationSettingsOptionEnum.ALWAYS
        )
        assert (
            providers[self.user][scope][NotificationSettingEnum.DEPLOY][
                ExternalProviderEnum.MSTEAMS
            ]
            == NotificationSettingsOptionEnum.NEVER
        )

    def test_get_layered_setting_options(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        options = controller._get_layered_setting_options()

        scope = (NotificationScopeEnum.PROJECT, self.project.id)
        assert (
            options[self.user][scope][NotificationSettingEnum.DEPLOY].value
            == self.setting_options[0].value
        )
        assert (
            options[self.user][scope][NotificationSettingEnum.ISSUE_ALERTS].value
            == self.setting_options[1].value
        )

        options = controller._get_layered_setting_options(
            type=NotificationSettingEnum.ISSUE_ALERTS.value
        )

        assert (
            options[self.user][scope][NotificationSettingEnum.ISSUE_ALERTS].value
            == self.setting_options[1].value
        )

    def test_get_layered_setting_options_defaults(self):
        new_user = self.create_user()
        setting_option_1 = add_notification_setting_option(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=new_user.id,
        )

        controller = NotificationController(
            recipients=[new_user, self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        options = controller._get_layered_setting_options()
        scope = (NotificationScopeEnum.PROJECT, self.project.id)
        assert (
            options[new_user][scope][NotificationSettingEnum.ISSUE_ALERTS].value
            == setting_option_1.value
        )

        user_options = options[self.user][scope]
        assert (
            user_options[NotificationSettingEnum.ISSUE_ALERTS].value
            == self.setting_options[1].value
        )
        assert user_options[NotificationSettingEnum.DEPLOY].value == self.setting_options[0].value
        assert (
            user_options[NotificationSettingEnum.WORKFLOW]
            == NotificationSettingsOptionEnum.SUBSCRIBE_ONLY
        )

    def test_get_layered_setting_providers_defaults(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        options = controller._get_layered_setting_providers()
        scope = (NotificationScopeEnum.PROJECT, self.project.id)
        user_options = options[self.user][scope]
        assert (
            user_options[NotificationSettingEnum.ISSUE_ALERTS][ExternalProviderEnum.MSTEAMS].value
            == self.setting_providers[1].value
        )
        assert (
            user_options[NotificationSettingEnum.DEPLOY][ExternalProviderEnum.SLACK].value
            == self.setting_providers[0].value
        )
        assert (
            user_options[NotificationSettingEnum.WORKFLOW][ExternalProviderEnum.EMAIL].value
            == self.setting_providers[2].value
        )

    def test_get_setting_providers_with_defaults(self):
        new_user = self.create_user()
        setting_provider_1 = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            provider=ExternalProviderEnum.MSTEAMS,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=new_user.id,
        )
        controller = NotificationController(
            recipients=[self.user, new_user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        scope = (NotificationScopeEnum.PROJECT, self.project.id)
        options = controller._get_layered_setting_providers()
        assert (
            options[new_user][scope][NotificationSettingEnum.ISSUE_ALERTS][
                ExternalProviderEnum.MSTEAMS
            ].value
            == setting_provider_1.value
        )

        user_options = options[self.user][scope]
        assert (
            user_options[NotificationSettingEnum.ISSUE_ALERTS][ExternalProviderEnum.MSTEAMS].value
            == self.setting_providers[1].value
        )
        assert (
            user_options[NotificationSettingEnum.DEPLOY][ExternalProviderEnum.SLACK].value
            == self.setting_providers[0].value
        )
        assert (
            user_options[NotificationSettingEnum.WORKFLOW][ExternalProviderEnum.EMAIL].value
            == self.setting_providers[2].value
        )

    def test_get_all_enabled_settings(self):
        new_user = self.create_user()
        self.create_member(
            organization=self.organization, user=new_user, role="member", teams=[self.team]
        )

        _ = add_notification_setting_option(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=new_user.id,
        )
        _ = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=new_user.id,
            provider=ExternalProviderEnum.MSTEAMS,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=new_user.id,
        )
        controller = NotificationController(
            recipients=[self.user, new_user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        enabled_settings = controller.get_all_enabled_settings()
        scope = (NotificationScopeEnum.PROJECT, self.project.id)

        for type in [
            NotificationSettingEnum.DEPLOY,
            NotificationSettingEnum.WORKFLOW,
            NotificationSettingEnum.ISSUE_ALERTS,
        ]:
            values = enabled_settings[self.user][scope][type].values()
            assert all(value == NotificationSettingsOptionEnum.ALWAYS for value in values)

            values = enabled_settings[new_user][scope][type].values()
            assert all(value == NotificationSettingsOptionEnum.ALWAYS for value in values)

        default = {
            ExternalProviderEnum.SLACK: NotificationSettingsOptionEnum.ALWAYS,
            ExternalProviderEnum.EMAIL: NotificationSettingsOptionEnum.ALWAYS,
        }
        for type in [NotificationSettingEnum.REPORTS, NotificationSettingEnum.QUOTA]:
            assert enabled_settings[self.user][scope][type] == default
            assert enabled_settings[new_user][scope][type] == default

    def test_get_notification_recipients(self):
        rpc_user = RpcActor.from_object(self.user)
        new_user = self.create_user()
        rpc_new_user = RpcActor.from_object(new_user)
        self.create_member(
            organization=self.organization, user=new_user, role="member", teams=[self.team]
        )

        _ = add_notification_setting_option(
            scope_type=NotificationScopeEnum.PROJECT,
            scope_identifier=self.project.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=new_user.id,
        )
        _ = add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=new_user.id,
            provider=ExternalProviderEnum.MSTEAMS,
            type=NotificationSettingEnum.ISSUE_ALERTS,
            value=NotificationSettingsOptionEnum.ALWAYS,
            user_id=new_user.id,
        )
        controller = NotificationController(
            recipients=[self.user, new_user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )
        recipients = controller.get_notification_recipients(
            type=NotificationSettingEnum.ISSUE_ALERTS,
            actor_type=ActorType.USER,
        )
        assert recipients[ExternalProviders.SLACK] == {rpc_user, rpc_new_user}
        assert recipients[ExternalProviders.EMAIL] == {rpc_user, rpc_new_user}
        assert recipients[ExternalProviders.MSTEAMS] == {rpc_new_user}

    def test_user_has_any_provider_settings(self):
        controller = NotificationController(
            recipients=[self.user],
            organization_id=self.organization.id,
        )
        assert controller.user_has_any_provider_settings(provider=ExternalProviderEnum.SLACK)
        assert controller.user_has_any_provider_settings(provider=ExternalProviderEnum.EMAIL)
        assert not controller.user_has_any_provider_settings(provider=ExternalProviderEnum.MSTEAMS)

    def test_get_subscriptions_status_for_projects(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert controller.get_subscriptions_status_for_projects(
            project_ids=[self.project.id],
            user=self.user,
            type=NotificationSettingEnum.DEPLOY,
        ) == {self.project.id: (False, True)}

        assert controller.get_subscriptions_status_for_projects(
            project_ids=[self.project.id],
            user=self.user,
            type=NotificationSettingEnum.ISSUE_ALERTS,
        ) == {self.project.id: (False, False)}

        assert controller.get_subscriptions_status_for_projects(
            project_ids=[self.project.id],
            user=self.user,
            type=NotificationSettingEnum.QUOTA,
        ) == {self.project.id: (False, True)}

    def test_get_participants(self):
        rpc_user = RpcActor.from_object(self.user)
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
            type=NotificationSettingEnum.ISSUE_ALERTS,
        )

        assert controller.get_participants() == {
            rpc_user: {
                ExternalProviders.EMAIL: NotificationSettingsOptionEnum.ALWAYS,
                ExternalProviders.SLACK: NotificationSettingsOptionEnum.ALWAYS,
            }
        }

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
            type=NotificationSettingEnum.WORKFLOW,
        )

        assert controller.get_participants() == {
            rpc_user: {
                ExternalProviders.EMAIL: NotificationSettingsOptionEnum.ALWAYS,
                ExternalProviders.SLACK: NotificationSettingsOptionEnum.ALWAYS,
            }
        }

    def test_get_notification_value_for_recipient_and_type(self):
        add_notification_setting_option(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.SUBSCRIBE_ONLY,
            user_id=self.user.id,
        )

        add_notification_setting_option(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.QUOTA_ERRORS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.DEPLOY,
            )
            == NotificationSettingsOptionEnum.ALWAYS
        )

        assert (
            controller.get_notification_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.WORKFLOW,
            )
            == NotificationSettingsOptionEnum.SUBSCRIBE_ONLY
        )

        assert (
            controller.get_notification_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.QUOTA_ERRORS,
            )
            == NotificationSettingsOptionEnum.NEVER
        )

    def test_get_notification_provider_value_for_recipient_and_type(self):
        add_notification_setting_provider(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.SUBSCRIBE_ONLY,
            provider=ExternalProviderEnum.OPSGENIE,
            user_id=self.user.id,
        )

        add_notification_setting_provider(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.QUOTA_WARNINGS,
            provider=ExternalProviderEnum.PAGERDUTY,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_provider_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.DEPLOY,
                provider=ExternalProviderEnum.SLACK,
            )
            == NotificationSettingsOptionEnum.ALWAYS
        )

        assert (
            controller.get_notification_provider_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.QUOTA_WARNINGS,
                provider=ExternalProviderEnum.PAGERDUTY,
            )
            == NotificationSettingsOptionEnum.NEVER
        )

        assert (
            controller.get_notification_provider_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.QUOTA_ERRORS,
                provider=ExternalProviderEnum.OPSGENIE,
            )
            == NotificationSettingsOptionEnum.NEVER
        )

    def test_get_notification_value_for_recipient_and_type_with_layering(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.DEPLOY,
            )
            == NotificationSettingsOptionEnum.ALWAYS
        )

        # overrides the user setting in setUp()
        add_notification_setting_option(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            type=NotificationSettingEnum.DEPLOY,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.DEPLOY,
            )
            == NotificationSettingsOptionEnum.NEVER
        )

    def test_get_notification_provider_value_for_recipient_and_type_with_layering(self):
        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_provider_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.WORKFLOW,
                provider=ExternalProviderEnum.EMAIL,
            )
            == NotificationSettingsOptionEnum.ALWAYS
        )

        # overrides the user setting in setUp()
        add_notification_setting_provider(
            scope_type=NotificationScopeEnum.ORGANIZATION,
            scope_identifier=self.organization.id,
            provider=ExternalProviderEnum.EMAIL,
            type=NotificationSettingEnum.WORKFLOW,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            project_ids=[self.project.id],
            organization_id=self.organization.id,
        )

        assert (
            controller.get_notification_provider_value_for_recipient_and_type(
                recipient=self.user,
                type=NotificationSettingEnum.WORKFLOW,
                provider=ExternalProviderEnum.EMAIL,
            )
            == NotificationSettingsOptionEnum.NEVER
        )

    def test_get_users_for_weekly_reports(self):
        controller = NotificationController(
            recipients=[self.user],
            organization_id=self.organization.id,
            type=NotificationSettingEnum.REPORTS,
        )
        assert controller.get_users_for_weekly_reports() == [self.user.id]

        add_notification_setting_option(
            scope_type=NotificationScopeEnum.USER,
            scope_identifier=self.user.id,
            type=NotificationSettingEnum.REPORTS,
            value=NotificationSettingsOptionEnum.NEVER,
            user_id=self.user.id,
        )

        controller = NotificationController(
            recipients=[self.user],
            organization_id=self.organization.id,
            type=NotificationSettingEnum.REPORTS,
        )
        assert controller.get_users_for_weekly_reports() == []
