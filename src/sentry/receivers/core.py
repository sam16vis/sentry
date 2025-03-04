import logging
from functools import wraps

from click import echo
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import connections, router, transaction
from django.db.models.signals import post_save
from django.db.utils import OperationalError, ProgrammingError
from packaging.version import parse as parse_version

from sentry import options
from sentry.loader.dynamic_sdk_options import get_default_loader_data
from sentry.models import Organization, OrganizationMember, Project, ProjectKey, Team
from sentry.services.hybrid_cloud.user.service import user_service
from sentry.services.hybrid_cloud.util import region_silo_function
from sentry.signals import post_upgrade, project_created
from sentry.silo import SiloMode
from sentry.utils.env import in_test_environment
from sentry.utils.settings import is_self_hosted

PROJECT_SEQUENCE_FIX = """
SELECT setval('sentry_project_id_seq', (
    SELECT GREATEST(MAX(id) + 1, nextval('sentry_project_id_seq')) - 1
    FROM sentry_project))
"""
DEFAULT_SENTRY_PROJECT_ID = 1


def handle_db_failure(func, using=None):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic(using or router.db_for_write(Organization)):
                return func(*args, **kwargs)
        except (ProgrammingError, OperationalError):
            logging.exception("Failed processing signal %s", func.__name__)
            return

    return wrapped


def create_default_projects(**kwds):
    if not in_test_environment() and not is_self_hosted():
        # No op in production SaaS environments.
        return

    create_default_project(
        # This guards against sentry installs that have SENTRY_PROJECT set to None, so
        # that they don't error after every migration. Specifically for single tenant.
        id=settings.SENTRY_PROJECT or DEFAULT_SENTRY_PROJECT_ID,
        name="Internal",
        slug="internal",
    )

    if settings.SENTRY_FRONTEND_PROJECT:
        create_default_project(
            id=settings.SENTRY_FRONTEND_PROJECT,
            name="Frontend",
            slug="frontend",
        )


@region_silo_function
def create_default_project(id, name, slug, verbosity=2, **kwargs):
    if Project.objects.filter(id=id).exists():
        return

    user = user_service.get_first_superuser()

    org, _ = Organization.objects.get_or_create(slug="sentry", defaults={"name": "Sentry"})

    if user:
        OrganizationMember.objects.get_or_create(user_id=user.id, organization=org, role="owner")

    team, _ = Team.objects.get_or_create(
        organization=org, slug="sentry", defaults={"name": "Sentry"}
    )

    with transaction.atomic(router.db_for_write(Project)):
        project = Project.objects.create(
            id=id, public=False, name=name, slug=slug, organization=team.organization, **kwargs
        )
        project.add_team(team)

        project_created.send(
            project=project,
            user=user or AnonymousUser(),
            default_rules=True,
            sender=create_default_project,
        )

        # HACK: Manually update the ID after insert due to Postgres sequence issues.
        connection = connections[project._state.db]
        cursor = connection.cursor()
        cursor.execute(PROJECT_SEQUENCE_FIX)

    project.update_option("sentry:origins", ["*"])

    if verbosity > 0:
        echo(f"Created internal Sentry project (slug={project.slug}, id={project.id})")

    return project


def set_sentry_version(latest=None, **kwargs):
    import sentry

    current = sentry.VERSION

    version = options.get("sentry:latest_version")

    for ver in (current, version):
        if parse_version(ver) >= parse_version(latest):
            latest = ver

    if latest == version:
        return

    options.set(
        "sentry:latest_version", (latest or current), channel=options.UpdateChannel.APPLICATION
    )


def create_keys_for_project(instance, created, app=None, **kwargs):
    if app and app.__name__ != "sentry.models":
        return

    if not created or kwargs.get("raw"):
        return

    if ProjectKey.objects.filter(project=instance).exists():
        return

    ProjectKey.objects.create(
        project=instance, label="Default", data=get_default_loader_data(instance)
    )


def freeze_option_epoch_for_project(instance, created, app=None, **kwargs):
    if app and app.__name__ != "sentry.models":
        return

    if not created or kwargs.get("raw"):
        return

    from sentry import projectoptions

    projectoptions.default_manager.freeze_option_epoch(project=instance, force=False)


# Anything that relies on default objects that may not exist with default
# fields should be wrapped in handle_db_failure
post_upgrade.connect(
    handle_db_failure(create_default_projects),
    dispatch_uid="create_default_project",
    weak=False,
    sender=SiloMode.MONOLITH,
)

post_save.connect(
    handle_db_failure(freeze_option_epoch_for_project),
    sender=Project,
    dispatch_uid="freeze_option_epoch_for_project",
    weak=False,
)
post_save.connect(
    handle_db_failure(create_keys_for_project),
    sender=Project,
    dispatch_uid="create_keys_for_project",
    weak=False,
)
