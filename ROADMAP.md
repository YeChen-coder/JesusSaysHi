# JesusSaysHi roadmap

## Where things stand (2026-10-21)

| part | state |
|---|---|
| Retrieval | **RAGFlow v1.0** (self-hosted in `ragflow/docker`, not in git): 487 BSB sections, parent-child chunks, LLM keywords and questions, hybrid search + Voyage `rerank-2.5`, abstention at 0.30. hit@3 95%, hit@5 98%, p50 445 ms. The phase 1 local index remains as a baseline (`JESUS_RETRIEVER=local`). |
| Voice + persona | Works in `--text` mode against the real model. The live microphone and speaker path has not been tried by the owner yet. |
| Safety | Crisis check outside the model (phrases + moderation) with a fixed, tool-free reply. |
| Faithfulness | Every reply is checked (verbatim / paraphrased / unsupported / misattributed / uncited) and logged. |
| Avatar | FeatherTalk runtime in `avatar/`, but still the SpecterSaysHi **gentleman** placeholder. Two Jesus base images are in `Jesus_material/`. |
| Demo video | `record_demo.py` is ready (OBS `JesusDemo` profile); nothing recorded yet. |

Services: the RAGFlow stack (6 containers, about 1.2 GB RAM) runs from `ragflow/docker` with `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`. Its UI is at http://127.0.0.1:19480. The avatar container does not restart by itself: `docker compose --env-file config.local.env up -d avatar`.

## Plan

### P0: what the portfolio needs

| # | task | who | done when |
|---|---|---|---|
| 1 | Generate Jesus talking-head training clips from `Jesus_material/` (Grok, once the limit resets) | owner | enough clean clips for FeatherTalk training, about the gentleman's amount |
| 2 | Train FeatherTalk on them; build the idle loop and the teeth/detail assets | owner + Claude | a checkpoint and idle assets in one folder |
| 3 | Swap the avatar: add a `jesus` entry to `avatar/characters.json`, set `JESUS_AVATAR_ASSETS` and `JESUS_AVATAR_CHARACTER=jesus` | Claude | the avatar page shows Jesus lip-syncing |
| 4 | Try the live voice path once (`python jesus.py`): barge-in, echo, latency | owner | one real spoken conversation works end to end |
| 5 | Record the demo with `record_demo.py` | owner (OBS) + Claude | a 1–2 minute video with verse cards |
| 6 | README top section: demo video, architecture diagram, the four headline numbers | Claude | someone can understand the project in 30 seconds |
| 7 | Resume bullet and a 2-minute interview story (why RAG fits here, the ablation, abstention, faithfulness) | Claude | written down in `docs/` |

### P1: quality, if there is time

| # | task | why |
|---|---|---|
| 8 | Grow the eval set: 55 → ~150 questions, and 10 → ~40 off-topic queries | ±5-point noise today; the 0.30 abstention threshold rests on 10 off-topic queries |
| 9 | Add a local `bge-reranker-v2-m3` row to the ablation (GPU, model server container) | completes the "none / open-source local / commercial API" comparison |
| 10 | Look into the rank-1 drop with rerank (75% → 67% hit@1) | e.g. rerank child chunks instead of parents, or try `rerank_candidates_count` |
| 11 | Persona issues still open: the search preamble ("I'll look in the Gospels…"), the unreliable "Christians understand this in different ways" line | known gaps listed in the README |
| 12 | Passive suicidal ideation ("I could just disappear…") is missed by both crisis layers | the most important safety gap |

### P2: optional

| # | task |
|---|---|
| 13 | Send `logs/retrieval.jsonl` traces to Langfuse or Arize Phoenix for a tracing UI |
| 14 | An agentic multi-query mode for comparison questions ("how do Matthew and Luke tell this differently?") |
| 15 | A denomination filter (canon profiles) once books beyond the Gospels are indexed |

## Things to remember

- The Voyage key comes from dashboard.voyageai.com, so it works on `api.voyageai.com` (not `ai.mongodb.com`), and its billing method must stay on file or rate limits drop to 3 RPM.
- RAGFlow 1.0's API differs from its docs. See the setup notes in the README (Phase 4) before changing the ingestion code.
- Re-running `python ingest_ragflow.py` is safe: only unstarted or failed documents are parsed again. Use `--replace` to re-upload changed sections.
