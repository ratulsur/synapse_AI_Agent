"""Agents: section writers (Intro / Body / Conclusion), run in parallel.

Each writer consumes a SectionSpec + section-scoped sources and produces a
schemas.section.Section with cited_source_ids populated. Prompts:
prompts.writers (one prompt variant per section role).

Owner: agent-prompt-engineer
"""

# TODO(agent-prompt-engineer): write_intro / write_body / write_conclusion.
