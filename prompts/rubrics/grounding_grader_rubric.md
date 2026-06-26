# Grounding Grader Rubric

Owner: agent-prompt-engineer

The LLM judge checks each drafted section's claims against the sources that
section cited, and emits a `GraderVerdict` with `failing_section_ids`.

## Inputs
- `sections` (each with `content` + `cited_source_ids`)
- the corresponding `Source[]` content

## Decision (per section)
TODO(agent-prompt-engineer): define grounded criteria, e.g.
- Every non-trivial factual claim is supported by at least one cited source.
- No fabricated citations; cited ids exist in state.
- Numbers/quotes match source text.

## Output
- `passed` = True only when ALL sections are grounded.
- `failing_section_ids` = the sections to send to Revise Section (per-section
  revise loop, ADR-005). Grounded sections are left untouched.

TODO(agent-prompt-engineer): finalize claim-extraction guidance and examples.
