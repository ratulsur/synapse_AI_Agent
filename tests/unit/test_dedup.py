"""Unit tests for tools/processing/dedup.py.

Covers:
- No duplicates: all incoming returned unchanged.
- Id-based dedup: same Source.id in incoming -> dropped (first-seen wins).
- URL-based dedup: same normalized URL in incoming -> dropped (id may differ).
- URL normalization: trailing slash stripped, lowercase scheme/host, fragment stripped.
- Empty existing -> all incoming returned.
- Empty incoming -> existing returned unchanged (as a copy).
- Mixed: some duplicates, some new; ordering: existing first, new appended in order.
- Dedup across heterogeneous tool sources (tools returning same page via slightly
  different URLs but same id).

Owner: test-eval-agent
"""

import pytest

from schemas.source import Source
from tools.processing.dedup import dedup, _norm_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _src(url: str, content: str = "", score: float = 0.5, explicit_id: str | None = None) -> Source:
    """Build a Source; if explicit_id provided, bypass auto-hash."""
    if explicit_id:
        return Source(id=explicit_id, title=url, url=url, domain="GENERIC", content=content, score=score)
    return Source(title=url, url=url, domain="GENERIC", content=content, score=score)


# ---------------------------------------------------------------------------
# _norm_url helper
# ---------------------------------------------------------------------------


class TestNormUrl:
    def test_lowercase(self):
        assert _norm_url("HTTPS://Example.COM/path") == "https://example.com/path"

    def test_trailing_slash_stripped(self):
        assert _norm_url("https://a.com/page/") == "https://a.com/page"

    def test_fragment_stripped(self):
        assert _norm_url("https://a.com/page#section") == "https://a.com/page"

    def test_empty_string(self):
        assert _norm_url("") == ""

    def test_no_change_needed(self):
        assert _norm_url("https://a.com/page") == "https://a.com/page"


# ---------------------------------------------------------------------------
# dedup() -- basic contract
# ---------------------------------------------------------------------------


class TestDedup:
    def test_empty_incoming_returns_copy_of_existing(self):
        s1 = _src("https://a.com")
        result = dedup([s1], [])
        assert len(result) == 1
        assert result[0].id == s1.id
        # Returned list is a new object (not the same list)
        result.append(_src("https://extra.com"))
        assert len(dedup([s1], [])) == 1  # original call unaffected

    def test_empty_existing_returns_all_incoming(self):
        s1 = _src("https://a.com")
        s2 = _src("https://b.com")
        result = dedup([], [s1, s2])
        assert len(result) == 2

    def test_both_empty_returns_empty(self):
        assert dedup([], []) == []

    def test_no_duplicates_all_incoming_returned(self):
        e1 = _src("https://e.com")
        i1 = _src("https://a.com")
        i2 = _src("https://b.com")
        result = dedup([e1], [i1, i2])
        assert len(result) == 3

    def test_ordering_existing_first_then_new(self):
        e1 = _src("https://e.com")
        i1 = _src("https://a.com")
        i2 = _src("https://b.com")
        result = dedup([e1], [i1, i2])
        assert result[0].url == "https://e.com"
        assert result[1].url == "https://a.com"
        assert result[2].url == "https://b.com"


# ---------------------------------------------------------------------------
# Id-based dedup
# ---------------------------------------------------------------------------


class TestIdBasedDedup:
    def test_same_id_in_incoming_dropped(self):
        """Sources with ids already in existing are dropped."""
        s = _src("https://a.com", content="same")
        # Same url+content => same id
        s_dup = _src("https://a.com", content="same")
        assert s.id == s_dup.id
        result = dedup([s], [s_dup])
        assert len(result) == 1

    def test_first_seen_wins(self):
        """When incoming has a duplicate id, the existing version is retained."""
        s_existing = _src("https://a.com", content="text", score=0.9)
        s_incoming = _src("https://a.com", content="text", score=0.1)
        assert s_existing.id == s_incoming.id
        result = dedup([s_existing], [s_incoming])
        assert result[0].score == pytest.approx(0.9)  # existing score kept

    def test_multiple_id_dupes_all_dropped(self):
        s1 = _src("https://a.com", content="alpha")
        s2 = _src("https://b.com", content="beta")
        s3 = _src("https://c.com", content="gamma")
        # incoming has duplicates of s1 and s2, plus a new s4
        s1_dup = _src("https://a.com", content="alpha")
        s2_dup = _src("https://b.com", content="beta")
        s4 = _src("https://d.com")
        result = dedup([s1, s2, s3], [s1_dup, s2_dup, s4])
        assert len(result) == 4  # s1, s2, s3 + new s4


# ---------------------------------------------------------------------------
# URL-based dedup (catches cross-tool same-page duplication)
# ---------------------------------------------------------------------------


class TestUrlBasedDedup:
    def test_same_url_different_id_dropped(self):
        """Even if ids differ, matching URL means the incoming is dropped."""
        e = _src("https://a.com", content="first snippet")
        # Same URL but different content -> different id, but same URL -> should be dropped
        i = _src("https://a.com", content="second snippet different")
        # Verify ids differ (different content)
        assert e.id != i.id
        result = dedup([e], [i])
        assert len(result) == 1
        assert result[0].id == e.id  # existing kept

    def test_url_normalization_trailing_slash(self):
        """URLs differing only by trailing slash are treated as equal."""
        e = _src("https://a.com/page/")
        # Create incoming with URL without trailing slash but same content
        i = Source(
            title="T", url="https://a.com/page", domain="GENERIC",
            content=e.content,  # different content so different id
        )
        # Force different content to ensure different id
        i = Source(title="T", url="https://a.com/page", domain="GENERIC", content="diff")
        result = dedup([e], [i])
        # URLs normalize to same -> incoming dropped
        assert len(result) == 1

    def test_url_normalization_case(self):
        """URLs differing only by case are treated as equal."""
        e = _src("https://EXAMPLE.COM/page")
        i = Source(title="T", url="https://example.com/page", domain="GENERIC", content="other")
        result = dedup([e], [i])
        assert len(result) == 1

    def test_url_fragment_ignored(self):
        """Fragment (#section) is stripped before URL comparison."""
        e = _src("https://a.com/page")
        i = Source(title="T", url="https://a.com/page#intro", domain="GENERIC", content="other")
        result = dedup([e], [i])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Mixed scenarios (heterogeneous tool sources)
# ---------------------------------------------------------------------------


class TestMixedDedup:
    def test_heterogeneous_tools_same_page_deduped(self):
        """Web search and wiki both return the same page -> only first kept."""
        from_web = Source(
            title="Wikipedia: Python",
            url="https://en.wikipedia.org/wiki/Python",
            domain="Techno",
            content="Python programming language...",
            tool="web",
        )
        from_wiki = Source(
            title="Python - Wikipedia",
            url="https://en.wikipedia.org/wiki/Python",
            domain="Techno",
            content="Python (programming language)...",  # different content -> different id
            tool="wiki",
        )
        # ids differ (different content) but URL matches -> incoming from_wiki dropped
        assert from_web.id != from_wiki.id
        result = dedup([from_web], [from_wiki])
        assert len(result) == 1
        assert result[0].tool == "web"  # first-seen (existing) kept

    def test_partial_overlap_keeps_all_unique(self):
        s1 = _src("https://a.com", content="a")
        s2 = _src("https://b.com", content="b")
        s3 = _src("https://c.com", content="c")
        s4 = _src("https://d.com", content="d")
        s1_dup = _src("https://a.com", content="a")
        result = dedup([s1, s2], [s1_dup, s3, s4])
        assert len(result) == 4
        urls = {s.url for s in result}
        assert "https://a.com" in urls
        assert "https://b.com" in urls
        assert "https://c.com" in urls
        assert "https://d.com" in urls
