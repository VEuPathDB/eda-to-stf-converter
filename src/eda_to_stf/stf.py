"""STF (Study Transfer Format) file generator."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .db import Collection, Entity, Study, Variable

# Delimiter used by db.get_entity_data when concatenating multi-valued attributes
MULTI_VALUE_DELIMITER = ";"

# YAML 1.1 readers (R's yaml package among them) resolve these bare words to
# booleans. PyYAML uses the narrower 1.2 set, so it would emit them unquoted
# and a vocabulary of "Y" would load back as TRUE.
_YAML_11_BOOLEANS = frozenset(
    "y Y yes Yes YES n N no No NO "
    "true True TRUE false False FALSE on On ON off Off OFF".split()
)


class StfDumper(yaml.SafeDumper):
    """YAML dumper that quotes strings other parsers would read as booleans."""


def _represent_str(dumper: yaml.SafeDumper, data: str):
    style = "'" if data in _YAML_11_BOOLEANS else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


StfDumper.add_representer(str, _represent_str)


def entity_name_for_stf(entity: Entity) -> str:
    """STF name for an entity.

    stable_id is the entity's authoritative identity and is unique within a
    study; internal_abbrev is a display convenience that upstream does not
    guarantee, and it names the EDA tables rather than the STF files.
    """
    return entity.stable_id


def map_data_type(eda_type: str | None) -> str:
    """Map EDA data type to STF data type."""
    if not eda_type:
        return "string"

    mapping = {
        "string": "string",
        "number": "number",
        "integer": "integer",
        "date": "date",
        "longitude": "number",
    }
    return mapping.get(eda_type.lower(), "string")


def map_data_shape(eda_shape: str | None) -> str:
    """Map EDA data shape to STF data shape."""
    if not eda_shape:
        return "categorical"

    mapping = {
        "continuous": "continuous",
        "categorical": "categorical",
        "ordinal": "ordinal",
        "binary": "binary",
    }
    return mapping.get(eda_shape.lower(), "categorical")


def parse_json_list(value: str | None) -> list | None:
    """Parse an EDA JSON-array column into a list of strings.

    EDA stores provider_label, hidden and vocabulary as JSON arrays. Values that
    predate that convention are returned as a single-element list.
    """
    if not value:
        return None

    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return [value.strip()] if value.strip() else None

    if isinstance(parsed, list):
        items = [str(item) for item in parsed]
        return items or None
    return [str(parsed)]


def normalize_shape(
    data_type: str | None,
    data_shape: str | None,
    vocabulary: list | None,
) -> tuple[str, str, list | None, list | None, str | None]:
    """Resolve STF data_type/data_shape/vocabulary from EDA metadata.

    EDA's data_shape already encodes ordinal_values and force_string_type, so it
    is passed through rather than re-inferred. STF requires ordinal variables to
    carry levels and to be integer or string; annotation that violates either is
    demoted so the study still loads.

    Returns:
        (data_type, data_shape, ordinal_levels, vocabulary_order, warning)
    """
    stf_type = map_data_type(data_type)
    stf_shape = map_data_shape(data_shape)

    if stf_shape != "ordinal":
        vocab_order = vocabulary if stf_shape in ("categorical", "binary") else None
        return stf_type, stf_shape, None, vocab_order, None

    if not vocabulary:
        demoted = "categorical" if stf_type == "string" else "continuous"
        return (
            stf_type,
            demoted,
            None,
            None,
            f"data_shape 'ordinal' with no vocabulary; demoted to '{demoted}'",
        )

    if stf_type not in ("integer", "string"):
        return (
            stf_type,
            "continuous",
            None,
            None,
            (
                f"data_shape 'ordinal' is incompatible with data_type "
                f"'{stf_type}'; demoted to 'continuous' and vocabulary dropped"
            ),
        )

    return stf_type, "ordinal", vocabulary, None, None


def build_entity_hierarchy(entities: list[Entity]) -> dict[str, list[Entity]]:
    """Build parent -> children mapping and return entities in hierarchical order.

    Returns:
        Dict mapping parent_stable_id to list of child entities.
    """
    children_map: dict[str, list[Entity]] = {}
    for entity in entities:
        parent_id = entity.parent_stable_id or ""
        if parent_id not in children_map:
            children_map[parent_id] = []
        children_map[parent_id].append(entity)

    return children_map


def get_ancestor_chain(
    entity: Entity,
    entities_by_id: dict[str, Entity]
) -> list[Entity]:
    """Get ordered list of ancestors from root to immediate parent."""
    ancestors = []
    current = entity

    while current.parent_stable_id:
        parent = entities_by_id.get(current.parent_stable_id)
        if not parent:
            break
        ancestors.insert(0, parent)
        current = parent

    return ancestors


def generate_study_yaml(study: Study, entities: list[Entity]) -> dict:
    """Generate study.yaml content."""
    return {
        "name": study.stable_id,
        "entities": [entity_name_for_stf(e) for e in entities]
    }


@dataclass
class ConversionWarning:
    """An EDA annotation that had to be altered to produce loadable STF."""
    entity: str
    variable: str
    message: str


def generate_collection_entry(collection: Collection) -> dict:
    """Build one STF collections entry.

    Fields EDA derives from the member variables (num_members, data_type,
    data_shape, unit, precision, range_min, range_max) are left out; STF
    recomputes them on load.
    """
    entry: dict[str, Any] = {
        "category": collection.stable_id,
        "stable_id": collection.stable_id,
        "display_name": collection.display_name,
        "member": collection.member,
        "member_plural": collection.member_plural,
    }

    if collection.is_proportion is not None:
        entry["is_proportion"] = collection.is_proportion
    if collection.is_compositional is not None:
        entry["is_compositional"] = collection.is_compositional
    if collection.impute_zero is not None:
        entry["impute_zero"] = collection.impute_zero

    # EDA writes the literal string 'NULL' where there is no normalization
    method = collection.normalization_method
    if method and method.upper() != "NULL":
        entry["normalization_method"] = method

    if collection.display_range_min:
        entry["display_range_min"] = collection.display_range_min
    if collection.display_range_max:
        entry["display_range_max"] = collection.display_range_max

    return entry


def generate_entity_yaml(
    entity: Entity,
    variables: list[Variable],
    ancestors: list[Entity],
    warnings: list[ConversionWarning] | None = None,
    collections: list[Collection] | None = None,
    collection_members: dict[str, set[str]] | None = None,
) -> dict:
    """Generate entity-<name>.yaml content."""
    entity_name = entity_name_for_stf(entity)

    # A parent_category must resolve to a variable or category in this same
    # entity; EDA parents pointing outside it would fail STF validation.
    # Parents that are entities are the normal top of the tree, not an error.
    local_stable_ids = {v.stable_id for v in variables}
    entity_ids_in_hierarchy = {entity.stable_id} | {a.stable_id for a in ancestors}

    def resolve_parent(var: Variable) -> str | None:
        parent = var.parent_stable_id
        if not parent or parent in local_stable_ids:
            return parent
        if parent in entity_ids_in_hierarchy:
            return None
        if warnings is not None:
            warnings.append(ConversionWarning(
                entity=entity_name,
                variable=var.stable_id,
                message=(
                    f"parent_category '{parent}' is not defined in this entity; "
                    f"reference dropped"
                ),
            ))
        return None

    # Build id_columns - ancestors first, then self
    id_columns = []

    for i, ancestor in enumerate(ancestors):
        ancestor_name = entity_name_for_stf(ancestor)
        # entity_level is negative for ancestors (-1 = parent, -2 = grandparent, etc.)
        level = -(len(ancestors) - i)
        id_columns.append({
            "id_column": f"{ancestor_name}.id",
            "entity_name": ancestor_name,
            "entity_level": level
        })

    # Add self
    id_columns.append({
        "id_column": f"{entity_name}.id",
        "entity_name": entity_name,
        "entity_level": 0
    })

    categories_list = []
    var_list = []

    for var in variables:
        # has_values distinguishes real variables from organizational categories;
        # provider_label is absent on whole entities' worth of real variables.
        if not var.has_values:
            cat_entry: dict[str, Any] = {
                "category": var.stable_id,
                "display_name": var.display_name or var.stable_id,
            }

            if var.definition:
                cat_entry["definition"] = var.definition

            parent_category = resolve_parent(var)
            if parent_category:
                cat_entry["parent_category"] = parent_category

            # Display metadata for categories
            if var.display_order is not None:
                cat_entry["display_order"] = var.display_order
            if var.display_type:
                cat_entry["display_type"] = var.display_type

            hidden_list = parse_json_list(var.hidden)
            if hidden_list:
                cat_entry["hidden"] = hidden_list

            categories_list.append(cat_entry)
        else:
            vocabulary = parse_json_list(var.vocabulary)
            data_type, data_shape, ordinal_levels, vocabulary_order, warning = (
                normalize_shape(var.data_type, var.data_shape, vocabulary)
            )

            if warning is not None and warnings is not None:
                warnings.append(ConversionWarning(
                    entity=entity_name,
                    variable=var.stable_id,
                    message=warning,
                ))

            var_entry: dict[str, Any] = {
                "variable": var.stable_id,
                "display_name": var.display_name or var.stable_id,
                "data_type": data_type,
                "data_shape": data_shape,
                "provider_label": parse_json_list(var.provider_label) or [],
            }

            # Required fields
            if var.definition:
                var_entry["definition"] = var.definition

            parent_category = resolve_parent(var)
            if parent_category:
                var_entry["parent_category"] = parent_category

            # Ordinals carry levels; other factors carry a sort order
            if ordinal_levels:
                var_entry["ordinal_levels"] = ordinal_levels
            if vocabulary_order:
                var_entry["vocabulary_order"] = vocabulary_order

            # Display metadata
            if var.display_order is not None:
                var_entry["display_order"] = var.display_order
            if var.display_type:
                var_entry["display_type"] = var.display_type

            # Ranges and binning
            if var.display_range_min:
                var_entry["display_range_min"] = var.display_range_min
            if var.display_range_max:
                var_entry["display_range_max"] = var.display_range_max
            if var.bin_width_override:
                var_entry["bin_width_override"] = var.bin_width_override

            # Scale and units
            if var.scale:
                var_entry["scale"] = var.scale
            if var.unit:
                var_entry["unit"] = var.unit

            # Boolean flags
            if var.is_temporal is not None:
                var_entry["is_temporal"] = var.is_temporal
            if var.is_featured is not None:
                var_entry["is_featured"] = var.is_featured
            if var.is_merge_key is not None:
                var_entry["is_merge_key"] = var.is_merge_key
            if var.is_repeated is not None:
                var_entry["is_repeated"] = var.is_repeated
            if var.is_multi_valued is not None:
                var_entry["is_multi_valued"] = var.is_multi_valued
            if var.is_multi_valued:
                var_entry["multi_value_delimiter"] = MULTI_VALUE_DELIMITER
            if var.has_study_dependent_vocabulary is not None:
                var_entry["has_study_dependent_vocabulary"] = var.has_study_dependent_vocabulary
            if var.impute_zero is not None:
                var_entry["impute_zero"] = var.impute_zero

            # Hidden contexts
            hidden_list = parse_json_list(var.hidden)
            if hidden_list:
                var_entry["hidden"] = hidden_list

            # Variable specs for special processing
            if var.weighting_variable_spec:
                var_entry["weighting_variable_spec"] = var.weighting_variable_spec
            if var.variable_spec_to_impute_zeroes_for:
                var_entry["variable_spec_to_impute_zeroes_for"] = var.variable_spec_to_impute_zeroes_for

            var_list.append(var_entry)

    result: dict[str, Any] = {
        "name": entity_name,
        "display_name": entity.display_name,
    }
    if entity.display_name_plural:
        result["display_name_plural"] = entity.display_name_plural
    result["id_columns"] = id_columns
    result["variables"] = var_list

    # Only include categories section if there are category-only variables
    if categories_list:
        result["categories"] = categories_list

    category_ids = {c["category"] for c in categories_list}
    collections_list = []
    for collection in collections or []:
        if collection.stable_id not in category_ids:
            if warnings is not None:
                warnings.append(ConversionWarning(
                    entity=entity_name,
                    variable=collection.stable_id,
                    message=(
                        "collection has no matching variable category in this "
                        "entity; collection dropped"
                    ),
                ))
            continue
        if collection_members is not None and warnings is not None:
            declared = collection_members.get(collection.stable_id, set())
            from_parent_links = {
                v.stable_id
                for v in variables
                if v.parent_stable_id == collection.stable_id and v.has_values
            }
            if declared != from_parent_links:
                missing = sorted(declared - from_parent_links)
                extra = sorted(from_parent_links - declared)
                warnings.append(ConversionWarning(
                    entity=entity_name,
                    variable=collection.stable_id,
                    message=(
                        "collection membership disagrees with parent_category "
                        f"links (only in collectionattribute: {missing or '-'}; "
                        f"only in parent links: {extra or '-'})"
                    ),
                ))

        collections_list.append(generate_collection_entry(collection))

    if collections_list:
        result["collections"] = collections_list

    # Add EDA-specific fields as comments/extensions
    if entity.description:
        result["description"] = entity.description

    # Additional EDA metadata (may not be in STF spec but useful)
    result["_eda_metadata"] = {
        "stable_id": entity.stable_id,
        "has_attribute_collections": entity.has_attribute_collections,
        "is_many_to_one_with_parent": entity.is_many_to_one_with_parent,
        "cardinality": entity.cardinality,
    }

    return result


def generate_entity_tsv_header(
    entity: Entity,
    ancestors: list[Entity],
    variable_ids: list[str]
) -> list[str]:
    """Generate TSV header row for entity data.

    Format: parent IDs (no suffix), then entity ID with '\\ Descriptors' suffix, then variables.
    """
    entity_name = entity_name_for_stf(entity)
    headers = []

    # Add ancestor ID columns (no suffix)
    for ancestor in ancestors:
        headers.append(f"{entity_name_for_stf(ancestor)}.id")

    # Add entity's own ID column with Descriptors suffix
    headers.append(f"{entity_name}.id \\\\ Descriptors")

    # Add variable columns
    headers.extend(variable_ids)

    return headers


class StfWriter:
    """Writes STF files to a directory."""

    WARNINGS_FILENAME = "conversion-warnings.log"

    def __init__(self, output_dir: Path):
        """Initialize writer with output directory."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.warnings: list[ConversionWarning] = []

    def write_study_yaml(self, study: Study, entities: list[Entity]):
        """Write study.yaml file."""
        content = generate_study_yaml(study, entities)
        path = self.output_dir / "study.yaml"

        with open(path, "w") as f:
            yaml.dump(
                content, f, Dumper=StfDumper,
                default_flow_style=False, sort_keys=False,
            )

        return path

    def write_entity_yaml(
        self,
        entity: Entity,
        variables: list[Variable],
        ancestors: list[Entity],
        collections: list[Collection] | None = None,
        collection_members: dict[str, set[str]] | None = None,
    ) -> Path:
        """Write entity-<name>.yaml file."""
        content = generate_entity_yaml(
            entity, variables, ancestors, self.warnings,
            collections, collection_members,
        )
        entity_name = entity_name_for_stf(entity)
        path = self.output_dir / f"entity-{entity_name}.yaml"

        with open(path, "w") as f:
            yaml.dump(
                content, f, Dumper=StfDumper,
                default_flow_style=False, sort_keys=False,
            )

        return path

    def write_entity_tsv(
        self,
        entity: Entity,
        ancestors: list[Entity],
        columns: list[str],
        rows: list[list],
        entities_by_id: dict[str, Entity]
    ) -> Path:
        """Write entity-<name>.tsv file.

        Args:
            entity: The entity being written
            ancestors: Ordered list of ancestor entities
            columns: Column names from database (entity_id + attribute_ids)
            rows: Data rows from database
            entities_by_id: Map of stable_id -> Entity for looking up parents
        """
        entity_name = entity_name_for_stf(entity)
        path = self.output_dir / f"entity-{entity_name}.tsv"

        # Build header - columns from DB are:
        # [ancestor_ids..., entity_id, attribute_ids...]
        # We need to rename ID columns and add Descriptors suffix to entity ID
        num_ancestors = len(ancestors)
        # Attribute IDs start after ancestor IDs and entity ID
        attribute_ids = columns[num_ancestors + 1:] if len(columns) > num_ancestors + 1 else []

        headers = generate_entity_tsv_header(entity, ancestors, attribute_ids)

        with open(path, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(headers)

            for row in rows:
                # Data now includes ancestor IDs from the DB query
                writer.writerow(row)

        return path

    def write_warnings_log(self) -> Path | None:
        """Write conversion-warnings.log if any annotation was altered."""
        if not self.warnings:
            return None

        path = self.output_dir / self.WARNINGS_FILENAME

        with open(path, "w") as f:
            f.write("entity\tvariable\tmessage\n")
            f.writelines(
                f"{w.entity}\t{w.variable}\t{w.message}\n" for w in self.warnings
            )

        return path
