"""Each multi-valued variable is joined with a delimiter none of its values contain."""

import pytest

from eda_to_stf.db import delimiter_conflicts_sql, pivot_column_sql
from eda_to_stf.stf import (
    MULTI_VALUE_DELIMITER_CANDIDATES,
    choose_multi_value_delimiter,
    generate_entity_yaml,
)

from .test_stf_metadata import make_entity, make_var


class TestChooseMultiValueDelimiter:
    def test_semicolon_when_no_value_contains_it(self):
        assert choose_multi_value_delimiter("E1", "V1", set()) == ";"

    def test_next_free_candidate_when_values_contain_semicolon(self):
        assert choose_multi_value_delimiter("E1", "V1", {";"}) == "|"

    def test_skips_every_taken_candidate(self):
        assert choose_multi_value_delimiter("E1", "V1", {";", "|"}) == "~"
        assert choose_multi_value_delimiter("E1", "V1", {";", "|", "~"}) == "^"

    def test_no_free_candidate_raises_naming_entity_variable_and_candidates(self):
        with pytest.raises(ValueError) as excinfo:
            choose_multi_value_delimiter("Participant", "EUPATH_1", set(";|~^"))
        message = str(excinfo.value)
        assert "Participant" in message
        assert "EUPATH_1" in message
        for candidate in MULTI_VALUE_DELIMITER_CANDIDATES:
            assert candidate in message


def multi_valued_entry(delimiters, warnings):
    content = generate_entity_yaml(
        make_entity(),
        [make_var(stable_id="MV", is_multi_valued=True)],
        [],
        warnings,
        value_ids=["MV"],
        multi_value_delimiters=delimiters,
    )
    return next(v for v in content["variables"] if v["variable"] == "MV")


class TestYamlDelimiter:
    def test_default_is_semicolon_without_warning(self):
        warnings = []
        assert multi_valued_entry({}, warnings)["multi_value_delimiter"] == ";"
        assert warnings == []

    def test_yaml_carries_chosen_delimiter_and_warns(self):
        warnings = []
        assert multi_valued_entry({"MV": "|"}, warnings)["multi_value_delimiter"] == "|"
        assert len(warnings) == 1
        assert warnings[0].variable == "MV"
        assert "'|'" in warnings[0].message

    def test_single_valued_variable_gets_no_delimiter(self):
        content = generate_entity_yaml(
            make_entity(),
            [make_var(stable_id="SV", is_multi_valued=False)],
            [],
            value_ids=["SV"],
            multi_value_delimiters={"SV": "|"},
        )
        assert "multi_value_delimiter" not in content["variables"][0]


class TestSql:
    @pytest.mark.parametrize(
        "db_type,agg", [("oracle", "LISTAGG"), ("postgres", "STRING_AGG")]
    )
    def test_pivot_column_joins_with_given_delimiter(self, db_type, agg):
        sql = pivot_column_sql("ATTR_1", db_type, "|")
        assert agg in sql
        assert "'|'" in sql
        assert "';'" not in sql

    def test_conflicts_query_checks_every_candidate(self):
        sql = delimiter_conflicts_sql(
            "eda.attributevalue_S_E", MULTI_VALUE_DELIMITER_CANDIDATES
        )
        for candidate in MULTI_VALUE_DELIMITER_CANDIDATES:
            assert f"'%{candidate}%'" in sql
        assert "string_value" in sql
