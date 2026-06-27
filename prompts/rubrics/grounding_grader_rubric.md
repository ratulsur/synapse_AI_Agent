# Grounding Grader Rubric

Owner: agent-prompt-engineer
Version: v2

The LLM judge checks each drafted section's claims against the sources THAT
section cited, and emits a `GraderVerdict` with `failing_section_ids`. Grounding
is judged and revised per-section (ADR-005): only failing sections are sent to
Revise Section; grounded sections are left untouched.

## Inputs
- Each `section`: its `section_id`, `heading`, `content` (the drafted prose), and
  the resolved text of its `cited_source_ids`.
- A cited id that does not resolve to a saved source is shown as `[MISSING]`.

## What counts as a claim
A "non-trivial factual claim" is any statement a reader would expect to verify:
facts, figures, dates, named entities, causal/comparative assertions, quotes.
NOT claims: the section's own framing/transition sentences, generic background
that is common knowledge, and explicit hedges ("this report will examine ...").

## Per-section grounding test (ALL must hold to be grounded)
1. Support: every non-trivial factual claim is supported by at least one of the
   section's cited sources. Paraphrase is fine; the meaning must match.
2. No fabricated citations: every id in `cited_source_ids` resolves to a saved
   source. Any `[MISSING]` id is an automatic failure for that section.
3. Fidelity: numbers, dates, names, and quoted text match the source exactly —
   no drift, no rounding that changes meaning, no quotes the source never made.
4. No unsupported extrapolation: conclusions stated as fact must follow from the
   cited evidence, not from outside knowledge the sources do not contain.
5. Quantitative provenance (finance/market claims): any price, percentage,
   high/low, moving-average, or volume figure must trace to a cited Finance
   source AND that source must identify the ticker and the date/period it
   covers. A numeric market claim with no ticker+date-range provenance, or
   whose figure does not match the cited OHLCV summary, fails the section.

A section that has NO citations but makes factual claims is NOT grounded.
A section whose only claims are framing/common-knowledge may pass even with few
citations.

## Output
- `failing_section_ids` = the `section_id` of every section that fails ANY test
  above. Use the exact ids shown in the input.
- `passed = true` ONLY when `failing_section_ids` is empty (all sections grounded).
- `score` = overall grounding quality in [0,1] (fraction of sections grounded,
  adjusted down for severe fabrications).
- `rationale` = 1-3 sentences; for each failing section, name the specific
  unsupported claim or the mismatch found.
- `mutation_action` is unused by this grader — leave it null.

## Examples (judgement sketches)
- Two sections, every claim traceable, all ids resolve -> `passed=true`,
  `failing_section_ids=[]`, score ~0.95.
- Body cites id=ab12 but states a market-size number not present in ab12 ->
  `passed=false`, `failing_section_ids=['body']`, rationale names the number.
- Conclusion cites id=ff99 which shows as `[MISSING]` -> `passed=false`,
  `failing_section_ids=['conclusion']` (fabricated citation).
- Intro is pure framing with no factual claims, no citations -> grounded (not a
  failure).
- Body states "AAPL rose 8.6% over the month" citing a Finance source whose
  summary shows pct_change=+8.6% over period=1mo -> grounded (fidelity pass).
  Body states "+12%" for the same source -> fails (fidelity, figure mismatch).
