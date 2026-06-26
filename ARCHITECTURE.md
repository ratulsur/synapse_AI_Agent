# Synapse AI Agent — Architecture

A LangGraph research-report agent: router → tool-augmented retrieval (with a
source-grader retry loop) → parallel section synthesis (with a grounding-grader
revise loop) → assembled report. This document is the scaffolding map and the
contract reference. Source of truth diagram: `research_agent_v2.jpg`.

> Status: implemented and runnable end-to-end. The graph compiles, the FastAPI
> backend serves the full run/resume/stream flow, and the pipeline produces
> grounded reports from real tool retrieval. This document remains the
> scaffolding map and contract reference; the diagram in `research_agent_v2.jpg`
> is the source of truth for topology.

## Folder map

```
synapse_AI_Agent/
├── main.py                     # existing CLI entry (untouched)
├── config/                     # existing: configuration.yaml (untouched)
├── exception/                  # existing: ResearchAnalystException (untouched)
├── log/                        # existing: GLOBAL_LOGGER (untouched)
├── utils/                      # existing: config_loader, model_loader (untouched)
│
├── schemas/                    # typed contracts shared by every layer
│   ├── source.py               #   Source (title, author, url, domain, content, score, ...)
│   ├── plan.py                 #   ReportPlan, SectionSpec
│   ├── section.py              #   Section (per-section source attribution)
│   ├── routing.py              #   DOMAINS, RouteLabel
│   └── grading.py              #   GraderVerdict, MutationAction
│
├── graph/                      # LangGraph orchestration backbone
│   ├── state.py                #   GraphState (top-level typed state + reducers)
│   ├── builder.py              #   build_graph(): nodes + edges + checkpointer
│   ├── routers.py              #   conditional-edge functions
│   ├── nodes/                  #   node callables (thin glue)
│   │   ├── create_analyst.py
│   │   ├── scope_plan.py
│   │   ├── human_in_the_loop.py
│   │   ├── query_router.py
│   │   ├── write.py
│   │   ├── assemble_report.py
│   │   └── final_answer.py
│   └── subgraphs/
│       ├── retrieval_evidence.py   # tool-call/normalize/dedup/save/grade loop
│       └── section_drafting.py     # parallel intro/body/conclusion writers
│
├── agents/                     # LLM reasoning units (prompt + LLM + output schema)
│   ├── analyst.py
│   ├── planner.py
│   ├── router_agent.py
│   ├── react_agent.py
│   ├── writers.py
│   ├── reviser.py
│   └── graders/
│       ├── source_grader.py
│       └── grounding_grader.py
│
├── prompts/                    # prompt templates + grader rubrics
│   ├── templates.py
│   └── rubrics/
│       ├── source_grader_rubric.md
│       └── grounding_grader_rubric.md
│
├── tools/                      # ReAct tool layer + deterministic processing
│   ├── registry.py             #   domain -> tool set binding
│   ├── web_search.py
│   ├── wiki.py                 #   wikipedia + wikivoyage
│   ├── arxiv.py
│   ├── external_api.py
│   ├── mcp.py                  #   MCP client tools
│   └── processing/
│       ├── normalize.py        #   raw hit -> Source
│       └── dedup.py            #   url/content-hash dedup
│
├── domains/                    # routable domains + per-domain tool policy
│   └── registry.py
│
├── persistence/                # SQLite checkpointer + typed Source store
│   ├── checkpointer.py
│   └── source_store.py
│
├── api/                        # backend API surface fronting the graph
│   ├── app.py
│   └── routes.py
│
├── frontend/                   # UI surface (README scaffold)
├── deploy/                     # packaging / infra (README scaffold)
│
├── tests/                      # unit + integration (test-eval-agent)
│   ├── unit/
│   └── integration/
└── evals/                      # quality/regression harness (test-eval-agent)
    ├── harness.py
    ├── metrics.py
    └── datasets/
```

## What each layer owns

| Layer | Owns |
|-------|------|
| `schemas/` | The typed contracts (`Source`, `ReportPlan`, `Section`, `RouteLabel`, `GraderVerdict`). Source of truth; changes are breaking. |
| `graph/` | State schema, graph/subgraph wiring, node callables, conditional edges, checkpointer attachment, interrupt config. |
| `agents/` | LLM-backed reasoning units; one per node role + the two graders. No graph wiring. |
| `prompts/` | Prompt templates and the two LLM-judge rubrics, decoupled from agent code. |
| `tools/` | ReAct retrieval tools (web/wiki/wikivoyage/arXiv/API/MCP) + deterministic normalize/dedup. |
| `domains/` | Canonical domain list and each domain's tool/parameter policy. |
| `persistence/` | SQLite checkpointer + typed Source store ("Save + Checkpoint"). |
| `api/` | Run/stream/resume endpoints; the human-in-the-loop interrupt contract. |
| `frontend/` | UI; consumes `api/` only. |
| `deploy/` | Containerization, secrets, DB volume, CI/CD. |
| `tests/`, `evals/` | Correctness tests + quality/regression evals. |

## LangGraph state-schema sketch

`GraphState` (see `graph/state.py`) is the single typed object flowing through
the graph. Accumulating fields use reducers.

```
GraphState:
  query: str                      # user research question
  analyst: AnalystPersona         # Create Analyst
  plan: ReportPlan                # Scope & Plan (audience/length/tone/sections)
  plan_approved: bool             # Human-in-the-loop approve

  route_labels: list[str]         # Query Router (multi-label)
  active_domains: list[str]       # selected subset of DOMAINS

  sources: list[Source]           # reducer-accumulated, deduped
  retrieval_iteration: int
  max_retrieval_iterations: int   # retrieval-loop cap
  source_grade: GraderVerdict
  mutation_action: str | None     # reformulate | widen | reroute
  low_confidence: bool            # set if loop exits without passing

  sections: list[Section]         # merge-by-id reducer; per-section source attribution
  grounding_grade: GraderVerdict
  revise_iteration: int
  max_revise_iterations: int      # grounding-loop cap

  report: str                     # Assemble Report
  final_answer: str               # terminal payload

  messages: list                  # ReAct scratch (add_messages)
  errors: list[str]
```

`Source` (the typed evidence unit, `schemas/source.py`):
`id, title, author, url, domain, content, score, tool, retrieved_at`.

## Node / edge topology

Nodes (parent graph):
- `create_analyst` — frame role/persona.
- `scope_plan` — audience/length/tone + section specs (revise target).
- `human_in_the_loop` — interrupt for approve/edit plan.
- `query_router` — multi-label domain routing.
- `retrieval_evidence` (subgraph) — evidence loop.
- `write` — expand plan into per-section tasks, fan out.
- `section_drafting` (subgraph) — parallel writers.
- `grounding_grader` — claims-vs-sources judge.
- `revise_section` — rewrite failing section(s).
- `assemble_report` — join grounded sections.
- `final_answer` — package output → END.

Edges:
```
START -> create_analyst -> scope_plan -> human_in_the_loop
human_in_the_loop --revise--> scope_plan
human_in_the_loop --approve--> query_router
query_router -> retrieval_evidence
retrieval_evidence -> write -> section_drafting -> grounding_grader
grounding_grader --ungrounded--> revise_section --> grounding_grader
grounding_grader --grounded--> assemble_report -> final_answer -> END
```

Retrieval & Evidence subgraph (internal):
```
tool_calls -> normalize -> deduplication -> save_checkpoint -> source_grader
source_grader --pass--> EXIT (-> write)
source_grader --fail + iteration<max--> tool_calls   (apply mutation_action)
source_grader --fail + iteration>=max--> EXIT (set low_confidence)
```

Section Drafting subgraph (internal):
```
fan-out: write_intro || write_body || write_conclusion
fan-in -> EXIT (-> grounding_grader)
```

### Conditional-edge logic (see `graph/routers.py`)
- `route_after_human`: branch on `plan_approved`.
- `route_query`: emit `active_domains`; GENERIC when no label fires.
- `route_after_source_grader`: pass → exit; fail & under cap → re-enter
  `tool_calls` with `mutation_action`; fail & at cap → exit + `low_confidence`.
- `route_after_grounding_grader`: any `failing_section_ids` & under cap →
  `revise_section`; all grounded or at cap → `assemble_report`.

## Feedback loops — termination conditions
- **Source-grader retry loop:** bounded by `retrieval_iteration <
  max_retrieval_iterations`. On the cap, exit and set `low_confidence` so the
  report is still produced but flagged.
- **Grounding-grader revise loop:** bounded by `revise_iteration <
  max_revise_iterations` (per-section `revise_count` also tracked). On the cap,
  proceed to `assemble_report` with the best available draft.

## Resolved design decisions
- **Grounding granularity (per-section):** the grounding grader returns
  `failing_section_ids` and only the failing section(s) are revised. The whole
  draft is not re-written. This is why `Section` carries `cited_source_ids`
  (per-section source attribution). Rationale: cheaper, avoids regressing
  already-grounded sections, enables parallelism.
- **Source-grader mutation strategy (may reroute):** the NO edge is not limited
  to re-retrieving the same path. The grader picks one of
  `reformulate` (same domains/tools, rewrite query), `widen` (relax filters /
  raise top_k, same domains), or `reroute` (add/swap domains+tools, fall back to
  GENERIC). Rationale: a wrong initial route should be correctable without
  exhausting the iteration budget on the wrong domain.

## Ownership

| Folder | Owner |
|--------|-------|
| `schemas/` | backend-developer |
| `graph/` (state, builder, routers, nodes, subgraphs) | backend-developer |
| `tools/` | backend-developer |
| `domains/` | backend-developer |
| `persistence/` | backend-developer (ops/path: cloud-developer) |
| `api/` | backend-developer (DTO contract co-owned with frontend-ui-developer) |
| `agents/` (incl. graders) | agent-prompt-engineer |
| `prompts/` (templates + rubrics) | agent-prompt-engineer |
| `frontend/` | frontend-ui-developer |
| `deploy/` | cloud-developer |
| `tests/`, `evals/` | test-eval-agent |
| `config/`, `exception/`, `log/`, `utils/`, `main.py` | existing (do not disturb) |

## Conventions (inherited from CLAUDE.md)
- Python >=3.13, `uv`, venv at `venv/`. Absolute imports rooted at repo
  (`from schemas.source import Source`, `from log import GLOBAL_LOGGER`).
- New config via `configuration.yaml` + `utils.config_loader.load_config()`.
- Wrap errors in `ResearchAnalystException` and log via `GLOBAL_LOGGER`.
- New LLM providers: add a YAML block + a branch in `ModelLoader.load_llm()`.
