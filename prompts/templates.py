"""Central registry of prompt templates (one per agent role).

Intended exports (ChatPromptTemplate or string templates):
    ANALYST_PROMPT, PLANNER_PROMPT, ROUTER_PROMPT, REACT_PROMPT,
    WRITE_INTRO_PROMPT, WRITE_BODY_PROMPT, WRITE_CONCLUSION_PROMPT,
    REVISE_SECTION_PROMPT, SOURCE_GRADER_PROMPT, GROUNDING_GRADER_PROMPT

Keep variables explicit ({query}, {plan}, {sources}, {section}, ...) so callers
in agents/ bind state fields without guessing.

Owner: agent-prompt-engineer
"""

# TODO(agent-prompt-engineer): define prompt templates.
