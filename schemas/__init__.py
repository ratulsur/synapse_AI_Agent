"""Typed contracts shared across every layer.

These Pydantic models are the source of truth that backend, agents, persistence,
and api layers all import.  Changing a field here is a breaking change -- keep
them stable and versioned.

Owner: Ratul Sur
"""

from schemas.analyst import AnalystPersona
from schemas.grading import GraderVerdict, MutationAction
from schemas.plan import ReportPlan, SectionSpec
from schemas.routing import DOMAINS, GENERIC_DOMAIN, RouteLabel
from schemas.section import Section
from schemas.source import Source

__all__ = [
    "AnalystPersona",
    "GraderVerdict",
    "MutationAction",
    "ReportPlan",
    "SectionSpec",
    "DOMAINS",
    "GENERIC_DOMAIN",
    "RouteLabel",
    "Section",
    "Source",
]
