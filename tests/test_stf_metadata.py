"""Tests for STF metadata fidelity: categories, shapes, JSON fields, naming."""

from eda_to_stf.db import Entity, Study, Variable
from eda_to_stf.stf import (
    entity_name_for_stf,
    generate_entity_tsv_header,
    generate_entity_yaml,
    generate_study_yaml,
    normalize_shape,
    parse_json_list,
)


def make_var(**kwargs) -> Variable:
    defaults = dict(
        stable_id="V1", parent_stable_id=None, provider_label=None,
        display_name="V one", definition=None, vocabulary=None,
        display_type=None, hidden=None, display_order=None,
        display_range_min=None, display_range_max=None, range_min=None,
        range_max=None, bin_width_override=None, bin_width_computed=None,
        mean=None, median=None, lower_quartile=None, upper_quartile=None,
        is_temporal=None, is_featured=None, is_merge_key=None, impute_zero=None,
        is_repeated=None, variable_spec_to_impute_zeroes_for=None,
        has_study_dependent_vocabulary=None, weighting_variable_spec=None,
        has_values=True, data_type="string", data_shape="categorical",
        distinct_values_count=None, is_multi_valued=None, unit=None,
        scale=None, precision=None,
    )
    defaults.update(kwargs)
    return Variable(**defaults)


def make_entity(**kwargs) -> Entity:
    defaults = dict(
        stable_id="E1", parent_stable_id=None, study_stable_id="S1",
        display_name="Participant", display_name_plural="Participants",
        description=None, internal_abbrev="Participant",
        has_attribute_collections=False, is_many_to_one_with_parent=False,
        cardinality=10,
    )
    defaults.update(kwargs)
    return Entity(**defaults)


class TestParseJsonList:
    def test_parses_json_array(self):
        assert parse_json_list('["GEMS.txt::country"]') == ["GEMS.txt::country"]

    def test_parses_multi_element_array(self):
        assert parse_json_list('["a","b"]') == ["a", "b"]

    def test_tolerates_whitespace(self):
        assert parse_json_list('[ "everywhere" ]') == ["everywhere"]

    def test_none_returns_none(self):
        assert parse_json_list(None) is None

    def test_empty_string_returns_none(self):
        assert parse_json_list("") is None

    def test_non_json_falls_back_to_single_item(self):
        assert parse_json_list("everywhere") == ["everywhere"]


class TestNormalizeShape:
    """EDA data_shape already encodes ordinal_values and force_string_type."""

    def test_categorical_with_vocabulary_stays_categorical(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "string", "categorical", ["Bangladesh", "Kenya"]
        )
        assert (dt, ds) == ("string", "categorical")
        assert ordinal is None
        assert vocab_order == ["Bangladesh", "Kenya"]
        assert warning is None

    def test_binary_with_vocabulary_stays_binary(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "string", "binary", ["Case", "Control"]
        )
        assert ds == "binary"
        assert ordinal is None
        assert vocab_order == ["Case", "Control"]

    def test_ordinal_keeps_levels_and_data_type(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "integer", "ordinal", ["low", "high"]
        )
        assert (dt, ds) == ("integer", "ordinal")
        assert ordinal == ["low", "high"]
        assert vocab_order is None
        assert warning is None

    def test_continuous_unchanged(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "integer", "continuous", None
        )
        assert (dt, ds) == ("integer", "continuous")
        assert ordinal is None and vocab_order is None and warning is None

    def test_numeric_ordinal_without_vocabulary_demoted_to_continuous(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "integer", "ordinal", None
        )
        assert ds == "continuous"
        assert ordinal is None
        assert warning is not None
        assert "no vocabulary" in warning

    def test_string_ordinal_without_vocabulary_demoted_to_categorical(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "string", "ordinal", None
        )
        assert ds == "categorical"
        assert warning is not None

    def test_number_ordinal_with_vocabulary_demoted_and_levels_dropped(self):
        dt, ds, ordinal, vocab_order, warning = normalize_shape(
            "number", "ordinal", ["1.5", "2.5"]
        )
        assert ds == "continuous"
        assert ordinal is None
        assert vocab_order is None
        assert warning is not None
        assert "number" in warning


class TestCategoryDetection:
    """has_values is the discriminator, not provider_label."""

    def test_variable_without_provider_label_is_still_a_variable(self):
        entity = make_entity()
        var = make_var(
            stable_id="EUPATH_0009251_Bacteria", provider_label=None,
            has_values=True, data_type="number", data_shape="continuous",
        )
        result = generate_entity_yaml(entity, [var], [])
        assert [v["variable"] for v in result["variables"]] == [
            "EUPATH_0009251_Bacteria"
        ]
        assert "categories" not in result

    def test_has_values_false_is_a_category(self):
        entity = make_entity()
        var = make_var(stable_id="EUPATH_0009251", has_values=False,
                       data_type=None, data_shape=None)
        result = generate_entity_yaml(entity, [var], [])
        assert result["variables"] == []
        assert [c["category"] for c in result["categories"]] == ["EUPATH_0009251"]

    def test_category_keeps_hidden(self):
        entity = make_entity()
        var = make_var(stable_id="EUPATH_0009350", has_values=False,
                       hidden='["everywhere"]')
        result = generate_entity_yaml(entity, [var], [])
        assert result["categories"][0]["hidden"] == ["everywhere"]


class TestVariableFields:
    def test_provider_label_is_parsed_not_wrapped(self):
        entity = make_entity()
        var = make_var(provider_label='["GEMS.txt::country"]')
        result = generate_entity_yaml(entity, [var], [])
        assert result["variables"][0]["provider_label"] == ["GEMS.txt::country"]

    def test_hidden_json_array_is_parsed(self):
        entity = make_entity()
        var = make_var(provider_label='["x"]', hidden='["variableTree","map"]')
        result = generate_entity_yaml(entity, [var], [])
        assert result["variables"][0]["hidden"] == ["variableTree", "map"]

    def test_multi_value_delimiter_emitted_when_multi_valued(self):
        entity = make_entity()
        var = make_var(provider_label='["x"]', is_multi_valued=True)
        result = generate_entity_yaml(entity, [var], [])
        assert result["variables"][0]["multi_value_delimiter"] == ";"

    def test_warnings_are_collected(self):
        entity = make_entity()
        var = make_var(provider_label='["x"]', data_type="integer",
                       data_shape="ordinal", vocabulary=None)
        warnings: list = []
        generate_entity_yaml(entity, [var], [], warnings=warnings)
        assert len(warnings) == 1
        assert warnings[0].variable == "V1"
        assert warnings[0].entity == "E1"


class TestEntityNaming:
    """STF names come from stable_id; DB table names still use internal_abbrev."""

    def test_entity_name_is_stable_id(self):
        entity = make_entity(
            stable_id="EUPATH_0000808",
            internal_abbrev="ArthropodSpecimenCollectionProcess",
        )
        assert entity_name_for_stf(entity) == "EUPATH_0000808"

    def test_yaml_name_and_id_columns_use_stable_id(self):
        parent = make_entity(stable_id="EUPATH_0000096", internal_abbrev="Participant")
        child = make_entity(
            stable_id="EUPATH_0000609",
            parent_stable_id="EUPATH_0000096",
            internal_abbrev="Sample",
        )
        result = generate_entity_yaml(child, [], [parent])

        assert result["name"] == "EUPATH_0000609"
        assert [c["id_column"] for c in result["id_columns"]] == [
            "EUPATH_0000096.id",
            "EUPATH_0000609.id",
        ]
        assert [c["entity_name"] for c in result["id_columns"]] == [
            "EUPATH_0000096",
            "EUPATH_0000609",
        ]

    def test_study_yaml_lists_stable_ids(self):
        entities = [
            make_entity(stable_id="EUPATH_0000096", internal_abbrev="Participant"),
            make_entity(stable_id="EUPATH_0000808", internal_abbrev="Arthropod"),
        ]
        study = Study(stable_id="GEMS-1", internal_abbrev="GEMS_1")
        assert generate_study_yaml(study, entities)["entities"] == [
            "EUPATH_0000096",
            "EUPATH_0000808",
        ]

    def test_tsv_header_uses_stable_ids(self):
        parent = make_entity(stable_id="EUPATH_0000096", internal_abbrev="Participant")
        child = make_entity(stable_id="EUPATH_0000609", internal_abbrev="Sample")
        header = generate_entity_tsv_header(child, [parent], ["OBI_0001169"])
        assert header == [
            "EUPATH_0000096.id",
            "EUPATH_0000609.id \\\\ Descriptors",
            "OBI_0001169",
        ]


class TestLoaderCompatibility:
    def test_null_display_name_plural_is_omitted(self):
        entity = make_entity(display_name_plural=None)
        result = generate_entity_yaml(entity, [], [])
        assert "display_name_plural" not in result

    def test_display_name_plural_kept_when_present(self):
        entity = make_entity(display_name_plural="Participants")
        result = generate_entity_yaml(entity, [], [])
        assert result["display_name_plural"] == "Participants"

    def test_parent_category_dropped_when_not_in_this_entity(self):
        entity = make_entity()
        var = make_var(
            stable_id="EUPATH_0000587",
            provider_label='["x"]',
            parent_stable_id="EUPATH_0035127",
        )
        warnings: list = []
        result = generate_entity_yaml(entity, [var], [], warnings=warnings)
        assert "parent_category" not in result["variables"][0]
        assert len(warnings) == 1
        assert "EUPATH_0035127" in warnings[0].message

    def test_parent_category_kept_when_defined_in_this_entity(self):
        entity = make_entity()
        parent = make_var(stable_id="CAT1", has_values=False)
        child = make_var(
            stable_id="V1", provider_label='["x"]', parent_stable_id="CAT1"
        )
        result = generate_entity_yaml(entity, [parent, child], [])
        assert result["variables"][0]["parent_category"] == "CAT1"

    def test_category_parent_also_validated(self):
        entity = make_entity()
        cat = make_var(
            stable_id="CAT1", has_values=False, parent_stable_id="MISSING"
        )
        result = generate_entity_yaml(entity, [cat], [])
        assert "parent_category" not in result["categories"][0]

    def test_entity_parent_dropped_without_warning(self):
        entity = make_entity(stable_id="E1")
        var = make_var(provider_label='["x"]', parent_stable_id="E1")
        warnings: list = []
        result = generate_entity_yaml(entity, [var], [], warnings=warnings)
        assert "parent_category" not in result["variables"][0]
        assert warnings == []
