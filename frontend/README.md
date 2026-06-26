# Frontend (UI surface)

Owner: frontend-ui-developer

The UI that drives a research run and renders progress, the editable plan
(human-in-the-loop), streamed section drafts, grader verdicts, and the final
report with its sources.

## Consumes (from `api/`)
- `POST /runs` to start, `GET /runs/{id}/stream` for live node events,
  `POST /runs/{id}/resume` for the plan approve/edit interrupt,
  `GET /runs/{id}` for the final report + sources.

## Key screens (suggested)
- Query entry + analyst/plan review (approve / edit / revise).
- Live pipeline timeline (router -> retrieval loop -> drafting -> grading).
- Final report with inline citations linking to the typed Source list.

TODO(frontend-ui-developer): choose stack (e.g. React/Vite or Streamlit) and
scaffold. Keep all server interaction behind the `api/` contract.
