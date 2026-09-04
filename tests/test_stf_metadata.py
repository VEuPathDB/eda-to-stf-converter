"""Tests for STF metadata fidelity: categories, shapes, JSON fields, naming."""

from eda_to_stf.db import Collection, Entity, Study, Variable
from eda_to_stf.stf import (
    entity_name_for_stf,
    generate_entity_tsv_header,
    generate_entity_yaml,
    generate_study_yaml,
    normalize_shape,
    StfWriter,
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


def make_collection(**kwargs) -> Collection:
    defaults = dict(
        stable_id="EUPATH_0009251",
        display_name="Kingdom",
        num_members=18,
        member="taxon",
        member_plural="taxa",
        is_proportion=True,
        is_compositional=True,
        impute_zero=False,
        normalization_method="sumToUnity",
        display_range_min=None,
        display_range_max=None,
    )
    defaults.update(kwargs)
    return Collection(**defaults)


class TestCollections:
    def test_collection_is_emitted_against_its_category(self):
        entity = make_entity()
        category = make_var(stable_id="EUPATH_0009251", has_values=False)
        member = make_var(
            stable_id="EUPATH_0009251_Bacteria",
            parent_stable_id="EUPATH_0009251",
            data_type="number",
            data_shape="continuous",
        )
        result = generate_entity_yaml(
            entity, [category, member], [], collections=[make_collection()]
        )

        assert len(result["collections"]) == 1
        collection = result["collections"][0]
        assert collection["category"] == "EUPATH_0009251"
        assert collection["stable_id"] == "EUPATH_0009251"
        assert collection["display_name"] == "Kingdom"
        assert collection["member"] == "taxon"
        assert collection["member_plural"] == "taxa"
        assert collection["is_proportion"] is True
        assert collection["is_compositional"] is True
        assert collection["impute_zero"] is False
        assert collection["normalization_method"] == "sumToUnity"

    def test_no_collections_key_when_none(self):
        entity = make_entity()
        result = generate_entity_yaml(entity, [], [], collections=[])
        assert "collections" not in result

    def test_literal_null_normalization_method_is_omitted(self):
        entity = make_entity()
        category = make_var(stable_id="EUPATH_0009251", has_values=False)
        result = generate_entity_yaml(
            entity,
            [category],
            [],
            collections=[make_collection(normalization_method="NULL")],
        )
        assert "normalization_method" not in result["collections"][0]

    def test_empty_normalization_method_is_omitted(self):
        entity = make_entity()
        category = make_var(stable_id="EUPATH_0009251", has_values=False)
        result = generate_entity_yaml(
            entity,
            [category],
            [],
            collections=[make_collection(normalization_method=None)],
        )
        assert "normalization_method" not in result["collections"][0]

    def test_display_ranges_kept_when_set(self):
        entity = make_entity()
        category = make_var(stable_id="EUPATH_0009251", has_values=False)
        result = generate_entity_yaml(
            entity,
            [category],
            [],
            collections=[make_collection(display_range_min="0", display_range_max="1")],
        )
        assert result["collections"][0]["display_range_min"] == "0"
        assert result["collections"][0]["display_range_max"] == "1"

    def test_collection_without_a_category_is_dropped_and_logged(self):
        entity = make_entity()
        warnings: list = []
        result = generate_entity_yaml(
            entity, [], [], collections=[make_collection()], warnings=warnings
        )
        assert "collections" not in result
        assert len(warnings) == 1
        assert warnings[0].variable == "EUPATH_0009251"
        assert "no matching variable category" in warnings[0].message


class TestYamlBooleanTrap:
    """R's YAML 1.1 parser reads bare Y/N/yes/no/on/off as logicals."""

    def test_risky_strings_are_quoted(self, tmp_path):
        entity = make_entity()
        var = make_var(
            provider_label='["x"]',
            data_shape="categorical",
            vocabulary='["Y", "N"]',
        )
        writer = StfWriter(tmp_path)
        path = writer.write_entity_yaml(entity, [var], [])
        text = path.read_text()

        assert "- 'Y'" in text
        assert "- 'N'" in text
        assert "\n  - Y\n" not in text

    def test_round_trips_as_strings(self, tmp_path):
        entity = make_entity()
        var = make_var(
            provider_label='["x"]',
            data_shape="categorical",
            vocabulary='["Y", "no", "off", "TRUE"]',
        )
        writer = StfWriter(tmp_path)
        path = writer.write_entity_yaml(entity, [var], [])

        import yaml as pyyaml
        loaded = pyyaml.safe_load(path.read_text())
        assert loaded["variables"][0]["vocabulary_order"] == ["Y", "no", "off", "TRUE"]

    def test_ordinary_strings_are_not_quoted(self, tmp_path):
        entity = make_entity()
        var = make_var(provider_label='["x"]', display_name="Country")
        writer = StfWriter(tmp_path)
        path = writer.write_entity_yaml(entity, [var], [])
        assert "display_name: Country" in path.read_text()


class TestCollectionMembership:
    """STF expresses membership only as parent_category, so EDA's explicit
    membership table must be checked to agree rather than assumed to."""

    def _entity_with_members(self, member_ids):
        category = make_var(stable_id="EUPATH_0009251", has_values=False)
        members = [
            make_var(stable_id=m, parent_stable_id="EUPATH_0009251",
                     data_type="number", data_shape="continuous")
            for m in member_ids
        ]
        return make_entity(), [category, *members]

    def test_agreeing_membership_produces_no_warning(self):
        entity, variables = self._entity_with_members(["A", "B"])
        warnings: list = []
        generate_entity_yaml(
            entity, variables, [],
            warnings=warnings,
            collections=[make_collection()],
            collection_members={"EUPATH_0009251": {"A", "B"}},
        )
        assert warnings == []

    def test_member_missing_from_parent_links_is_reported(self):
        entity, variables = self._entity_with_members(["A"])
        warnings: list = []
        generate_entity_yaml(
            entity, variables, [],
            warnings=warnings,
            collections=[make_collection()],
            collection_members={"EUPATH_0009251": {"A", "B"}},
        )
        assert len(warnings) == 1
        assert "B" in warnings[0].message

    def test_extra_member_from_parent_links_is_reported(self):
        entity, variables = self._entity_with_members(["A", "B"])
        warnings: list = []
        generate_entity_yaml(
            entity, variables, [],
            warnings=warnings,
            collections=[make_collection()],
            collection_members={"EUPATH_0009251": {"A"}},
        )
        assert len(warnings) == 1
        assert "B" in warnings[0].message

    def test_collection_still_emitted_when_membership_diverges(self):
        entity, variables = self._entity_with_members(["A"])
        result = generate_entity_yaml(
            entity, variables, [],
            collections=[make_collection()],
            collection_members={"EUPATH_0009251": {"A", "B"}},
        )
        assert len(result["collections"]) == 1

    def test_no_check_when_membership_unavailable(self):
        entity, variables = self._entity_with_members(["A"])
        warnings: list = []
        generate_entity_yaml(
            entity, variables, [],
            warnings=warnings,
            collections=[make_collection()],
            collection_members=None,
        )
        assert warnings == []
