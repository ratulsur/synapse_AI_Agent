"""Grader: Source Grader (LLM judge over collected evidence).

Judges whether the accumulated, deduped Source[] is sufficient and relevant to
satisfy the plan. On NO, also selects a MutationAction (reformulate / widen /
reroute) that the retrieval loop applies on its next iteration.

Output: schemas.grading.GraderVerdict (passed, score, rationale, mutation_action).
Rubric: prompts/rubrics/source_grader_rubric.md.

Owner: agent-prompt-engineer
"""

# TODO(agent-prompt-engineer): implement source grader judge.
