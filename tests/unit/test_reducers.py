"""Unit tests for graph/state.py reducer functions.

Covers:
- add_sources_reducer: basic accumulation, dedup by id (left/existing wins),
  subgraph fan-out boundary (same id in both left and right -> no double-count),
  empty right -> left unchanged.
- merge_sections_reducer: newest write wins for same spec_id, parallel writers
  (multiple new spec_ids from right), revise cycle (only failing section updated),
  insertion-order preservation.

Owner: test-eval-agent
"""

import pytest

from graph.state import add_sources_reducer, merge_sections_reducer
from schemas.section import Section
from schemas.source import Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src(url: str, content: str = "", score: float = 0.5) -> Source:
    """Construct a Source with a deterministic id derived from url+content."""
    return Source(title=url, url=url, domain="GENERIC", content=content, score=score)


def _sec(spec_id: str, content: str = "draft", revise_count: int = 0) -> Section:
    """Construct a Section with the given spec_id and content."""
    return Section(spec_id=spec_id, heading=spec_id.capitalize(), content=content,
                   revise_count=revise_count)


# ---------------------------------------------------------------------------
# add_sources_reducer
# ---------------------------------------------------------------------------


class TestAddSourcesReducer:
    def test_empty_right_returns_left_unchanged(self):
        s1 = _src("https://a.com")
        result = add_sources_reducer([s1], [])
        assert result == [s1]

    def test_empty_left_returns_right(self):
        s1 = _src("https://a.com")
        result = add_sources_reducer([], [s1])
        assert result == [s1]

    def test_both_empty_returns_empty(self):
        result = add_sources_reducer([], [])
        assert result == []

    def test_basic_accumulation(self):
        s1 = _src("https://a.com")
        s2 = _src("https://b.com")
        result = add_sources_reducer([s1], [s2])
        assert len(result) == 2
        ids = {s.id for s in result}
        assert s1.id in ids and s2.id in ids

    def test_dedup_by_id_left_wins(self):
        """When the same id appears in both, the left (existing) version is kept."""
        # Both sources have same url+content => same id
        s_left = _src("https://a.com", content="text", score=0.9)
        s_right = _src("https://a.com", content="text", score=0.1)
        # Verify they have the same id
        assert s_left.id == s_right.id
        result = add_sources_reducer([s_left], [s_right])
        assert len(result) == 1
        assert result[0].score == 0.9  # left (existing) score preserved

    def test_no_double_count_across_subgraph_boundary(self):
        """Subgraphs receive the full parent state; same sources must not be duplicated."""
        s1 = _src("https://a.com")
        s2 = _src("https://b.com")
        # Simulating a subgraph that receives [s1, s2] and returns [s1, s2, s3]
        # (s1 and s2 are already in the parent state)
        s3 = _src("https://c.com")
        # Parent state has [s1, s2]; subgraph returns [s1, s2, s3]
        result = add_sources_reducer([s1, s2], [s1, s2, s3])
        assert len(result) == 3  # s1, s2, s3 -- no doubles
        assert s3.id in {s.id for s in result}

    def test_ordering_preserved_left_first_then_new(self):
        """Existing sources come first, new sources appended in their original order."""
        s1 = _src("https://a.com")
        s2 = _src("https://b.com")
        s3 = _src("https://c.com")
        result = add_sources_reducer([s1], [s2, s3])
        assert result[0].id == s1.id
        assert result[1].id == s2.id
        assert result[2].id == s3.id

    def test_multiple_new_sources_all_added(self):
        s1 = _src("https://a.com")
        s2 = _src("https://b.com")
        s3 = _src("https://c.com")
        result = add_sources_reducer([], [s1, s2, s3])
        assert len(result) == 3


# ---------------------------------------------------------------------------
# merge_sections_reducer
# ---------------------------------------------------------------------------


class TestMergeSectionsReducer:
    def test_empty_right_returns_left(self):
        sec_intro = _sec("intro")
        result = merge_sections_reducer([sec_intro], [])
        assert result == [sec_intro]

    def test_empty_left_returns_right(self):
        sec_body = _sec("body")
        result = merge_sections_reducer([], [sec_body])
        assert result == [sec_body]

    def test_both_empty_returns_empty(self):
        result = merge_sections_reducer([], [])
        assert result == []

    def test_newest_write_wins_for_same_spec_id(self):
        """Right overwrites left for the same spec_id (revise cycle)."""
        old = _sec("body", content="old draft", revise_count=0)
        new = _sec("body", content="revised draft", revise_count=1)
        result = merge_sections_reducer([old], [new])
        assert len(result) == 1
        assert result[0].content == "revised draft"
        assert result[0].revise_count == 1

    def test_new_spec_ids_from_right_appended(self):
        """Sections in right with spec_ids not in left are appended."""
        intro = _sec("intro", content="intro text")
        body = _sec("body", content="body text")
        conclusion = _sec("conclusion", content="conclusion text")
        result = merge_sections_reducer([intro], [body, conclusion])
        assert len(result) == 3
        spec_ids = [s.spec_id for s in result]
        assert spec_ids == ["intro", "body", "conclusion"]

    def test_parallel_writers_all_sections_merged(self):
        """Parallel writers each emit one section; all three must be in the result."""
        # The write node creates stubs (all in left); parallel writers fill them (all in right)
        stub_intro = _sec("intro", content="")
        stub_body = _sec("body", content="")
        stub_conclusion = _sec("conclusion", content="")
        drafted_intro = _sec("intro", content="real intro")
        drafted_body = _sec("body", content="real body")
        drafted_conclusion = _sec("conclusion", content="real conclusion")
        result = merge_sections_reducer(
            [stub_intro, stub_body, stub_conclusion],
            [drafted_intro, drafted_body, drafted_conclusion],
        )
        assert len(result) == 3
        by_id = {s.spec_id: s for s in result}
        assert by_id["intro"].content == "real intro"
        assert by_id["body"].content == "real body"
        assert by_id["conclusion"].content == "real conclusion"

    def test_revise_cycle_only_failing_section_updated(self):
        """Only the failing section is in right; other sections remain from left."""
        intro = _sec("intro", content="grounded intro")
        body_old = _sec("body", content="ungrounded body", revise_count=0)
        conclusion = _sec("conclusion", content="grounded conclusion")
        body_revised = _sec("body", content="revised body", revise_count=1)
        result = merge_sections_reducer([intro, body_old, conclusion], [body_revised])
        assert len(result) == 3
        by_id = {s.spec_id: s for s in result}
        assert by_id["intro"].content == "grounded intro"      # unchanged
        assert by_id["body"].content == "revised body"         # updated
        assert by_id["conclusion"].content == "grounded conclusion"  # unchanged

    def test_insertion_order_left_first_then_new_from_right(self):
        """Order: existing sections from left (in their order), new from right appended."""
        s1 = _sec("intro")
        s2 = _sec("body")
        s3 = _sec("conclusion")
        result = merge_sections_reducer([s1, s2], [s3])
        assert [s.spec_id for s in result] == ["intro", "body", "conclusion"]

    def test_merge_idempotent_when_same_sections_in_both(self):
        """Calling with same content in both left and right is idempotent."""
        s = _sec("intro", content="same")
        result = merge_sections_reducer([s], [s])
        assert len(result) == 1
        assert result[0].content == "same"
