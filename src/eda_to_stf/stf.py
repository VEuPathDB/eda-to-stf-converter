"""STF (Study Transfer Format) file generator."""

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .db import Entity, Study, Variable


def entity_name_for_stf(entity: Entity) -> str:
    """Convert entity to STF-friendly name (lowercase, underscores)."""
    return entity.internal_abbrev.lower()


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


def parse_vocabulary(vocab_json: str | None) -> list | None:
    """Parse vocabulary JSON field into list for ordinal_levels.

    Args:
        vocab_json: JSON string from vocabulary CLOB field

    Returns:
        List of vocabulary items or None if empty/invalid
    """
    if not vocab_json:
        return None

    try:
        vocab = json.loads(vocab_json)
        if isinstance(vocab, list):
            return vocab
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def parse_hidden(hidden_str: str | None) -> list | None:
    """Parse hidden field into list.

    Args:
        hidden_str: Comma-separated string or single value

    Returns:
        List of hidden contexts or None if empty
    """
    if not hidden_str:
        return None

    # Split by comma and strip whitespace
    items = [item.strip() for item in hidden_str.split(',') if item.strip()]
    return items if items else None


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


def generate_entity_yaml(
    entity: Entity,
    variables: list[Variable],
    ancestors: list[Entity]
) -> dict:
    """Generate entity-<name>.yaml content."""
    entity_name = entity_name_for_stf(entity)

    # Build set of entity stable_ids in the hierarchy (for filtering parent references)
    entity_ids_in_hierarchy = {entity.stable_id} | {a.stable_id for a in ancestors}

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

    # Separate category-only variables (no provider_label) from data variables
    # Category-only variables are organizational containers without actual data
    categories_list = []
    var_list = []

    for var in variables:
        # Variables without provider_label are category-only (organizational)
        is_category = not var.provider_label

        if is_category:
            cat_entry: dict[str, Any] = {
                "category": var.stable_id,
                "display_name": var.display_name or var.stable_id,
                "data_type": map_data_type(var.data_type),
                "data_shape": map_data_shape(var.data_shape),
            }

            if var.definition:
                cat_entry["definition"] = var.definition

            # Only set parent_category if parent is another variable/category, not any entity in the hierarchy
            if var.parent_stable_id and var.parent_stable_id not in entity_ids_in_hierarchy:
                cat_entry["parent_category"] = var.parent_stable_id

            # Display metadata for categories
            if var.display_order is not None:
                cat_entry["display_order"] = var.display_order
            if var.display_type:
                cat_entry["display_type"] = var.display_type

            categories_list.append(cat_entry)
        else:
            # Ordinal levels from vocabulary - parse first to determine data_shape and data_type
            ordinal_levels = parse_vocabulary(var.vocabulary)

            # If ordinal_levels exists, data_shape should be ordinal and data_type should be string
            if ordinal_levels:
                data_shape = "ordinal"
                data_type = "string"
            else:
                data_shape = map_data_shape(var.data_shape)
                data_type = map_data_type(var.data_type)

            var_entry: dict[str, Any] = {
                "variable": var.stable_id,
                "display_name": var.display_name or var.stable_id,
                "data_type": data_type,
                "data_shape": data_shape,
                "provider_label": [var.provider_label],
            }

            # Required fields
            if var.definition:
                var_entry["definition"] = var.definition

            # Only set parent_category if parent is another variable/category, not any entity in the hierarchy
            if var.parent_stable_id and var.parent_stable_id not in entity_ids_in_hierarchy:
                var_entry["parent_category"] = var.parent_stable_id

            # Add ordinal levels if present
            if ordinal_levels:
                var_entry["ordinal_levels"] = ordinal_levels

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
            if var.has_values is not None:
                var_entry["has_values"] = var.has_values
            if var.has_study_dependent_vocabulary is not None:
                var_entry["has_study_dependent_vocabulary"] = var.has_study_dependent_vocabulary
            if var.impute_zero is not None:
                var_entry["impute_zero"] = var.impute_zero

            # Hidden contexts
            hidden_list = parse_hidden(var.hidden)
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
        "display_name_plural": entity.display_name_plural,
        "id_columns": id_columns,
        "variables": var_list,
    }

    # Only include categories section if there are category-only variables
    if categories_list:
        result["categories"] = categories_list

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

    def __init__(self, output_dir: Path):
        """Initialize writer with output directory."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_study_yaml(self, study: Study, entities: list[Entity]):
        """Write study.yaml file."""
        content = generate_study_yaml(study, entities)
        path = self.output_dir / "study.yaml"

        with open(path, "w") as f:
            yaml.dump(content, f, default_flow_style=False, sort_keys=False)

        return path

    def write_entity_yaml(
        self,
        entity: Entity,
        variables: list[Variable],
        ancestors: list[Entity]
    ) -> Path:
        """Write entity-<name>.yaml file."""
        content = generate_entity_yaml(entity, variables, ancestors)
        entity_name = entity_name_for_stf(entity)
        path = self.output_dir / f"entity-{entity_name}.yaml"

        with open(path, "w") as f:
            yaml.dump(content, f, default_flow_style=False, sort_keys=False)

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
