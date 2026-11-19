"""Oracle annotation quirks the converter repairs so the STF validates."""

import csv

from eda_to_stf.stf import (
    StfWriter,
    encode_geohash,
    entity_name_for_stf,
    generate_entity_yaml,
)
from tests.test_stf_metadata import make_collection, make_entity, make_var

LAT = "OBI_0001620"
LNG = "OBI_0001621"
GEOHASH_IDS = [f"EUPATH_004320{n}" for n in range(3, 9)]


def messages(warnings):
    return [(w.variable, w.message) for w in warnings]


class TestCategoryDuplicatingEntity:
    def test_category_with_entity_stable_id_is_omitted(self):
        entity = make_entity(stable_id="OBI_0001624")
        dup = make_var(
            stable_id="OBI_0001624", parent_stable_id="OBI_0000070", has_values=False
        )
        child = make_var(stable_id="V1", parent_stable_id="OBI_0001624")
        warnings: list = []

        result = generate_entity_yaml(entity, [dup, child], [], warnings=warnings)

        assert "categories" not in result
        assert "parent_category" not in result["variables"][0]
        assert messages(warnings) == [
            ("OBI_0001624", "category 'OBI_0001624' duplicates its entity; omitted")
        ]

    def test_variable_with_entity_stable_id_is_omitted(self):
        entity = make_entity(stable_id="E1")
        dup = make_var(stable_id="E1")
        other = make_var(stable_id="V1")
        warnings: list = []

        result = generate_entity_yaml(entity, [dup, other], [], warnings=warnings)

        assert [v["stable_id"] for v in result["variables"]] == ["V1"]
        assert messages(warnings) == [
            ("E1", "category 'E1' duplicates its entity; omitted")
        ]

    def test_ancestor_stable_id_is_not_treated_as_duplicate(self):
        parent = make_entity(stable_id="P1")
        entity = make_entity(stable_id="E1", parent_stable_id="P1")
        cat = make_var(stable_id="P1", has_values=False)

        result = generate_entity_yaml(entity, [cat], [parent])

        assert [c["stable_id"] for c in result["categories"]] == ["P1"]


class TestCollectionTypeWidening:
    def _yaml(self, members, warnings):
        cat = make_var(stable_id="C1", has_values=False)
        return generate_entity_yaml(
            make_entity(),
            [cat, *members],
            [],
            warnings=warnings,
            collections=[make_collection(stable_id="C1")],
        )

    def test_binary_widened_to_categorical(self):
        members = [
            make_var(stable_id="A", parent_stable_id="C1", data_shape="binary"),
            make_var(stable_id="B", parent_stable_id="C1", data_shape="categorical"),
        ]
        warnings: list = []

        result = self._yaml(members, warnings)

        assert [v["data_shape"] for v in result["variables"]] == [
            "categorical",
            "categorical",
        ]
        assert messages(warnings) == [
            (
                "A",
                "data_shape 'binary' widened to 'categorical' to match collection 'C1'",
            )
        ]

    def test_integer_widened_to_number(self):
        members = [
            make_var(
                stable_id="A",
                parent_stable_id="C1",
                data_type="number",
                data_shape="continuous",
            ),
            make_var(
                stable_id="B",
                parent_stable_id="C1",
                data_type="integer",
                data_shape="continuous",
            ),
        ]
        warnings: list = []

        result = self._yaml(members, warnings)

        assert [v["data_type"] for v in result["variables"]] == ["number", "number"]
        assert messages(warnings) == [
            ("B", "data_type 'integer' widened to 'number' to match collection 'C1'")
        ]

    def test_other_mixes_left_for_validation(self):
        members = [
            make_var(
                stable_id="A",
                parent_stable_id="C1",
                data_type="string",
                data_shape="categorical",
            ),
            make_var(
                stable_id="B",
                parent_stable_id="C1",
                data_type="number",
                data_shape="continuous",
            ),
        ]
        warnings: list = []

        result = self._yaml(members, warnings)

        assert [(v["data_type"], v["data_shape"]) for v in result["variables"]] == [
            ("string", "categorical"),
            ("number", "continuous"),
        ]
        assert warnings == []

    def test_variables_outside_the_collection_untouched(self):
        members = [
            make_var(stable_id="A", parent_stable_id="C1", data_shape="binary"),
            make_var(stable_id="B", parent_stable_id="C1", data_shape="binary"),
            make_var(stable_id="X", data_shape="categorical"),
        ]
        warnings: list = []

        result = self._yaml(members, warnings)

        assert [v["data_shape"] for v in result["variables"]] == [
            "binary",
            "binary",
            "categorical",
        ]
        assert warnings == []


class TestUnitOnNonNumeric:
    def test_unit_dropped_on_string(self):
        var = make_var(stable_id="PATO_0000146", unit="degree Celsius")
        warnings: list = []

        result = generate_entity_yaml(make_entity(), [var], [], warnings=warnings)

        assert "unit" not in result["variables"][0]
        assert messages(warnings) == [
            (
                "PATO_0000146",
                "unit 'degree Celsius' is not allowed on a string; unit dropped",
            )
        ]

    def test_unit_kept_on_integer_and_number(self):
        variables = [
            make_var(
                stable_id="A", data_type="integer", data_shape="continuous", unit="u"
            ),
            make_var(
                stable_id="B", data_type="number", data_shape="continuous", unit="u"
            ),
        ]
        warnings: list = []

        result = generate_entity_yaml(make_entity(), variables, [], warnings=warnings)

        assert [v["unit"] for v in result["variables"]] == ["u", "u"]
        assert warnings == []


class TestEncodeGeohash:
    def test_matches_study_wrangler(self):
        # Reference values from study-wrangler's encode_geohash().
        assert encode_geohash(0, 34.6, 6) == "kzbxgr"
        assert encode_geohash(0, -51.1, 6) == "6zgxvp"
        assert encode_geohash(12.5, 34.6, 6) == "sf0x57"
        assert encode_geohash(0, 34.6, 1) == "k"


class TestLongitudeWithoutLatitude:
    def _write(self, tmp_path, columns, rows):
        entity = make_entity()
        writer = StfWriter(tmp_path)
        writer.write_entity_tsv(entity, [], columns, iter(rows), {"E1": entity})
        tsv = tmp_path / f"entity-{entity_name_for_stf(entity)}.tsv"
        with open(tsv, newline="") as f:
            return list(csv.reader(f, delimiter="\t"))[1:], writer.warnings

    def test_latitude_set_to_zero_and_geohash_filled(self, tmp_path):
        columns = ["E1_ID", LAT, LNG, *GEOHASH_IDS]
        rows = [
            ("R1", None, 34.6, None, None, None, None, None, None),
            ("R2", 1.5, 2.5, "s", "s0", "s00", "s000", "s0000", "s00000"),
        ]

        written, warnings = self._write(tmp_path, columns, rows)

        assert written[0] == [
            "R1",
            "0",
            "34.6",
            "k",
            "kz",
            "kzb",
            "kzbx",
            "kzbxg",
            "kzbxgr",
        ]
        assert written[1] == [
            "R2",
            "1.5",
            "2.5",
            "s",
            "s0",
            "s00",
            "s000",
            "s0000",
            "s00000",
        ]
        assert [(w.entity, w.variable, w.message) for w in warnings] == [
            ("E1", LAT, "latitude missing with longitude 34.6; set to 0 (row R1)")
        ]

    def test_existing_geohash_values_kept(self, tmp_path):
        columns = ["E1_ID", LAT, LNG, *GEOHASH_IDS]
        rows = [("R1", "", "-51.1", "a", "", "", "", "", "")]

        written, warnings = self._write(tmp_path, columns, rows)

        assert written[0] == ["R1", "0", "-51.1", "a", "", "", "", "", ""]
        assert len(warnings) == 1

    def test_latitude_without_longitude_left_alone(self, tmp_path):
        columns = ["E1_ID", LAT, LNG]
        rows = [("R1", 12.0, None)]

        written, warnings = self._write(tmp_path, columns, rows)

        assert written[0] == ["R1", "12.0", ""]
        assert warnings == []

    def test_no_latitude_column_left_alone(self, tmp_path):
        columns = ["E1_ID", LNG]
        rows = [("R1", 34.6)]

        written, warnings = self._write(tmp_path, columns, rows)

        assert written[0] == ["R1", "34.6"]
        assert warnings == []
