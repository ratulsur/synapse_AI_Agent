# Source Grader Rubric

Owner: agent-prompt-engineer

The LLM judge scores the accumulated `Source[]` against the report plan and emits
a `GraderVerdict`.

## Inputs
- `query`, `plan` (audience/length/tone/sections)
- `sources` (typed, deduped) with `domain`, `score`, `content`

## Decision (`passed`: YES/NO)
TODO(agent-prompt-engineer): define pass criteria, e.g.
- Coverage: every plan section has >= N supporting sources.
- Relevance: median source score >= threshold.
- Diversity: not all sources from a single url/domain.

## Mutation action (only when `passed` = NO)
- `reformulate` — evidence is on-topic but thin/noisy -> rewrite the query, keep
  the same domains and tools.
- `widen` — too few hits -> relax filters / raise `top_k`, same domains.
- `reroute` — wrong domain(s) entirely -> add/swap domains and tools, falling
  back to GENERIC when no specific domain fits.

TODO(agent-prompt-engineer): finalize thresholds and few-shot examples.
