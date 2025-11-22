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
    data_type: str | None
    data_shape: str | None
    unit: str | None
    display_order: int | None


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
                        data_type,
                        data_shape,
                        unit,
                        display_order
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
                    data_type=row[5],
                    data_shape=row[6],
                    unit=row[7],
                    display_order=row[8]
                ))

            return variables

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

            # Build pivot query using CASE statements
            pivot_cols = []
            for attr_id in attribute_ids:
                pivot_cols.append(f"""
                    MAX(CASE WHEN av.attribute_stable_id = '{attr_id}'
                        THEN COALESCE(av.string_value, CAST(av.number_value AS VARCHAR(50)), TO_CHAR(av.date_value, 'YYYY-MM-DD'))
                    END) AS "{attr_id}"
                """)

            pivot_sql = ",\n".join(pivot_cols) if pivot_cols else "''"

            # Build ancestor columns and join
            if ancestor_abbrevs:
                ancestors_table = f"eda.ancestors_{study_abbrev}_{entity_abbrev}"
                ancestor_cols = [f"anc.{abbrev}_STABLE_ID" for abbrev in ancestor_abbrevs]
                ancestor_select = ", ".join(ancestor_cols) + ","

                query = f"""
                    SELECT {ancestor_select}
                        av.{entity_id_column},
                        {pivot_sql}
                    FROM {attr_table} av
                    LEFT JOIN {ancestors_table} anc ON av.{entity_id_column} = anc.{entity_id_column}
                    GROUP BY {", ".join(ancestor_cols)}, av.{entity_id_column}
                    ORDER BY av.{entity_id_column}
                """
                columns = [f"{abbrev}_STABLE_ID" for abbrev in ancestor_abbrevs] + [entity_id_column] + attribute_ids
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
