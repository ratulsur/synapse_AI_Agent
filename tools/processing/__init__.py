"""Deterministic (non-LLM) evidence-processing functions.

Sit between raw tool output and the typed Source store:
  normalize -> dedup -> (persist).

Owner: backend-developer
"""
