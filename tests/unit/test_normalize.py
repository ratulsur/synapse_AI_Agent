"""Unit tests for tools/processing/normalize.py.

Covers:
- Basic hit dict -> Source field mapping (title, url, content, domain, tool, score).
- HTML stripping in content field.
- Score clamping: values > 1.0 -> 1.0, < 0.0 -> 0.0.
- Author extraction: string, list, None.
- Alternative field names: href/link for url; body/snippet/summary/extract for content.
- '_tool' field in hit dict overrides fallback_tool arg.
- No url + has title -> synthetic deterministic url is created.
- No url + no title -> hit dropped, returns empty list.
- Non-dict in raw_hits -> silently skipped (no crash).
- Empty raw_hits -> empty list.
- Domain field is passed through from the function argument (not from hit).

Owner: test-eval-agent
"""

import pytest

from schemas.source import Source
from tools.processing.normalize import normalize, _strip_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_hit(**overrides) -> dict:
    base = {
        "title": "Test Page",
        "url": "https://example.com/page",
        "content": "Some text content.",
        "score": 0.75,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# normalize() -- happy path
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_basic_hit_produces_one_source(self):
        sources = normalize([_basic_hit()], domain="Techno", tool="web")
        assert len(sources) == 1

    def test_source_fields_mapped_correctly(self):
        sources = normalize(
            [_basic_hit(title="My Title", url="https://a.com", content="My content")],
            domain="Education",
            tool="wiki",
        )
        s = sources[0]
        assert s.title == "My Title"
        assert s.url == "https://a.com"
        assert s.content == "My content"
        assert s.domain == "Education"
        assert s.tool == "wiki"

    def test_domain_from_argument_not_from_hit(self):
        """Domain comes from the function argument, not from any field in the hit."""
        sources = normalize([_basic_hit()], domain="Travel", tool="web")
        assert sources[0].domain == "Travel"

    def test_score_passed_through(self):
        sources = normalize([_basic_hit(score=0.6)], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(0.6)

    def test_empty_raw_hits_returns_empty_list(self):
        assert normalize([], domain="GENERIC", tool="web") == []

    def test_multiple_hits_all_normalized(self):
        hits = [
            _basic_hit(url="https://a.com"),
            _basic_hit(url="https://b.com"),
            _basic_hit(url="https://c.com"),
        ]
        sources = normalize(hits, domain="GENERIC", tool="web")
        assert len(sources) == 3


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------


class TestHtmlStripping:
    def test_html_tags_stripped_from_content(self):
        sources = normalize(
            [_basic_hit(content="<p>Hello <b>world</b></p>")],
            domain="GENERIC",
            tool="web",
        )
        assert sources[0].content == "Hello world"

    def test_nested_html_stripped(self):
        sources = normalize(
            [_basic_hit(content="<div><p><a href='#'>Link</a></p></div>")],
            domain="GENERIC",
            tool="web",
        )
        assert sources[0].content == "Link"

    def test_plain_text_unchanged(self):
        sources = normalize(
            [_basic_hit(content="No HTML here.")],
            domain="GENERIC",
            tool="web",
        )
        assert sources[0].content == "No HTML here."

    def test_strip_html_helper_directly(self):
        assert _strip_html("<p>hello</p>") == "hello"
        assert _strip_html("no tags") == "no tags"
        assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------


class TestScoreClamping:
    def test_score_above_one_clamped_to_one(self):
        sources = normalize([_basic_hit(score=1.5)], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(1.0)

    def test_score_below_zero_clamped_to_zero(self):
        sources = normalize([_basic_hit(score=-0.5)], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(0.0)

    def test_score_zero_preserved(self):
        sources = normalize([_basic_hit(score=0.0)], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(0.0)

    def test_score_one_preserved(self):
        sources = normalize([_basic_hit(score=1.0)], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(1.0)

    def test_non_numeric_score_defaults_to_zero(self):
        sources = normalize([_basic_hit(score="not-a-number")], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(0.0)

    def test_missing_score_defaults_to_zero(self):
        hit = {"title": "T", "url": "https://a.com"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Author extraction
# ---------------------------------------------------------------------------


class TestAuthorExtraction:
    def test_string_author(self):
        sources = normalize([_basic_hit(author="Alice Smith")], domain="GENERIC", tool="web")
        assert sources[0].author == "Alice Smith"

    def test_list_author_joined(self):
        sources = normalize([_basic_hit(author=["Alice", "Bob"])], domain="GENERIC", tool="web")
        assert sources[0].author == "Alice, Bob"

    def test_no_author_is_none(self):
        hit = {"title": "T", "url": "https://a.com"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].author is None

    def test_authors_field_alias(self):
        hit = _basic_hit()
        del hit["title"]
        hit["name"] = "My Name"
        hit["authors"] = "Multiple Authors"
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].author == "Multiple Authors"


# ---------------------------------------------------------------------------
# Alternative field names
# ---------------------------------------------------------------------------


class TestAlternativeFieldNames:
    def test_href_used_for_url(self):
        hit = {"title": "T", "href": "https://via-href.com", "content": "c"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].url == "https://via-href.com"

    def test_link_used_for_url(self):
        hit = {"title": "T", "link": "https://via-link.com", "content": "c"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].url == "https://via-link.com"

    def test_url_preferred_over_href(self):
        hit = {"title": "T", "url": "https://primary.com", "href": "https://secondary.com"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].url == "https://primary.com"

    def test_body_used_for_content(self):
        hit = {"title": "T", "url": "https://a.com", "body": "body text"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert "body text" in sources[0].content

    def test_snippet_used_for_content(self):
        hit = {"title": "T", "url": "https://a.com", "snippet": "snippet text"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert "snippet text" in sources[0].content

    def test_summary_used_for_content(self):
        hit = {"title": "T", "url": "https://a.com", "summary": "summary text"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert "summary text" in sources[0].content

    def test_name_used_for_title(self):
        hit = {"name": "My Name", "url": "https://a.com"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert sources[0].title == "My Name"


# ---------------------------------------------------------------------------
# _tool field override
# ---------------------------------------------------------------------------


class TestToolFieldOverride:
    def test_tool_from_hit_overrides_fallback(self):
        hit = _basic_hit(_tool="arxiv")
        sources = normalize([hit], domain="GENERIC", tool="fallback-tool")
        assert sources[0].tool == "arxiv"

    def test_fallback_tool_used_when_no_tool_in_hit(self):
        sources = normalize([_basic_hit()], domain="GENERIC", tool="fallback-tool")
        assert sources[0].tool == "fallback-tool"


# ---------------------------------------------------------------------------
# Missing url / title
# ---------------------------------------------------------------------------


class TestMissingUrlTitle:
    def test_no_url_with_title_synthesizes_fake_url(self):
        hit = {"title": "My Title Without URL", "content": "some content"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert len(sources) == 1
        assert "synapse-unknown-source" in sources[0].url

    def test_no_url_no_title_hit_is_dropped(self):
        hit = {"content": "some content but no url or title"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert len(sources) == 0

    def test_empty_url_and_title_dropped(self):
        hit = {"url": "", "title": "", "content": "content"}
        sources = normalize([hit], domain="GENERIC", tool="web")
        assert len(sources) == 0


# ---------------------------------------------------------------------------
# Malformed/non-dict hits
# ---------------------------------------------------------------------------


class TestMalformedHits:
    def test_non_dict_hit_skipped(self):
        sources = normalize(["not a dict", 42, None], domain="GENERIC", tool="web")
        assert sources == []

    def test_mixed_valid_and_invalid_hits(self):
        hits = [_basic_hit(url="https://good.com"), "bad", None, _basic_hit(url="https://also-good.com")]
        sources = normalize(hits, domain="GENERIC", tool="web")
        assert len(sources) == 2
