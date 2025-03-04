from datetime import timedelta
from typing import List, Optional

from django.utils import timezone

from sentry.models import CustomDynamicSamplingRule
from sentry.testutils.cases import TestCase
from sentry.testutils.helpers.datetime import freeze_time
from sentry.testutils.silo import region_silo_test


@freeze_time("2023-09-18")
@region_silo_test()
class TestCustomDynamicSamplingRuleProject(TestCase):
    def setUp(self):
        super().setUp()
        self.second_project = self.create_project()
        self.second_organization = self.create_organization(owner=self.user)
        self.third_project = self.create_project(organization=self.second_organization)

    def test_update_or_create(self):
        condition = {"op": "equals", "name": "environment", "value": "prod"}

        end1 = timezone.now() + timedelta(hours=1)

        rule = CustomDynamicSamplingRule.update_or_create(
            condition=condition,
            start=timezone.now(),
            end=end1,
            project_ids=[self.project.id],
            organization_id=self.organization.id,
            num_samples=100,
            sample_rate=0.5,
        )

        end2 = timezone.now() + timedelta(hours=1)
        updated_rule = CustomDynamicSamplingRule.update_or_create(
            condition=condition,
            start=timezone.now() + timedelta(minutes=1),
            end=end2,
            project_ids=[self.second_project.id],
            organization_id=self.organization.id,
            num_samples=100,
            sample_rate=0.5,
        )

        assert rule.id == updated_rule.id
        projects = updated_rule.projects.all()

        assert len(projects) == 2
        assert self.project in projects
        assert self.second_project in projects

        assert updated_rule.end_date >= end1
        assert updated_rule.end_date >= end2

    def test_assign_rule_id(self):
        def create_rule_for_env(env_idx: int):
            condition = {"op": "equals", "name": "environment", "value": f"prod{env_idx}"}
            return CustomDynamicSamplingRule.update_or_create(
                condition=condition,
                start=timezone.now(),
                end=timezone.now() + timedelta(hours=1),
                project_ids=[self.project.id],
                organization_id=self.organization.id,
                num_samples=100,
                sample_rate=0.5,
            )

        rule_ids = set()
        rules = []
        for idx in range(3):
            rule = create_rule_for_env(idx)
            rule_ids.add(rule.rule_id)
            rules.append(rule)

        # all 3 rules have different rule ids
        assert len(rule_ids) == 3

        # make a rule obsolete and check that the rule id is reused
        rules[1].is_active = False
        rules[1].save()

        new_rule = create_rule_for_env(4)
        assert new_rule.rule_id == rules[1].rule_id

        # a new rule will take another slot (now that there is no free slot)
        new_rule_2 = create_rule_for_env(5)
        assert new_rule_2.rule_id not in rule_ids

        # make again an empty slot ( this time by having the rule expire)
        rules[2].start_date = timezone.now() - timedelta(hours=2)
        rules[2].end_date = timezone.now() - timedelta(hours=1)
        rules[2].save()

        # the new rule should take the empty slot
        new_rule_3 = create_rule_for_env(6)
        assert new_rule_3.rule_id == rules[2].rule_id

    def test_deactivate_old_rules(self):
        idx = 1

        old_rules = []
        new_rules = []

        def create_rule(is_old: bool, idx: int):
            condition = {"op": "equals", "name": "environment", "value": f"prod{idx}"}
            if is_old:
                end_delta = -timedelta(hours=1)
            else:
                end_delta = timedelta(hours=1)
            return CustomDynamicSamplingRule.update_or_create(
                condition=condition,
                start=timezone.now() - timedelta(hours=2),
                end=timezone.now() + end_delta,
                project_ids=[self.project.id],
                organization_id=self.organization.id,
                num_samples=100,
                sample_rate=0.5,
            )

        for i in range(10):
            for is_old in [True, False]:
                idx += 1
                rule = create_rule(is_old, idx)
                if is_old:
                    old_rules.append(rule)
                else:
                    new_rules.append(rule)

        CustomDynamicSamplingRule.deactivate_old_rules()

        # check that all old rules are inactive and all new rules are active
        inactive_rules = list(CustomDynamicSamplingRule.objects.filter(is_active=False))
        assert len(inactive_rules) == 10
        for rule in old_rules:
            assert rule in inactive_rules

        active_rules = list(CustomDynamicSamplingRule.objects.filter(is_active=True))
        assert len(active_rules) == 10
        for rule in new_rules:
            assert rule in active_rules

    def test_get_rule_for_org(self):
        """
        Test the get_rule_for_org method
        """
        condition = {"op": "equals", "name": "environment", "value": "prod"}

        # check empty result
        rule = CustomDynamicSamplingRule.get_rule_for_org(condition, self.organization.id)
        assert rule is None

        new_rule = CustomDynamicSamplingRule.update_or_create(
            condition=condition,
            start=timezone.now() - timedelta(hours=2),
            end=timezone.now() + timedelta(hours=1),
            project_ids=[self.project.id],
            organization_id=self.organization.id,
            num_samples=100,
            sample_rate=0.5,
        )

        rule = CustomDynamicSamplingRule.get_rule_for_org(condition, self.organization.id)
        assert rule == new_rule

    def test_get_project_rules(self):
        """
        Tests that all valid rules (i.e. active and within the date range) that apply to a project
        (i.e. that are either organization rules or apply to the project) are returned.
        """

        idx = [1]

        def create_rule(
            project_ids: List[int],
            org_id: Optional[int] = None,
            old: bool = False,
            new: bool = False,
        ) -> CustomDynamicSamplingRule:
            idx[0] += 1
            condition = {"op": "equals", "name": "environment", "value": f"prod{idx[0]}"}
            if old:
                end_delta = -timedelta(hours=2)
            else:
                end_delta = timedelta(hours=2)

            if new:
                start_delta = timedelta(hours=1)
            else:
                start_delta = -timedelta(hours=1)

            if org_id is None:
                org_id = self.organization.id

            return CustomDynamicSamplingRule.update_or_create(
                condition=condition,
                start=timezone.now() + start_delta,
                end=timezone.now() + end_delta,
                project_ids=project_ids,
                organization_id=org_id,
                num_samples=100,
                sample_rate=0.5,
            )

        valid_project_rule = create_rule([self.project.id, self.second_project.id])
        valid_org_rule = create_rule([])
        # rule for another project
        create_rule([self.second_project.id])
        # rule for another org
        create_rule([self.third_project.id], org_id=self.second_organization.id)
        # old project rule ( already expired)
        create_rule([self.project.id], old=True)
        # new project rule ( not yet active)
        create_rule([self.project.id], new=True)
        # old org rule
        create_rule([], old=True)
        # new org rule
        create_rule([], new=True)

        # we should only get valid_project_rule and valid_org_rule
        rules = list(CustomDynamicSamplingRule.get_project_rules(self.project))
        assert len(rules) == 2
        assert valid_project_rule in rules
        assert valid_org_rule in rules
