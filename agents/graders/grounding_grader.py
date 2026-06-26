"""Grader: Grounding Grader (LLM judge: claims vs sources).

For each drafted section, checks every claim against its cited sources and flags
ungrounded sections. Returns failing_section_ids so the router can send ONLY the
failing section(s) to Revise Section (ADR-005).

Output: schemas.grading.GraderVerdict (passed, score, rationale,
failing_section_ids). Rubric: prompts/rubrics/grounding_grader_rubric.md.

Owner: agent-prompt-engineer
"""

# TODO(agent-prompt-engineer): implement grounding grader judge.
