"""Node: Write (plan sections).

Transition node that expands the approved plan + graded sources into per-section
writing tasks, then fans out into the parallel section-drafting subgraph. Emits
the initial ``sections`` scaffold (one Section per plan spec, status=pending).

Owner: backend-developer
"""

# TODO(backend-developer): def write(state) -> dict
