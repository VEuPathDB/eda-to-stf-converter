"""Database access layer for EDA schema using SQLAlchemy."""

import os
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@dataclass
class Study:
    """EDA Study metadata."""
    stable_id: str
    internal_abbrev: str


@dataclass
class Entity:
    """EDA Entity metadata from EntityTypeGraph."""
    stable_id: str
    parent_stable_id: str | None
    study_stable_id: str
    display_name: str
    display_name_plural: str
    description: str | None
    internal_abbrev: str
    has_attribute_collections: bool
    is_many_to_one_with_parent: bool
    cardinality: int | None


@dataclass
class Variable:
    """EDA Variable metadata from attributegraph."""
    stable_id: str
    parent_stable_id: str | None
    provider_label: str | None
    display_name: str | None
    definition: str | None
    vocabulary: str | None  # CLOB field, JSON string
    display_type: str | None
    hidden: str | None
    display_order: int | None
    display_range_min: str | None
    display_range_max: str | None
    range_min: str | None
    range_max: str | None
    bin_width_override: str | None
    bin_width_computed: str | None
    mean: str | None
    median: str | None
    lower_quartile: str | None
    upper_quartile: str | None
    is_temporal: bool | None
    is_featured: bool | None
    is_merge_key: bool | None
    impute_zero: bool | None
    is_repeated: bool | None
    variable_spec_to_impute_zeroes_for: str | None
    has_study_dependent_vocabulary: bool | None
    weighting_variable_spec: str | None
    has_values: bool | None
    data_type: str | None
    data_shape: str | None
    distinct_values_count: int | None
    is_multi_valued: bool | None
    unit: str | None
    scale: str | None
    precision: int | None


@dataclass
class Collection:
    """EDA variable collection, anchored on a variable category."""
    stable_id: str
    display_name: str | None
    num_members: int | None
    member: str | None
    member_plural: str | None
    is_proportion: bool | None
    is_compositional: bool | None
    impute_zero: bool | None
    normalization_method: str | None
    display_range_min: str | None
    display_range_max: str | None


def build_connection_url(config: dict) -> str:
    """Build SQLAlchemy connection URL from config.

    Args:
        config: Database configuration with type, host, port, name, user.
                Password from DB_PASSWORD environment variable.

    Returns:
        SQLAlchemy connection URL string.
    """
    password = os.environ.get("DB_PASSWORD")
    if not password:
        raise ValueError("DB_PASSWORD environment variable not set")

    db_type = config.get("type", "oracle")
    host = config["host"]
    port = config.get("port", 1521 if db_type == "oracle" else 5432)
    name = config["name"]
    user = config["user"]

    if db_type == "oracle":
        # Oracle uses oracledb driver
        return f"oracle+oracledb://{user}:{password}@{host}:{port}/?service_name={name}"
    elif db_type == "postgres":
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    else:
        raise ValueError(f"Unsupported database type: {db_type}")


class EdaDatabase:
    """Database connection and queries for EDA schema."""

    def __init__(self, config: dict):
        """Initialize database connection.

        Args:
            config: Database configuration dict with type, host, port, name, user.
                    Password should be in DB_PASSWORD environment variable.
        """
        self.config = config
        self._engine: Engine | None = None

    def connect(self):
        """Establish database connection."""
        url = build_connection_url(self.config)

        # For Oracle thick mode (required for network encryption)
        if self.config.get("type", "oracle") == "oracle":
            import oracledb
            oracledb.init_oracle_client()

        self._engine = create_engine(url)

    def close(self):
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_study(self, stable_id: str) -> Study:
        """Fetch study metadata by stable_id."""
        with self._engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT stable_id, internal_abbrev
                    FROM eda.study
                    WHERE stable_id = :stable_id
                """),
                {"stable_id": stable_id}
            )

            row = result.fetchone()
            if not row:
                raise ValueError(f"Study not found: {stable_id}")

            return Study(stable_id=row[0], internal_abbrev=row[1])

    def get_entities(self, study_stable_id: str) -> list[Entity]:
        """Fetch all entities for a study from EntityTypeGraph."""
        with self._engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT
                        stable_id,
                        parent_stable_id,
                        study_stable_id,
                        display_name,
                        display_name_plural,
                        description,
                        internal_abbrev,
                        has_attribute_collections,
                        is_many_to_one_with_parent,
                        cardinality
                    FROM eda.entitytypegraph
                    WHERE study_stable_id = :study_stable_id
                    ORDER BY stable_id
                """),
                {"study_stable_id": study_stable_id}
            )

            entities = []
            for row in result.fetchall():
                entities.append(Entity(
                    stable_id=row[0],
                    parent_stable_id=row[1],
                    study_stable_id=row[2],
                    display_name=row[3],
                    display_name_plural=row[4],
                    description=row[5],
                    internal_abbrev=row[6],
                    has_attribute_collections=bool(row[7]),
                    is_many_to_one_with_parent=bool(row[8]),
                    cardinality=row[9]
                ))

            return entities

    def get_variables(self, study_abbrev: str, entity_abbrev: str) -> list[Variable]:
        """Fetch variable metadata from attributegraph table."""
        table_name = f"eda.attributegraph_{study_abbrev}_{entity_abbrev}"

        with self._engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        stable_id,
                        parent_stable_id,
                        provider_label,
                        display_name,
                        definition,
                        vocabulary,
                        display_type,
                        hidden,
                        display_order,
                        display_range_min,
                        display_range_max,
                        range_min,
                        range_max,
                        bin_width_override,
                        bin_width_computed,
                        mean,
                        median,
                        lower_quartile,
                        upper_quartile,
                        is_temporal,
                        is_featured,
                        is_merge_key,
                        impute_zero,
                        is_repeated,
                        variable_spec_to_impute_zeroes_for,
                        has_study_dependent_vocabulary,
                        weighting_variable_spec,
                        has_values,
                        data_type,
                        data_shape,
                        distinct_values_count,
                        is_multi_valued,
                        unit,
                        scale,
                        precision
                    FROM {table_name}
                    ORDER BY display_order NULLS LAST, stable_id
                """)
            )

            variables = []
            for row in result.fetchall():
                variables.append(Variable(
                    stable_id=row[0],
                    parent_stable_id=row[1],
                    provider_label=row[2],
                    display_name=row[3],
                    definition=row[4],
                    vocabulary=row[5],
                    display_type=row[6],
                    hidden=row[7],
                    display_order=row[8],
                    display_range_min=row[9],
                    display_range_max=row[10],
                    range_min=row[11],
                    range_max=row[12],
                    bin_width_override=row[13],
                    bin_width_computed=row[14],
                    mean=row[15],
                    median=row[16],
                    lower_quartile=row[17],
                    upper_quartile=row[18],
                    is_temporal=bool(row[19]) if row[19] is not None else None,
                    is_featured=bool(row[20]) if row[20] is not None else None,
                    is_merge_key=bool(row[21]) if row[21] is not None else None,
                    impute_zero=bool(row[22]) if row[22] is not None else None,
                    is_repeated=bool(row[23]) if row[23] is not None else None,
                    variable_spec_to_impute_zeroes_for=row[24],
                    has_study_dependent_vocabulary=bool(row[25]) if row[25] is not None else None,
                    weighting_variable_spec=row[26],
                    has_values=bool(row[27]) if row[27] is not None else None,
                    data_type=row[28],
                    data_shape=row[29],
                    distinct_values_count=row[30],
                    is_multi_valued=bool(row[31]) if row[31] is not None else None,
                    unit=row[32],
                    scale=row[33],
                    precision=row[34]
                ))

            return variables

    def _table_exists(self, table_name: str) -> bool:
        """Check a dataset-specific table exists.

        entitytypegraph.has_attribute_collections is set for at least one entity
        whose tables were never built, so the flag alone is not enough.
        """
        schema, _, name = table_name.partition(".")

        with self._engine.connect() as conn:
            if self.config.get("type", "oracle") == "oracle":
                result = conn.execute(
                    text("""
                        SELECT 1 FROM all_tables
                        WHERE owner = :owner AND table_name = :table_name
                    """),
                    {"owner": schema.upper(), "table_name": name.upper()},
                )
            else:
                result = conn.execute(
                    text("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = :owner AND table_name = :table_name
                    """),
                    {"owner": schema.lower(), "table_name": name.lower()},
                )

            return result.fetchone() is not None

    def get_collections(
        self, study_abbrev: str, entity_abbrev: str
    ) -> list[Collection]:
        """Fetch variable collections from the entity's collection table."""
        table_name = f"eda.collection_{study_abbrev}_{entity_abbrev}"

        if not self._table_exists(table_name):
            return []

        with self._engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT
                        stable_id,
                        display_name,
                        num_members,
                        member,
                        member_plural,
                        is_proportion,
                        is_compositional,
                        impute_zero,
                        normalization_method,
                        display_range_min,
                        display_range_max
                    FROM {table_name}
                    ORDER BY stable_id
                """)
            )

            return [
                Collection(
                    stable_id=row[0],
                    display_name=row[1],
                    num_members=row[2],
                    member=row[3],
                    member_plural=row[4],
                    is_proportion=bool(row[5]) if row[5] is not None else None,
                    is_compositional=bool(row[6]) if row[6] is not None else None,
                    impute_zero=bool(row[7]) if row[7] is not None else None,
                    normalization_method=row[8],
                    display_range_min=row[9],
                    display_range_max=row[10],
                )
                for row in result.fetchall()
            ]

    def get_collection_members(
        self, study_abbrev: str, entity_abbrev: str
    ) -> dict[str, set[str]] | None:
        """Fetch declared collection membership, keyed by collection stable_id.

        Returns None when the table is absent. STF can only express membership
        as parent_category, so this is read to check that EDA's explicit
        membership agrees rather than to build the output from.
        """
        table_name = f"eda.collectionattribute_{study_abbrev}_{entity_abbrev}"

        if not self._table_exists(table_name):
            return None

        members: dict[str, set[str]] = {}

        with self._engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    SELECT collection_stable_id, attribute_stable_id
                    FROM {table_name}
                """)
            )
            for collection_id, attribute_id in result:
                members.setdefault(collection_id, set()).add(attribute_id)

        return members

    def get_entity_data(
        self,
        study_abbrev: str,
        entity_abbrev: str,
        ancestor_abbrevs: list[str] | None = None,
    ) -> tuple[list[str], list[list]]:
        """Fetch entity data from attributevalue table, pivoted to wide format.

        Args:
            study_abbrev: Study internal abbreviation
            entity_abbrev: Entity internal abbreviation
            ancestor_abbrevs: List of ancestor entity abbreviations (parent first, then grandparent, etc.)

        Returns:
            Tuple of (column_names, rows) where data is pivoted to wide format.
            Columns are: [ancestor_ids..., entity_id, attribute_ids...]
        """
        attr_table = f"eda.attributevalue_{study_abbrev}_{entity_abbrev}"
        entity_id_column = f"{entity_abbrev}_STABLE_ID"

        ancestor_abbrevs = ancestor_abbrevs or []

        with self._engine.connect() as conn:
            # First, get distinct attribute IDs to build pivot columns
            result = conn.execute(
                text(f"""
                    SELECT DISTINCT attribute_stable_id
                    FROM {attr_table}
                    ORDER BY attribute_stable_id
                """)
            )
            attribute_ids = [row[0] for row in result.fetchall()]

            # Determine aggregation function based on database type
            db_type = self.config.get("type", "oracle")
            if db_type == "oracle":
                # Oracle uses LISTAGG
                agg_template = """
                    LISTAGG(CASE WHEN av.attribute_stable_id = '{attr_id}'
                        THEN COALESCE(av.string_value, CAST(av.number_value AS VARCHAR(50)), TO_CHAR(av.date_value, 'YYYY-MM-DD'))
                    END, ';') WITHIN GROUP (ORDER BY COALESCE(av.string_value, CAST(av.number_value AS VARCHAR(50)), TO_CHAR(av.date_value, 'YYYY-MM-DD'))) AS "{attr_id}"
                """
            else:
                # PostgreSQL uses STRING_AGG
                agg_template = """
                    STRING_AGG(CASE WHEN av.attribute_stable_id = '{attr_id}'
                        THEN COALESCE(av.string_value, CAST(av.number_value AS VARCHAR), TO_CHAR(av.date_value, 'YYYY-MM-DD'))
                    END, ';' ORDER BY COALESCE(av.string_value, CAST(av.number_value AS VARCHAR), TO_CHAR(av.date_value, 'YYYY-MM-DD'))) AS "{attr_id}"
                """

            # Build pivot query using CASE statements with aggregation
            pivot_cols = []
            for attr_id in attribute_ids:
                pivot_cols.append(agg_template.format(attr_id=attr_id))

            pivot_sql = ",\n".join(pivot_cols) if pivot_cols else "''"

            # The ancestors table is the authoritative row set: it holds every
            # entity instance, while attributevalue only holds those that have
            # at least one value. Driving from attributevalue silently drops
            # instances and breaks the parent-child join on the way back in.
            ancestors_table = f"eda.ancestors_{study_abbrev}_{entity_abbrev}"
            has_ancestors_table = self._table_exists(ancestors_table)

            if has_ancestors_table:
                ancestor_cols = [f"anc.{abbrev}_STABLE_ID" for abbrev in ancestor_abbrevs]
                ancestor_select = ", ".join(ancestor_cols) + "," if ancestor_cols else ""
                group_by_cols = ancestor_cols + [f"anc.{entity_id_column}"]

                query = f"""
                    SELECT {ancestor_select}
                        anc.{entity_id_column},
                        {pivot_sql}
                    FROM {ancestors_table} anc
                    LEFT JOIN {attr_table} av
                        ON av.{entity_id_column} = anc.{entity_id_column}
                    GROUP BY {", ".join(group_by_cols)}
                    ORDER BY anc.{entity_id_column}
                """
                columns = (
                    [f"{abbrev}_STABLE_ID" for abbrev in ancestor_abbrevs]
                    + [entity_id_column]
                    + attribute_ids
                )
            else:
                query = f"""
                    SELECT av.{entity_id_column},
                        {pivot_sql}
                    FROM {attr_table} av
                    GROUP BY av.{entity_id_column}
                    ORDER BY av.{entity_id_column}
                """
                columns = [entity_id_column] + attribute_ids

            result = conn.execute(text(query))
            rows = [list(row) for row in result.fetchall()]

        return columns, rows
