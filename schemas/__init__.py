"""Typed contracts shared across every layer.

These Pydantic models are the source of truth that backend, agents, persistence,
and api layers all import. Changing a field here is a breaking change — keep them
stable and versioned.

Re-exports (intended):
    from schemas.source import Source
    from schemas.plan import ReportPlan, SectionSpec
    from schemas.section import Section
    from schemas.routing import RouteLabel, DOMAINS
    from schemas.grading import GraderVerdict, MutationAction

Owner: backend-developer
"""
