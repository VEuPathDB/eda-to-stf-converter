"""STF (Study Transfer Format) file generator."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import provenance
from .db import Collection, Entity, Study, Variable

# Database config keys recorded in dump-info.yaml; an allowlist so credentials never are.
DUMP_INFO_DB_KEYS = {"type": "oracle", "host": None, "port": None, "name": None}

# Delimiters for joining a multi-valued variable's values, in order of preference;
# each variable gets the first that none of its values contain. Printable only,
# and never a LIKE wildcard or quote (db.delimiter_conflicts_sql searches for them).
MULTI_VALUE_DELIMITER_CANDIDATES = (";", "|", "~", "^")
MULTI_VALUE_DELIMITER = MULTI_VALUE_DELIMITER_CANDIDATES[0]

# YAML 1.1 readers (R's yaml package among them) resolve these bare words to
# booleans. PyYAML uses the narrower 1.2 set, so it would emit them unquoted
# and a vocabulary of "Y" would load back as TRUE.
_YAML_11_BOOLEANS = frozenset(
    "y Y yes Yes YES n N no No NO "
    "true True TRUE false False FALSE on On ON off Off OFF".split()
)

LATITUDE_STABLE_ID = "OBI_0001620"
LONGITUDE_STABLE_ID = "OBI_0001621"

# study-wrangler allows units only on these data types.
UNIT_DATA_TYPES = ("integer", "number")

# Mixes within one collection that widen to a type every member satisfies;
# any other mix is left for validation to report.
COLLECTION_WIDENINGS = {
    "data_shape": ({"binary", "categorical"}, "categorical"),
    "data_type": ({"integer", "number"}, "number"),
}

_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"

# EDA geohash variables, by precision. Some studies carry their values with no
# attributegraph row; study-wrangler's geo check needs them as geoaggregators.
GEOHASH_PRECISION_BY_STABLE_ID = {
    "EUPATH_0043203": 1,
    "EUPATH_0043204": 2,
    "EUPATH_0043205": 3,
    "EUPATH_0043206": 4,
    "EUPATH_0043207": 5,
    "EUPATH_0043208": 6,
}


class StfDumper(yaml.SafeDumper):
    """YAML dumper that quotes strings other parsers would read as booleans."""


def _represent_str(dumper: yaml.SafeDumper, data: str):
    style = "'" if data in _YAML_11_BOOLEANS else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


StfDumper.add_representer(str, _represent_str)


def encode_geohash(latitude: float, longitude: float, precision: int) -> str:
    """Geohash as study-wrangler's encode_geohash() computes it.

    A value equal to the midpoint takes the lower half, unlike standard geohash.
    """
    ranges = {"lat": [-90.0, 90.0], "lng": [-180.0, 180.0]}
    coords = {"lat": float(latitude), "lng": float(longitude)}
    axis = "lng"
    chars = []
    for _ in range(precision):
        index = 0
        for _ in range(5):
            low, high = ranges[axis]
            mid = (low + high) / 2
            index <<= 1
            if coords[axis] <= mid:
                ranges[axis][1] = mid
            else:
                index |= 1
                ranges[axis][0] = mid
            axis = "lat" if axis == "lng" else "lng"
        chars.append(_GEOHASH_ALPHABET[index])
    return "".join(chars)


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
        "longitude": "longitude",
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
        "stable_id": study.stable_id,
        "entities": [entity_name_for_stf(e) for e in entities]
    }


@dataclass
class ConversionWarning:
    """An EDA annotation that had to be altered to produce loadable STF."""
    entity: str
    variable: str
    message: str


def value_attribute_ids(columns: Sequence[str], ancestors: list[Entity]) -> list[str]:
    """Attribute ids from stream_entity_data columns: [ancestor_ids..., entity_id, attribute_ids...]."""
    return list(columns[len(ancestors) + 1:])


def choose_multi_value_delimiter(
    entity_name: str, variable: str, taken: set[str]
) -> str:
    """First candidate delimiter that none of the variable's values contain."""
    for candidate in MULTI_VALUE_DELIMITER_CANDIDATES:
        if candidate not in taken:
            return candidate
    raise ValueError(
        f"entity {entity_name}, variable {variable}: values contain every "
        f"multi-value delimiter candidate ({' '.join(MULTI_VALUE_DELIMITER_CANDIDATES)})"
    )


def generate_geohash_entry(stable_id: str) -> dict:
    """Variable entry for a geohash attribute that has values but no attributegraph row."""
    precision = GEOHASH_PRECISION_BY_STABLE_ID[stable_id]
    return {
        "variable": stable_id,
        "stable_id": stable_id,
        "display_name": f"Geohash (precision {precision})",
        "data_type": "string",
        "data_shape": "categorical",
        "display_type": "geoaggregator",
        "hidden": ["everywhere"],
    }


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


def widen_collection_members(
    entity_name: str,
    collection_id: str,
    var_list: list[dict],
    warnings: list[ConversionWarning] | None,
) -> None:
    """Widen a collection's members to a common data_shape/data_type, in place.

    study-wrangler finds members by parent_category and requires these fields
    to be uniform across them.
    """
    members = [v for v in var_list if v.get("parent_category") == collection_id]
    for field, (mix, widened) in COLLECTION_WIDENINGS.items():
        if {m[field] for m in members} != mix:
            continue
        for member in members:
            if member[field] == widened:
                continue
            if warnings is not None:
                warnings.append(ConversionWarning(
                    entity=entity_name,
                    variable=member["stable_id"],
                    message=(
                        f"{field} '{member[field]}' widened to '{widened}' "
                        f"to match collection '{collection_id}'"
                    ),
                ))
            member[field] = widened


def generate_entity_yaml(
    entity: Entity,
    variables: list[Variable],
    ancestors: list[Entity],
    warnings: list[ConversionWarning] | None = None,
    collections: list[Collection] | None = None,
    collection_members: dict[str, set[str]] | None = None,
    value_ids: Iterable[str] = (),
    multi_value_delimiters: dict[str, str] | None = None,
) -> dict:
    """Generate entity-<name>.yaml content.

    value_ids are the attribute ids with values in this entity's attributevalue table.
    multi_value_delimiters maps a multi-valued variable to the delimiter its TSV
    values are joined with, when not MULTI_VALUE_DELIMITER.
    """
    entity_name = entity_name_for_stf(entity)

    # A row repeating the entity's own stable_id would be a second node for it;
    # its children's parent links already resolve to the entity.
    duplicates = [v for v in variables if v.stable_id == entity.stable_id]
    for dup in duplicates:
        if warnings is not None:
            warnings.append(ConversionWarning(
                entity=entity_name,
                variable=dup.stable_id,
                message=f"category '{dup.stable_id}' duplicates its entity; omitted",
            ))
    variables = [v for v in variables if v.stable_id != entity.stable_id]

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
                "stable_id": var.stable_id,
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
            # study-wrangler's geo check requires latitude to be a number;
            # some EDA studies annotate it as integer.
            eda_type = "number" if var.stable_id == LATITUDE_STABLE_ID else var.data_type
            data_type, data_shape, ordinal_levels, vocabulary_order, warning = (
                normalize_shape(eda_type, var.data_shape, vocabulary)
            )

            if warning is not None and warnings is not None:
                warnings.append(ConversionWarning(
                    entity=entity_name,
                    variable=var.stable_id,
                    message=warning,
                ))

            var_entry: dict[str, Any] = {
                "variable": var.stable_id,
                "stable_id": var.stable_id,
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
            if var.unit and data_type not in UNIT_DATA_TYPES:
                if warnings is not None:
                    warnings.append(ConversionWarning(
                        entity=entity_name,
                        variable=var.stable_id,
                        message=(
                            f"unit '{var.unit}' is not allowed on a {data_type}; "
                            "unit dropped"
                        ),
                    ))
            elif var.unit:
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
                delimiter = (multi_value_delimiters or {}).get(
                    var.stable_id, MULTI_VALUE_DELIMITER
                )
                var_entry["multi_value_delimiter"] = delimiter
                if delimiter != MULTI_VALUE_DELIMITER and warnings is not None:
                    warnings.append(ConversionWarning(
                        entity=entity_name,
                        variable=var.stable_id,
                        message=(
                            f"values contain '{MULTI_VALUE_DELIMITER}'; "
                            f"multi_value_delimiter is '{delimiter}'"
                        ),
                    ))
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

    unannotated_geohash_ids = sorted(
        (vid for vid in set(value_ids) - local_stable_ids
         if vid in GEOHASH_PRECISION_BY_STABLE_ID),
        key=GEOHASH_PRECISION_BY_STABLE_ID.__getitem__,
    )
    for geohash_id in unannotated_geohash_ids:
        var_list.append(generate_geohash_entry(geohash_id))
        if warnings is not None:
            warnings.append(ConversionWarning(
                entity=entity_name,
                variable=geohash_id,
                message=(
                    "geohash has values but no attributegraph row; "
                    "written as a hidden geoaggregator variable"
                ),
            ))

    # study-wrangler reads only top-level scalars into the Entity, so the
    # stable_id under _eda_metadata alone would leave it minting ENT_ ids.
    result: dict[str, Any] = {
        "name": entity_name,
        "stable_id": entity.stable_id,
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
        widen_collection_members(entity_name, collection.stable_id, var_list, warnings)

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
    DUMP_INFO_FILENAME = "dump-info.yaml"

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

    def write_dump_info(self, study_stable_id: str, db_config: dict) -> Path:
        """Write dump-info.yaml: converter build, study and source database.

        Kept out of study.yaml, whose top-level keys study-wrangler passes on.
        """
        commit = provenance.converter_commit()
        content = {
            "converter_commit": commit.sha,
            "converter_dirty": commit.dirty,
            "converter_version": provenance.converter_version(),
            "study_stable_id": study_stable_id,
            "dumped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": {
                key: db_config.get(key, default)
                for key, default in DUMP_INFO_DB_KEYS.items()
            },
        }
        path = self.output_dir / self.DUMP_INFO_FILENAME

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
        value_ids: Iterable[str] = (),
        multi_value_delimiters: dict[str, str] | None = None,
    ) -> Path:
        """Write entity-<name>.yaml file."""
        content = generate_entity_yaml(
            entity, variables, ancestors, self.warnings,
            collections, collection_members, value_ids, multi_value_delimiters,
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
        rows: Iterable[Sequence],
        entities_by_id: dict[str, Entity]
    ) -> int:
        """Write entity-<name>.tsv file.

        Args:
            entity: The entity being written
            ancestors: Ordered list of ancestor entities
            columns: Column names from database (entity_id + attribute_ids)
            rows: Data rows from database, consumed once in a single pass
            entities_by_id: Map of stable_id -> Entity for looking up parents

        Returns:
            Number of data rows written.
        """
        entity_name = entity_name_for_stf(entity)
        path = self.output_dir / f"entity-{entity_name}.tsv"

        attribute_ids = value_attribute_ids(columns, ancestors)
        headers = generate_entity_tsv_header(entity, ancestors, attribute_ids)
        repair = self._latitude_repair(entity_name, len(ancestors), columns)

        with open(path, "w", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(headers)

            row_count = 0
            for row in rows:
                # Data now includes ancestor IDs from the DB query
                writer.writerow(repair(row) if repair else row)
                row_count += 1

        return row_count

    def _latitude_repair(self, entity_name: str, id_index: int, columns: list[str]):
        """Row fixer giving latitude 0 to rows with a longitude and no latitude.

        study-wrangler rejects a partial coordinate pair. When all six geohash
        columns are empty too, they are filled from (0, longitude).
        Returns None when the entity lacks a latitude or longitude column.
        """
        position = {c: i for i, c in enumerate(columns)}
        lat_i = position.get(LATITUDE_STABLE_ID)
        lng_i = position.get(LONGITUDE_STABLE_ID)
        if lat_i is None or lng_i is None:
            return None
        geohash_cols = [
            (position[gid], precision)
            for gid, precision in GEOHASH_PRECISION_BY_STABLE_ID.items()
            if gid in position
        ]
        all_geohash_present = len(geohash_cols) == len(GEOHASH_PRECISION_BY_STABLE_ID)

        def is_empty(value) -> bool:
            return value is None or value == ""

        def repair(row: Sequence) -> Sequence:
            longitude = row[lng_i]
            if not is_empty(row[lat_i]) or is_empty(longitude):
                return row
            fixed = list(row)
            fixed[lat_i] = 0
            if all_geohash_present and all(is_empty(row[i]) for i, _ in geohash_cols):
                for i, precision in geohash_cols:
                    fixed[i] = encode_geohash(0, longitude, precision)
            self.warnings.append(ConversionWarning(
                entity=entity_name,
                variable=LATITUDE_STABLE_ID,
                message=(
                    f"latitude missing with longitude {longitude}; set to 0 "
                    f"(row {row[id_index]})"
                ),
            ))
            return fixed

        return repair

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
