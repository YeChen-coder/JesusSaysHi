# JesusSaysHi roadmap

## Where things stand (2026-10-21, late evening)

| part | state |
|---|---|
| Retrieval | **RAGFlow v1.0** (self-hosted in `ragflow/docker`, not in git): 487 BSB sections, parent-child chunks, LLM keywords and questions, hybrid search + Voyage `rerank-2.5`, abstention at 0.30. hit@3 95%, hit@5 98%, p50 445 ms. The phase 1 local index remains as a baseline (`JESUS_RETRIEVER=local`). |
| Voice + persona | **Persona v2 is the default** (`JESUS_PERSONA=memory`): first a person, then lived experience, then a godfather; scripture only as recalled sayings; two-phase reply (about 1–1.3 s to first words). Tried live by the owner and accepted. Voice `ash` at 0.85. |
| Safety | Crisis check outside the model: phrases, then a classifier model (moderation as fallback). Held-out set: 15/15 caught (was 8/15), 0/15 false alarms ([eval/crisis_results.md](eval/crisis_results.md)). On by default; the owner runs with `JESUS_CRISIS_CHECK=false`. |
| Faithfulness | Every reply is checked (verbatim / paraphrased / unsupported / misattributed / uncited) and logged. End to end over 3 runs: 85% clean replies, 2% unsupported citations, 79% retrieved a relevant section live ([eval/replies_results.md](eval/replies_results.md)). |
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
| 4 | Try the live voice path once (`python jesus.py`): barge-in, echo, latency | owner | **done**: several sessions; local barge-in works, latency fixed (see README Phase 5) |
| 5 | Record the demo with `record_demo.py` | owner (OBS) + Claude | a 1–2 minute video with verse cards |
| 6 | README top section: demo video, architecture diagram, the four headline numbers | Claude | **done** except the video (placeholder line until #5) |
| 7 | Resume bullet and a 2-minute interview story (why RAG fits here, the ablation, abstention, faithfulness) | Claude | **done**, kept local (`docs/INTERVIEW.md` is git-ignored); add the Phase 5 story (memory, two-phase, offline curation) |

### P1: quality, if there is time

| # | task | why |
|---|---|---|
| 8 | Grow the eval set: 55 → ~150 questions, and 10 → ~40 off-topic queries; grow the crisis sets past 40 positives | ±5-point noise today; the 0.30 abstention threshold rests on 10 off-topic queries |
| 9 | Add a local `bge-reranker-v2-m3` row to the ablation (GPU, model server container) | completes the "none / open-source local / commercial API" comparison |
| 10 | Look into the rank-1 drop with rerank (75% → 67% hit@1) | e.g. rerank child chunks instead of parents, or try `rerank_candidates_count` |
| 11 | Persona issues still open: the search preamble ("I'll look in the Gospels…"), the unreliable "Christians understand this in different ways" line | known gaps listed in the README |
| 12 | ~~Passive suicidal ideation missed by both crisis layers~~ | **done**: classifier layer, held-out 15/15. Left: about 0.9 s per message in `--text` mode, and borderline false alarms ("Sometimes I feel worthless") |
| 16 | ~~The live query gap (the realtime model wrote its own query)~~ | **addressed by persona v2**: the app rewrites the query itself, and phase A covers the second it takes |
| 17 | Citation slips: off-by-one verse numbers, a quote that runs past the one verse it cites, the wrong book ("Matthew 7:10" for Mark 7:10); about 5% of replies | the bulk of what is left of "not clean" |
| 18 | A preamble and then nothing: the model says "Listen." and ends the turn without calling the tool (a few per 55) | shows up as "no verbatim quote" in the reply eval |

| 19 | Run the end-to-end reply eval on the memory persona (curated pool, local ranking, two phases) | the v2 numbers so far come from one trial with an earlier selector |
| 20 | Phase B sometimes repeats phase A or opens with filler; phase A sometimes announces what he will do | prompt rules help but do not hold every time |
| 21 | After a local interruption the server sometimes reports `item_retrieve_invalid_item_id` (an item already deleted) | harmless so far; clean up the delete/truncate order |
| 22 | The voice is `ash`, the same as SpecterSaysHi's (at 0.90); try `ballad`, `verse` or `echo` if he should sound distinct | owner's taste |
| 23 | The curated pool (278 sayings) still has a few odd keeps ("What do you want?") and splits some verses into fragments ("for they will be comforted.") | re-run curate_memory.py with stricter rules, or review the list by hand |
| 24 | Grow the "lived experience" list (e.g. scenes he would call his favourite), so questions about his life have more to draw on | "What's your favourite scene?" got a vague answer |

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
