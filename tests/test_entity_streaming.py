"""Entity rows stream from the cursor to the TSV without being materialised."""

import csv

import pytest

from eda_to_stf.db import ENTITY_ROW_BATCH_SIZE, Entity, stream_rows
from eda_to_stf.stf import StfWriter, entity_name_for_stf


class FakeResult:
    """A cursor result that serves its rows in batches, once."""

    def __init__(self, batches):
        self._batches = batches
        self.batches_served = 0
        self.requested_size = None
        self._consumed = False

    def partitions(self, size):
        if self._consumed:
            raise AssertionError("result consumed twice")
        self._consumed = True
        self.requested_size = size
        for batch in self._batches:
            self.batches_served += 1
            yield batch


def make_entity() -> Entity:
    return Entity(
        stable_id="E1",
        parent_stable_id=None,
        study_stable_id="S1",
        display_name="Participant",
        display_name_plural="Participants",
        description=None,
        internal_abbrev="Participant",
        has_attribute_collections=False,
        is_many_to_one_with_parent=False,
        cardinality=None,
    )


BATCHES = [
    [("P1", "a", "1"), ("P2", "b", "2")],
    [("P3", "c;d", "3")],
    [("P4", None, "4")],
]


def test_stream_rows_pulls_one_batch_at_a_time():
    result = FakeResult(BATCHES)
    rows = stream_rows(result)

    assert result.batches_served == 0
    next(rows)
    next(rows)
    assert result.batches_served == 1
    next(rows)
    assert result.batches_served == 2
    assert result.requested_size == ENTITY_ROW_BATCH_SIZE


def test_writer_consumes_a_single_pass_stream(tmp_path):
    result = FakeResult(BATCHES)
    entity = make_entity()
    writer = StfWriter(tmp_path)

    count = writer.write_entity_tsv(
        entity,
        [],
        ["Participant_STABLE_ID", "V1", "V2"],
        stream_rows(result),
        {"E1": entity},
    )

    assert count == 4
    assert result.batches_served == 3
    tsv = tmp_path / f"entity-{entity_name_for_stf(entity)}.tsv"
    with open(tsv, newline="") as f:
        lines = list(csv.reader(f, delimiter="\t"))
    assert lines[1:] == [
        ["P1", "a", "1"],
        ["P2", "b", "2"],
        ["P3", "c;d", "3"],
        ["P4", "", "4"],
    ]
    with pytest.raises(AssertionError, match="consumed twice"):
        next(stream_rows(result))
