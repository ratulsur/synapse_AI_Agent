"""LLM-judge graders: the two quality gates of the pipeline.

  * source_grader   -- gates the retrieval/evidence loop (evidence sufficiency).
  * grounding_grader -- gates section drafting (claims supported by sources).

Both return schemas.grading.GraderVerdict and are driven by rubrics in
prompts/rubrics/.

Owner: agent-prompt-engineer
"""
