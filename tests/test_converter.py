"""convert_study passes the value-bearing attribute ids to the entity YAML."""

from contextlib import contextmanager

import yaml

from eda_to_stf.converter import convert_study
from eda_to_stf.db import Entity, Study


class FakeDb:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows

    def get_study(self, stable_id):
        return Study(stable_id=stable_id, internal_abbrev="S1")

    def get_entities(self, study_stable_id):
        return [
            Entity(
                stable_id="EUPATH_0000096",
                parent_stable_id=None,
                study_stable_id=study_stable_id,
                display_name="Collection",
                display_name_plural="Collections",
                description=None,
                internal_abbrev="Coll",
                has_attribute_collections=False,
                is_many_to_one_with_parent=False,
                cardinality=1,
            )
        ]

    def get_variables(self, study_abbrev, entity_abbrev):
        return []

    @contextmanager
    def stream_entity_data(self, study_abbrev, entity_abbrev, ancestor_abbrevs=None):
        yield self._columns, iter(self._rows)


def test_unannotated_geohash_column_gets_yaml_entry(tmp_path):
    db = FakeDb(["Coll_STABLE_ID", "EUPATH_0043203"], [("C1", "d")])

    convert_study(db, "STUDY-1", tmp_path)

    with open(tmp_path / "entity-EUPATH_0000096.yaml") as f:
        content = yaml.safe_load(f)
    assert [v["variable"] for v in content["variables"]] == ["EUPATH_0043203"]
    warnings_log = (tmp_path / "conversion-warnings.log").read_text()
    assert "EUPATH_0000096\tEUPATH_0043203\t" in warnings_log
