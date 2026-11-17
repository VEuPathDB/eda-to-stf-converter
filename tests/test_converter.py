"""convert_study passes the value-bearing attribute ids to the entity YAML."""

from contextlib import contextmanager

import yaml

from eda_to_stf.converter import convert_study
from eda_to_stf.db import Entity, Study

from .test_stf_metadata import make_var

DB_CONFIG = {"type": "oracle", "host": "localhost", "port": 1521, "name": "db"}


class FakeDb:
    def __init__(self, columns, rows, variables=(), conflicts=None):
        self.config = DB_CONFIG
        self._columns = columns
        self._rows = rows
        self._variables = list(variables)
        self._conflicts = conflicts or {}
        self.streamed_delimiters = None

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
        return self._variables

    def get_multi_value_delimiter_conflicts(
        self, study_abbrev, entity_abbrev, attribute_ids, candidates
    ):
        return {a: self._conflicts[a] for a in attribute_ids if a in self._conflicts}

    @contextmanager
    def stream_entity_data(
        self,
        study_abbrev,
        entity_abbrev,
        ancestor_abbrevs=None,
        multi_value_delimiters=None,
    ):
        self.streamed_delimiters = multi_value_delimiters
        yield self._columns, iter(self._rows)


def test_unannotated_geohash_column_gets_yaml_entry(tmp_path):
    db = FakeDb(["Coll_STABLE_ID", "EUPATH_0043203"], [("C1", "d")])

    convert_study(db, "STUDY-1", tmp_path)

    with open(tmp_path / "entity-EUPATH_0000096.yaml") as f:
        content = yaml.safe_load(f)
    assert [v["variable"] for v in content["variables"]] == ["EUPATH_0043203"]
    warnings_log = (tmp_path / "conversion-warnings.log").read_text()
    assert "EUPATH_0000096\tEUPATH_0043203\t" in warnings_log


def test_dump_info_written_beside_study_yaml_not_in_it(tmp_path):
    convert_study(FakeDb(["Coll_STABLE_ID"], []), "STUDY-1", tmp_path)

    info = yaml.safe_load((tmp_path / "dump-info.yaml").read_text())
    assert info["study_stable_id"] == "STUDY-1"
    assert info["database"] == DB_CONFIG
    study = yaml.safe_load((tmp_path / "study.yaml").read_text())
    assert not set(info) & set(study)


def test_multi_valued_delimiter_reaches_join_yaml_and_warnings_log(tmp_path):
    db = FakeDb(
        ["Coll_STABLE_ID", "MV_SEMI", "MV_PLAIN"],
        [("C1", "a;|b", "x;y")],
        variables=[
            make_var(stable_id="MV_SEMI", is_multi_valued=True),
            make_var(stable_id="MV_PLAIN", is_multi_valued=True),
        ],
        conflicts={"MV_SEMI": {";"}},
    )

    convert_study(db, "STUDY-1", tmp_path)

    assert db.streamed_delimiters == {"MV_SEMI": "|", "MV_PLAIN": ";"}
    content = yaml.safe_load((tmp_path / "entity-EUPATH_0000096.yaml").read_text())
    delimiters = {
        v["variable"]: v["multi_value_delimiter"] for v in content["variables"]
    }
    assert delimiters == {"MV_SEMI": "|", "MV_PLAIN": ";"}
    log_lines = (tmp_path / "conversion-warnings.log").read_text().splitlines()
    assert [line for line in log_lines if "multi_value_delimiter" in line] == [
        "EUPATH_0000096\tMV_SEMI\tvalues contain ';'; multi_value_delimiter is '|'"
    ]
