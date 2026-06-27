"""Unit tests for schemas/*.py typed contracts.

Covers:
- Source.id content-hashing: deterministic, same url+content -> same hash; different -> different.
- Source.id auto-computation when not explicitly provided.
- Source.score clamping enforced by pydantic ge/le constraints.
- Section status literals and lifecycle fields.
- ReportPlan.sorted_sections() sort correctness.
- RouteLabel.is_valid() for valid and invalid domains.
- DOMAINS list completeness.
- GraderVerdict with mutation_action and failing_section_ids.
- AnalystPersona defaults.

Owner: test-eval-agent
"""

import hashlib

import pytest
from pydantic import ValidationError

from schemas.analyst import AnalystPersona
from schemas.grading import GraderVerdict, MutationAction
from schemas.plan import ReportPlan, SectionSpec
from schemas.routing import DOMAINS, GENERIC_DOMAIN, RouteLabel
from schemas.section import Section
from schemas.source import Source


# ---------------------------------------------------------------------------
# Source.id hashing
# ---------------------------------------------------------------------------


class TestSourceId:
    def test_id_auto_computed_when_empty(self):
        """id is populated even when not provided."""
        src = Source(title="T", url="https://example.com", domain="GENERIC")
        assert src.id != ""
        assert len(src.id) == 16  # sha256 hex[:16]

    def test_id_deterministic_same_url_content(self):
        """Two sources with identical url+content get identical ids."""
        kwargs = dict(title="T", url="https://example.com", domain="GENERIC", content="hello")
        s1 = Source(**kwargs)
        s2 = Source(**kwargs)
        assert s1.id == s2.id

    def test_id_differs_on_different_url(self):
        """Different url -> different id."""
        s1 = Source(title="T", url="https://a.com", domain="GENERIC", content="x")
        s2 = Source(title="T", url="https://b.com", domain="GENERIC", content="x")
        assert s1.id != s2.id

    def test_id_differs_on_different_content(self):
        """Different content -> different id (url same)."""
        s1 = Source(title="T", url="https://a.com", domain="GENERIC", content="alpha")
        s2 = Source(title="T", url="https://a.com", domain="GENERIC", content="beta")
        assert s1.id != s2.id

    def test_id_explicit_value_respected(self):
        """Explicitly provided id is kept as-is (no re-computation)."""
        src = Source(id="custom-id-42", title="T", url="https://x.com", domain="GENERIC")
        assert src.id == "custom-id-42"

    def test_id_hash_matches_expected_formula(self):
        """Verify the hash formula: sha256(url::content[:512])[:16]."""
        url = "https://example.com"
        content = "some content"
        expected = hashlib.sha256(f"{url}::{content[:512]}".encode()).hexdigest()[:16]
        src = Source(title="T", url=url, domain="GENERIC", content=content)
        assert src.id == expected

    def test_id_content_truncated_at_512(self):
        """Only the first 512 chars of content are used in the hash."""
        content_short = "x" * 512
        content_long = "x" * 512 + "extra_ignored_chars"
        s1 = Source(title="T", url="https://a.com", domain="GENERIC", content=content_short)
        s2 = Source(title="T", url="https://a.com", domain="GENERIC", content=content_long)
        assert s1.id == s2.id  # extra chars after 512 are ignored in hash


# ---------------------------------------------------------------------------
# Source.score clamping
# ---------------------------------------------------------------------------


class TestSourceScore:
    def test_score_defaults_to_zero(self):
        src = Source(title="T", url="https://a.com", domain="GENERIC")
        assert src.score == 0.0

    def test_score_accepts_valid_values(self):
        for v in [0.0, 0.5, 1.0]:
            src = Source(title="T", url="https://a.com", domain="GENERIC", score=v)
            assert src.score == v

    def test_score_rejects_above_one(self):
        with pytest.raises(ValidationError):
            Source(title="T", url="https://a.com", domain="GENERIC", score=1.1)

    def test_score_rejects_below_zero(self):
        with pytest.raises(ValidationError):
            Source(title="T", url="https://a.com", domain="GENERIC", score=-0.1)


# ---------------------------------------------------------------------------
# Section lifecycle
# ---------------------------------------------------------------------------


class TestSection:
    def test_default_status_is_pending(self):
        sec = Section(spec_id="intro", heading="Introduction")
        assert sec.status == "pending"
        assert sec.grounded is False
        assert sec.revise_count == 0
        assert sec.content == ""
        assert sec.cited_source_ids == []

    def test_valid_status_values(self):
        for status in ("pending", "drafted", "grounded", "revising"):
            sec = Section(spec_id="s", heading="H", status=status)
            assert sec.status == status

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            Section(spec_id="s", heading="H", status="unknown")

    def test_grounded_field(self):
        sec = Section(spec_id="body", heading="Body", grounded=True, status="grounded")
        assert sec.grounded is True

    def test_revise_count_increments(self):
        sec = Section(spec_id="conclusion", heading="Conclusion", revise_count=3)
        assert sec.revise_count == 3


# ---------------------------------------------------------------------------
# ReportPlan
# ---------------------------------------------------------------------------


class TestReportPlan:
    def _make_plan(self) -> ReportPlan:
        return ReportPlan(
            audience="technical",
            length="long",
            tone="formal",
            sections=[
                SectionSpec(id="conclusion", heading="Conclusion", order=2),
                SectionSpec(id="intro", heading="Introduction", order=0),
                SectionSpec(id="body", heading="Body", order=1),
            ],
        )

    def test_sorted_sections_returns_in_order(self):
        plan = self._make_plan()
        sorted_secs = plan.sorted_sections()
        assert [s.id for s in sorted_secs] == ["intro", "body", "conclusion"]

    def test_sorted_sections_stable_on_equal_order(self):
        plan = ReportPlan(
            sections=[
                SectionSpec(id="a", heading="A", order=0),
                SectionSpec(id="b", heading="B", order=0),
            ]
        )
        result = plan.sorted_sections()
        assert len(result) == 2

    def test_defaults(self):
        plan = ReportPlan()
        assert plan.audience == "general"
        assert plan.length == "medium"
        assert plan.tone == "neutral"
        assert plan.sections == []

    def test_section_spec_intent_default(self):
        spec = SectionSpec(id="x", heading="X")
        assert spec.intent == ""
        assert spec.order == 0


# ---------------------------------------------------------------------------
# RouteLabel and DOMAINS
# ---------------------------------------------------------------------------


class TestRoutingSchemas:
    def test_domains_list_contains_expected_values(self):
        for expected in ("Techno", "Education", "Travel", "Art", "Mgmt", "GENERIC"):
            assert expected in DOMAINS

    def test_generic_domain_is_in_domains(self):
        assert GENERIC_DOMAIN in DOMAINS
        assert GENERIC_DOMAIN == "GENERIC"

    def test_route_label_valid_for_all_domains(self):
        for domain in DOMAINS:
            lbl = RouteLabel(domain=domain)
            assert lbl.is_valid() is True

    def test_route_label_invalid_for_unknown_domain(self):
        lbl = RouteLabel(domain="Crypto")
        assert lbl.is_valid() is False

    def test_route_label_confidence_default(self):
        lbl = RouteLabel(domain="GENERIC")
        assert lbl.confidence == 1.0

    def test_route_label_confidence_clamped(self):
        with pytest.raises(ValidationError):
            RouteLabel(domain="GENERIC", confidence=1.5)
        with pytest.raises(ValidationError):
            RouteLabel(domain="GENERIC", confidence=-0.1)


# ---------------------------------------------------------------------------
# GraderVerdict and MutationAction
# ---------------------------------------------------------------------------


class TestGraderVerdict:
    def test_default_fields(self):
        v = GraderVerdict(passed=True)
        assert v.passed is True
        assert v.score == 0.0
        assert v.rationale == ""
        assert v.mutation_action is None
        assert v.failing_section_ids == []

    def test_source_grader_verdict_with_mutation(self):
        v = GraderVerdict(
            passed=False,
            score=0.3,
            rationale="Insufficient evidence",
            mutation_action=MutationAction.REROUTE,
        )
        assert v.mutation_action == MutationAction.REROUTE
        assert v.mutation_action.value == "reroute"

    def test_grounding_grader_verdict_with_failing_ids(self):
        v = GraderVerdict(
            passed=False,
            score=0.4,
            failing_section_ids=["body", "conclusion"],
        )
        assert "body" in v.failing_section_ids
        assert "conclusion" in v.failing_section_ids

    def test_mutation_action_enum_values(self):
        assert MutationAction.REFORMULATE.value == "reformulate"
        assert MutationAction.WIDEN.value == "widen"
        assert MutationAction.REROUTE.value == "reroute"

    def test_score_bounds(self):
        with pytest.raises(ValidationError):
            GraderVerdict(passed=True, score=1.1)
        with pytest.raises(ValidationError):
            GraderVerdict(passed=True, score=-0.1)


# ---------------------------------------------------------------------------
# AnalystPersona
# ---------------------------------------------------------------------------


class TestAnalystPersona:
    def test_defaults(self):
        p = AnalystPersona()
        assert p.expertise == "generalist"
        assert p.voice == "neutral"
        assert p.stance == "objective"

    def test_custom_values(self):
        p = AnalystPersona(
            expertise="AI/ML researcher",
            voice="authoritative but accessible",
            stance="evidence-first",
        )
        assert p.expertise == "AI/ML researcher"
        assert p.voice == "authoritative but accessible"
        assert p.stance == "evidence-first"
