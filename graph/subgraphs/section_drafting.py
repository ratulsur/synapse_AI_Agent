"""Subgraph: Parallel Section Drafting.

Fans out into three writer agents that run concurrently, then fans back in:
    write_intro    -> agents.writers.write_intro
    write_body     -> agents.writers.write_body
    write_conclusion -> agents.writers.write_conclusion
    (fan-in) -> parent: grounding_grader

Each writer consumes the plan section spec plus the section-scoped sources
(per-section source attribution; see ADR-005) and emits a Section with
status=drafted and a record of which Source ids it cited. Concurrent updates to
the ``sections`` list require a merge reducer keyed by section id.

TODO(backend-developer): implement build_section_drafting_subgraph().

Owner: backend-developer (writer prompts: agent-prompt-engineer)
"""

# TODO(backend-developer): implement build_section_drafting_subgraph().
