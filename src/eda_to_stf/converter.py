"""Main converter logic - orchestrates EDA to STF conversion."""

from pathlib import Path

from .db import EdaDatabase, Entity
from .stf import StfWriter, entity_name_for_stf, get_ancestor_chain


def convert_study(
    db: EdaDatabase,
    study_stable_id: str,
    output_dir: Path,
    verbose: bool = False
) -> Path:
    """Convert an EDA study to STF format.

    Args:
        db: Connected EdaDatabase instance
        study_stable_id: The stable_id of the study to convert
        output_dir: Directory to write STF files
        verbose: Print progress messages

    Returns:
        Path to the output directory
    """
    if verbose:
        print(f"Fetching study: {study_stable_id}")

    # Get study metadata
    study = db.get_study(study_stable_id)

    if verbose:
        print(f"  Study internal_abbrev: {study.internal_abbrev}")

    # Get all entities for the study
    entities = db.get_entities(study_stable_id)

    if verbose:
        print(f"  Found {len(entities)} entities")

    # Build lookup map
    entities_by_id: dict[str, Entity] = {e.stable_id: e for e in entities}

    # Sort entities by hierarchy (parents before children)
    sorted_entities = _sort_entities_by_hierarchy(entities, entities_by_id)

    # Initialize writer
    writer = StfWriter(output_dir)

    # Write study.yaml
    writer.write_study_yaml(study, sorted_entities)
    if verbose:
        print(f"  Wrote study.yaml")

    # Process each entity
    for entity in sorted_entities:
        if verbose:
            print(f"  Processing entity: {entity.display_name} ({entity.internal_abbrev})")

        # Get ancestor chain for hierarchy
        ancestors = get_ancestor_chain(entity, entities_by_id)

        # Get variables for this entity
        variables = db.get_variables(study.internal_abbrev, entity.internal_abbrev)

        if verbose:
            print(f"    Found {len(variables)} variables")

        # Write entity YAML
        writer.write_entity_yaml(entity, variables, ancestors)

        # Get entity data (pivoted to wide format)
        # Pass ancestor abbreviations for joining with ancestors table
        ancestor_abbrevs = [a.internal_abbrev for a in ancestors]
        columns, rows = db.get_entity_data(
            study.internal_abbrev,
            entity.internal_abbrev,
            ancestor_abbrevs=ancestor_abbrevs if ancestors else None
        )

        if verbose:
            print(f"    Found {len(rows)} data rows")

        # Write entity TSV
        writer.write_entity_tsv(entity, ancestors, columns, rows, entities_by_id)

        entity_name = entity_name_for_stf(entity)
        if verbose:
            print(f"    Wrote entity-{entity_name}.yaml and entity-{entity_name}.tsv")

    warnings_path = writer.write_warnings_log()
    if warnings_path:
        print(
            f"  {len(writer.warnings)} variable(s) had annotation demoted; "
            f"see {warnings_path.name}"
        )

    if verbose:
        print(f"STF files written to: {output_dir}")

    return output_dir


def _sort_entities_by_hierarchy(
    entities: list[Entity],
    entities_by_id: dict[str, Entity]
) -> list[Entity]:
    """Sort entities so parents come before children."""
    sorted_list = []
    visited = set()

    def visit(entity: Entity):
        if entity.stable_id in visited:
            return
        # Visit parent first
        if entity.parent_stable_id and entity.parent_stable_id in entities_by_id:
            visit(entities_by_id[entity.parent_stable_id])
        visited.add(entity.stable_id)
        sorted_list.append(entity)

    for entity in entities:
        visit(entity)

    return sorted_list
