# Source Grader Rubric

Owner: agent-prompt-engineer
Version: v1

The LLM judge scores the accumulated, deduped `Source[]` against the report plan
and emits a `GraderVerdict` (`passed`, `score`, `rationale`, `mutation_action`).
This is an evidence-sufficiency-and-relevance judgement made BEFORE any writing,
so the bar is "is there enough trustworthy, on-topic material to write each
planned section" — not "is the prose good".

## Inputs
- `query` and the `plan` (audience / length / tone / the ordered section specs).
- `sources` — typed and deduped, each with `domain`, `score`, `url`, `content`.
- The current `iteration` and `max_iterations` (context only; do not relax the
  bar just because iterations remain).

## Scoring dimensions (weigh into `score`, 0..1)
1. Coverage (most important). Map sources to the plan's sections (intro / body /
   conclusion intents). The body/core-analysis topic must have at least 2
   distinct supporting sources; intro and conclusion can lean on the same pool.
   A section with zero on-topic support is a hard coverage failure.
2. Relevance. Sources must be on-topic for the query, not merely keyword-adjacent.
   Roughly half or more of the pool should be clearly relevant; treat retriever
   `score` as a hint, not proof.
3. Diversity. Evidence should not all come from a single url or a single domain
   when the query is broader. Near-duplicate sources count once toward coverage.
4. Trustworthiness. Prefer authoritative/primary sources; a pool dominated by
   thin snippets or one low-quality page is weaker even if on-topic.

## Decision (`passed`: YES/NO)
- `passed = true` when ALL of:
  - every planned section has at least one clearly relevant source AND the
    body/core topic has >= 2 distinct supporting sources;
  - the majority of the pool is on-topic (relevance);
  - evidence is not entirely from one url/domain (diversity);
  - `score >= 0.6`.
- `passed = false` otherwise.
- Empty or near-empty pool => `passed = false`, low score.

## Mutation action (REQUIRED when `passed = false`; null when `passed = true`)
Pick the single action that best fixes the dominant gap:
- `reformulate` — the evidence is on the right domain and roughly on-topic but
  thin, noisy, or slightly off-target. Keep the same domains/tools; the agent
  should rewrite the query (synonyms, narrower phrasing).
- `widen` — the domain is right and what little was found is relevant, but there
  are simply too few hits. Keep the same domains; relax filters / raise `top_k`.
- `reroute` — the evidence is mostly off-topic or from the wrong area, i.e. the
  initial domain routing was wrong. Add or swap domains/tools, falling back to
  GENERIC web/wiki when no specific domain fits.

Heuristic: wrong area -> `reroute`; right area but too few -> `widen`; right area,
enough volume but low quality/relevance -> `reformulate`.

## Examples (judgement sketches)
- 8 on-topic sources across 3 domains, body has 4 supporters -> `passed=true`,
  score ~0.85, mutation_action=null.
- 2 sources, both relevant, both from the same blog -> `passed=false`
  (coverage+diversity), `widen` (right area, too few).
- 6 sources but all about a different sense of the query term -> `passed=false`
  (relevance), `reroute`.
- 5 loosely-related low-quality snippets, right domain -> `passed=false`
  (relevance/trust), `reformulate`.
