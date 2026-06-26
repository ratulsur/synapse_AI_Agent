"""Compiled subgraphs embedded as nodes in the parent graph.

Two subgraphs mirror the dashed boxes in the architecture diagram:
  * retrieval_evidence -- the tool-call/normalize/dedup/checkpoint/grade loop.
  * section_drafting   -- parallel intro/body/conclusion writers.

Owner: backend-developer
"""
