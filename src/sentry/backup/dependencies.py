from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto, unique
from functools import lru_cache
from typing import Dict, FrozenSet, NamedTuple, Optional, Set, Tuple, Type

from django.db import models
from django.db.models.fields.related import ForeignKey, OneToOneField

from sentry.backup.helpers import EXCLUDED_APPS
from sentry.backup.scopes import RelocationScope
from sentry.silo import SiloMode
from sentry.utils import json


class NormalizedModelName:
    """
    A wrapper type that ensures that the contained model name has been properly normalized. A "normalized" model name is one that is identical to the name as it appears in an exported JSON backup, so a string of the form `{app_label.lower()}.{model_name.lower()}`.
    """

    __model_name: str

    def __init__(self, model_name: str):
        if "." not in model_name:
            raise TypeError("cannot create NormalizedModelName from invalid input string")
        self.__model_name = model_name.lower()

    def __hash__(self):
        return hash(self.__model_name)

    def __eq__(self, other) -> bool:
        if other is None:
            return False
        if not isinstance(other, self.__class__):
            raise TypeError(
                "NormalizedModelName can only be compared with other NormalizedModelName"
            )
        return self.__model_name == other.__model_name

    def __lt__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            raise TypeError(
                "NormalizedModelName can only be compared with other NormalizedModelName"
            )
        return self.__model_name < other.__model_name

    def __str__(self) -> str:
        return self.__model_name


# A "root" model is one that is the source of a particular relocation scope - ex, `User` is the root
# of the `User` relocation scope, the model from which all other (non-dangling; see below) models in
# that scope are referenced.
#
# TODO(getsentry/team-ospo#190): We should find a better way to store this information than a magic
# list in this file. We should probably make a field (or method?) on `BaseModel` instead.
@unique
class RelocationRootModels(Enum):
    """
    Record the "root" models for a given `RelocationScope`.
    """

    Excluded: list[NormalizedModelName] = []
    User = [NormalizedModelName("sentry.user")]
    Organization = [NormalizedModelName("sentry.organization")]
    Config = [
        NormalizedModelName("sentry.controloption"),
        NormalizedModelName("sentry.option"),
        NormalizedModelName("sentry.relay"),
        NormalizedModelName("sentry.relayusage"),
        NormalizedModelName("sentry.userrole"),
    ]
    # TODO(getsentry/team-ospo#188): Split out extension scope root models from this list.
    Global = [
        NormalizedModelName("sentry.apiapplication"),
        NormalizedModelName("sentry.integration"),
        NormalizedModelName("sentry.sentryapp"),
    ]


@unique
class ForeignFieldKind(Enum):
    """Kinds of foreign fields that we care about."""

    # Uses our `FlexibleForeignKey` wrapper.
    FlexibleForeignKey = auto()

    # Uses our `HybridCloudForeignKey` wrapper.
    HybridCloudForeignKey = auto()

    # Uses our `OneToOneCascadeDeletes` wrapper.
    OneToOneCascadeDeletes = auto()

    # A naked usage of Django's `ForeignKey`.
    DefaultForeignKey = auto()

    # A naked usage of Django's `OneToOneField`.
    DefaultOneToOneField = auto()

    # A ForeignKey-like dependency that is opaque to Django because it uses `BoundedBigIntegerField`
    # instead of one of the Django's default relational field types like `ForeignKey`,
    # `OneToOneField`, etc.dd
    ImplicitForeignKey = auto()


class ForeignField(NamedTuple):
    """A field that creates a dependency on another Sentry model."""

    model: Type[models.base.Model]
    kind: ForeignFieldKind
    nullable: bool


@dataclass
class ModelRelations:
    """What other models does this model depend on, and how?"""

    # A "dangling" model is one that does not transitively contain a non-nullable `ForeignField`
    # reference to at least one of the `RelocationRootModels` listed above.
    #
    # TODO(getsentry/team-ospo#190): A model may or may not be "dangling" in different
    # `ExportScope`s - for example, a model in `RelocationScope.Organization` may have a single,
    # non-nullable `ForeignField` reference to a root model in `RelocationScope.Config`. This would
    # cause it to be dangling when we do an `ExportScope.Organization` export, but non-dangling if
    # we do an `ExportScope.Global` export. HOWEVER, as best as I can tell, this situation does not
    # actually exist today, so we can ignore this subtlety for now and just us a boolean here.
    dangling: Optional[bool]
    foreign_keys: dict[str, ForeignField]
    model: Type[models.base.Model]
    relocation_scope: RelocationScope | set[RelocationScope]
    silos: list[SiloMode]
    table_name: str
    uniques: list[frozenset[str]]

    def flatten(self) -> set[Type[models.base.Model]]:
        """Returns a flat list of all related models, omitting the kind of relation they have."""

        return {ff.model for ff in self.foreign_keys.values()}

    def get_possible_relocation_scopes(self) -> set[RelocationScope]:
        from sentry.db.models import BaseModel

        if issubclass(self.model, BaseModel):
            return self.model.get_possible_relocation_scopes()
        return set()


def get_model_name(model: type[models.Model] | models.Model) -> NormalizedModelName:
    return NormalizedModelName(f"{model._meta.app_label}.{model._meta.object_name}")


def get_model(model_name: NormalizedModelName) -> Optional[Type[models.base.Model]]:
    """
    Given a standardized model name string, retrieve the matching Sentry model.
    """
    for model in sorted_dependencies():
        if get_model_name(model) == model_name:
            return model
    return None


class DependenciesJSONEncoder(json.JSONEncoder):
    """JSON serializer that outputs a detailed serialization of all models included in a
    `ModelRelations`."""

    def default(self, obj):
        if meta := getattr(obj, "_meta", None):
            return f"{meta.app_label}.{meta.object_name}".lower()
        if isinstance(obj, ModelRelations):
            return obj.__dict__
        if isinstance(obj, ForeignFieldKind):
            return obj.name
        if isinstance(obj, RelocationScope):
            return obj.name
        if isinstance(obj, set) and all(isinstance(rs, RelocationScope) for rs in obj):
            # Order by enum value, which should correspond to `RelocationScope` breadth.
            return sorted(list(obj), key=lambda obj: obj.value)
        if isinstance(obj, SiloMode):
            return obj.name.lower().capitalize()
        if isinstance(obj, set):
            return sorted(list(obj), key=lambda obj: get_model_name(obj))
        # JSON serialization of `uniques` values, which are stored in `frozenset`s.
        if isinstance(obj, frozenset):
            return sorted(list(obj))
        return super().default(obj)


class ImportKind(Enum):
    """
    When importing a given model, we may create a new copy of it (`Inserted`), merely re-use an
    `Existing` copy that has the same already-used globally unique identifier (ex: `username` for
    users, `slug` for orgs, etc), or do an `Overwrite` that merges the new data into an existing
    model that already has a `pk` assigned to it. This information can then be saved alongside the
    new `pk` for the model in the `PrimaryKeyMap`, so that models that depend on this one can know
    if they are dealing with a new or re-used model.
    """

    Inserted = auto()
    Existing = auto()
    Overwrite = auto()


class PrimaryKeyMap:
    """
    A map between a primary key in one primary key sequence (like a database) and another (like the
    ordinals in a backup JSON file). As models are moved between databases, their absolute contents
    may stay the same, but their relative identifiers may change. This class allows us to track how
    those relations have been transformed, thereby preserving the model references between one
    another.

    Note that the map assumes that the primary keys in question are integers. In particular, natural
    keys are not supported!
    """

    # Pydantic duplicates global default models on a per-instance basis, so using `{}` here is safe.
    mapping: Dict[str, Dict[int, Tuple[int, ImportKind]]]

    def __init__(self):
        self.mapping = defaultdict(dict)

    def get_pk(self, model_name: NormalizedModelName, old: int) -> Optional[int]:
        """
        Get the new, post-mapping primary key from an old primary key.
        """

        pk_map = self.mapping.get(str(model_name))
        if pk_map is None:
            return None

        entry = pk_map.get(old)
        if entry is None:
            return None

        return entry[0]

    def get_pks(self, model_name: NormalizedModelName) -> Set[int]:
        """
        Get a list of all of the pks for a specific model.
        """

        return {entry[0] for entry in self.mapping[str(model_name)].items()}

    def get_kind(self, model_name: NormalizedModelName, old: int) -> Optional[ImportKind]:
        """
        Is the mapped entry a newly inserted model, or an already existing one that has been merged in?
        """

        pk_map = self.mapping.get(str(model_name))
        if pk_map is None:
            return None

        entry = pk_map.get(old)
        if entry is None:
            return None

        return entry[1]

    def insert(self, model_name: NormalizedModelName, old: int, new: int, kind: ImportKind) -> None:
        """
        Create a new OLD_PK -> NEW_PK mapping for the given model.
        """

        self.mapping[str(model_name)][old] = (new, kind)


# No arguments, so we lazily cache the result after the first calculation.
@lru_cache(maxsize=1)
def dependencies() -> dict[NormalizedModelName, ModelRelations]:
    """Produce a dictionary mapping model type definitions to a `ModelDeps` describing their dependencies."""

    from django.apps import apps

    from sentry.db.models.base import ModelSiloLimit
    from sentry.db.models.fields.bounded import (
        BoundedBigIntegerField,
        BoundedIntegerField,
        BoundedPositiveIntegerField,
    )
    from sentry.db.models.fields.foreignkey import FlexibleForeignKey
    from sentry.db.models.fields.hybrid_cloud_foreign_key import HybridCloudForeignKey
    from sentry.db.models.fields.onetoone import OneToOneCascadeDeletes
    from sentry.models.actor import Actor
    from sentry.models.team import Team

    # Process the list of models, and get the list of dependencies.
    model_dependencies_dict: Dict[NormalizedModelName, ModelRelations] = {}
    app_configs = apps.get_app_configs()
    models_from_names = {
        get_model_name(model): model
        for app_config in app_configs
        for model in app_config.get_models()
    }

    for app_config in app_configs:
        if app_config.label in EXCLUDED_APPS:
            continue

        model_iterator = app_config.get_models()

        for model in model_iterator:
            foreign_keys: Dict[str, ForeignField] = dict()
            uniques: Set[FrozenSet[str]] = {
                frozenset(combo) for combo in model._meta.unique_together
            }

            # Now add a dependency for any FK relation visible to Django.
            for field in model._meta.get_fields():
                is_nullable = getattr(field, "null", False)
                if getattr(field, "unique", False):
                    uniques.add(frozenset({field.name}))

                rel_model = getattr(field.remote_field, "model", None)
                if rel_model is not None and rel_model != model:
                    # TODO(hybrid-cloud): actor refactor. Add kludgy conditional preventing walking
                    # actor.team_id, which avoids circular imports
                    if model == Actor and rel_model == Team:
                        continue

                    if isinstance(field, FlexibleForeignKey):
                        foreign_keys[field.name] = ForeignField(
                            model=rel_model,
                            kind=ForeignFieldKind.FlexibleForeignKey,
                            nullable=is_nullable,
                        )
                    elif isinstance(field, ForeignKey):
                        foreign_keys[field.name] = ForeignField(
                            model=rel_model,
                            kind=ForeignFieldKind.DefaultForeignKey,
                            nullable=is_nullable,
                        )
                elif isinstance(field, HybridCloudForeignKey):
                    rel_model = models_from_names[NormalizedModelName(field.foreign_model_name)]
                    foreign_keys[field.name] = ForeignField(
                        model=rel_model,
                        kind=ForeignFieldKind.HybridCloudForeignKey,
                        nullable=is_nullable,
                    )

            # Get all simple O2O relations as well.
            one_to_one_fields = [
                field for field in model._meta.get_fields() if isinstance(field, OneToOneField)
            ]
            for field in one_to_one_fields:
                is_nullable = getattr(field, "null", False)
                if getattr(field, "unique", False):
                    uniques.add(frozenset({field.name}))

                rel_model = getattr(field.remote_field, "model", None)
                if rel_model is not None and rel_model != model:
                    if isinstance(field, OneToOneCascadeDeletes):
                        foreign_keys[field.name] = ForeignField(
                            model=rel_model,
                            kind=ForeignFieldKind.OneToOneCascadeDeletes,
                            nullable=is_nullable,
                        )
                    elif isinstance(field, OneToOneField):
                        foreign_keys[field.name] = ForeignField(
                            model=rel_model,
                            kind=ForeignFieldKind.DefaultOneToOneField,
                            nullable=is_nullable,
                        )
                    else:
                        raise RuntimeError("Unknown one to kind")

            # Use some heuristics to grab numeric-only unlinked dependencies.
            simple_integer_fields = [
                field
                for field in model._meta.get_fields()
                if isinstance(field, BoundedIntegerField)
                or isinstance(field, BoundedBigIntegerField)
                or isinstance(field, BoundedPositiveIntegerField)
            ]
            for field in simple_integer_fields:
                is_nullable = getattr(field, "null", False)
                if getattr(field, "unique", False):
                    uniques.add(frozenset({field.name}))

                # "actor_id", when used as a simple integer field rather than a `ForeignKey` into an
                # `Actor`, refers to a unified but loosely specified means by which to index into a
                # either a `Team` or `User`, before this pattern was formalized by the official
                # `Actor` model. Because of this, we avoid assuming that it is a dependency into
                # `Actor` and just ignore it.
                if field.name.endswith("_id") and field.name != "actor_id":
                    candidate = NormalizedModelName("sentry." + field.name[:-3].replace("_", ""))
                    if candidate and candidate in models_from_names:
                        foreign_keys[field.name] = ForeignField(
                            model=models_from_names[candidate],
                            kind=ForeignFieldKind.ImplicitForeignKey,
                            nullable=is_nullable,
                        )

            model_dependencies_dict[get_model_name(model)] = ModelRelations(
                dangling=None,
                foreign_keys=foreign_keys,
                model=model,
                relocation_scope=getattr(model, "__relocation_scope__", RelocationScope.Excluded),
                silos=list(
                    getattr(model._meta, "silo_limit", ModelSiloLimit(SiloMode.MONOLITH)).modes
                ),
                table_name=model._meta.db_table,
                # Sort the constituent sets alphabetically, so that we get consistent JSON output.
                uniques=sorted(list(uniques), key=lambda u: ":".join(sorted(list(u)))),
            )

    # Get a flat list of "root" models, then mark all of them as non-dangling.
    relocation_root_models: list[NormalizedModelName] = []
    for root_models in RelocationRootModels:
        relocation_root_models.extend(root_models.value)
    for model_name in relocation_root_models:
        model_dependencies_dict[model_name].dangling = False

    # Now that all `ModelRelations` have been added to the `model_dependencies_dict`, we can circle
    # back and figure out which ones are actually dangling. We do this by marking all of the root
    # models non-dangling, then traversing from every other model to a (possible) root model
    # recursively. At this point there should be no circular reference chains, so if we encounter
    # them, fail immediately.
    def resolve_dangling(seen: Set[NormalizedModelName], model_name: NormalizedModelName) -> bool:
        model_relations = model_dependencies_dict[model_name]
        model_name = get_model_name(model_relations.model)
        if model_name in seen:
            raise RuntimeError(
                f"Circular dependency: {model_name} cannot transitively reference itself"
            )
        if model_relations.dangling is not None:
            return model_relations.dangling

        # TODO(getsentry/team-ospo#190): Maybe make it so that `Global` models are never "dangling",
        # since we want to export 100% of models in `ExportScope.Global` anyway?

        seen.add(model_name)

        # If we are able to successfully over all of the foreign keys without encountering a
        # dangling reference, we know that this model is dangling as well.
        model_relations.dangling = True
        for ff in model_relations.foreign_keys.values():
            if not ff.nullable:
                foreign_model_name = get_model_name(ff.model)
                if not resolve_dangling(seen, foreign_model_name):
                    # We only need one non-dangling reference to mark this model as non-dangling as
                    # well.
                    model_relations.dangling = False
                    break

        seen.remove(model_name)
        return model_relations.dangling

    for model_name in model_dependencies_dict.keys():
        if model_name not in relocation_root_models:
            resolve_dangling(set(), model_name)

    return model_dependencies_dict


# No arguments, so we lazily cache the result after the first calculation.
@lru_cache(maxsize=1)
def sorted_dependencies() -> list[Type[models.base.Model]]:
    """Produce a list of model definitions such that, for every item in the list, all of the other models it mentions in its fields and/or natural key (ie, its "dependencies") have already appeared in the list.

    Similar to Django's algorithm except that we discard the importance of natural keys
    when sorting dependencies (ie, it works without them)."""

    model_dependencies_dict = list(dependencies().values())
    model_dependencies_dict.reverse()
    model_set = {md.model for md in model_dependencies_dict}

    # Now sort the models to ensure that dependencies are met. This
    # is done by repeatedly iterating over the input list of models.
    # If all the dependencies of a given model are in the final list,
    # that model is promoted to the end of the final list. This process
    # continues until the input list is empty, or we do a full iteration
    # over the input models without promoting a model to the final list.
    # If we do a full iteration without a promotion, that means there are
    # circular dependencies in the list.
    model_list = []
    while model_dependencies_dict:
        skipped = []
        changed = False
        while model_dependencies_dict:
            model_deps = model_dependencies_dict.pop()
            deps = model_deps.flatten()
            model = model_deps.model

            # If all of the models in the dependency list are either already
            # on the final model list, or not on the original serialization list,
            # then we've found another model with all it's dependencies satisfied.
            found = True
            for candidate in ((d not in model_set or d in model_list) for d in deps):
                if not candidate:
                    found = False
            if found:
                model_list.append(model)
                changed = True
            else:
                skipped.append(model_deps)
        if not changed:
            raise RuntimeError(
                "Can't resolve dependencies for %s in serialized app list."
                % ", ".join(
                    str(get_model_name(m.model))
                    for m in sorted(skipped, key=lambda mr: get_model_name(mr.model))
                )
            )
        model_dependencies_dict = skipped

    return model_list
