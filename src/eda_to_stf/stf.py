"""STF (Study Transfer Format) file generator."""

import csv
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
    }
    return mapping.get(eda_shape.lower(), "categorical")


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

    # Build variables list
    var_list = []
    for var in variables:
        var_entry: dict[str, Any] = {
            "variable": var.stable_id,
            "display_name": var.display_name or var.stable_id,
            "data_type": map_data_type(var.data_type),
            "data_shape": map_data_shape(var.data_shape),
        }

        if var.provider_label:
            var_entry["provider_label"] = [var.provider_label]

        if var.definition:
            var_entry["definition"] = var.definition

        if var.unit:
            var_entry["unit"] = var.unit

        if var.parent_stable_id:
            var_entry["parent_variable"] = var.parent_stable_id

        var_list.append(var_entry)

    result: dict[str, Any] = {
        "name": entity_name,
        "display_name": entity.display_name,
        "display_name_plural": entity.display_name_plural,
        "id_columns": id_columns,
        "variables": var_list,
    }

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
