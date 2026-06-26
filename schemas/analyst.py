"""Analyst persona schema -- produced by the Create Analyst node.

Owner: Ratul Sur
"""

from pydantic import BaseModel, Field


class AnalystPersona(BaseModel):
    """Role/persona framing produced by the Create Analyst agent.

    Fields:
        expertise: Domain expertise the analyst brings (e.g. "AI / ML researcher").
        voice:     Writing voice and register (e.g. "authoritative but accessible").
        stance:    Editorial stance or angle (e.g. "evidence-first, sceptical of hype").
    """

    expertise: str = Field(
        default="generalist",
        description="Domain expertise the analyst brings to the research question.",
    )
    voice: str = Field(
        default="neutral",
        description="Writing voice and register for the drafted report.",
    )
    stance: str = Field(
        default="objective",
        description="Editorial stance or analytical angle.",
    )
