# JesusSaysHi roadmap

## Where things stand (2026-10-26)

| part | state |
|---|---|
| Retrieval | **RAGFlow v1.0** (self-hosted in `ragflow/docker`, not in git): 487 BSB sections, parent-child chunks, LLM keywords and questions, hybrid search + Voyage `rerank-2.5`, threshold 0.30. hit@3 95%, hit@5 98%, p50 445 ms. The phase 1 local index remains as a baseline (`JESUS_RETRIEVER=local`). |
| Voice + persona | **Persona v3 is the default** (`JESUS_PERSONA=memory`): first a person, then a godfather; the Gospels are the memory of his own life, recalled as whole episodes (README Phase 7). Each turn is read once into a kind: information is looked up (`research_web`), questions for a professional are left to one, conversation is remembered. Two-phase reply, about 1–1.3 s to first words. Recall threshold 0.30, chosen from judged samples. Realtime model **`gpt-realtime-2.1`** (not mini), for faithful retelling at about 3 times the cost (README Phase 8). |
| Safety | Crisis check outside the model: phrases, then a classifier model (moderation as fallback). Held-out set: 15/15 caught (was 8/15), 0/15 false alarms ([eval/crisis_results.md](eval/crisis_results.md)). On by default; the owner runs with `JESUS_CRISIS_CHECK=false`. |
| Faithfulness | v3: each reply logs which offered episode he told, scripture recited from elsewhere, and any "I remember..." with nothing offered. Samples at three recall settings: [eval/episodes_samples.md](eval/episodes_samples.md). The quote persona's end-to-end numbers (85% clean) are in [eval/replies_results.md](eval/replies_results.md). |
| Avatar | **Jesus**, trained on Muse clips, FeatherTalk on an 80 ms streaming window (README Phase 6). |
| Demo video | [docs/demo/jesus-demo-20261022.mp4](docs/demo/jesus-demo-20261022.mp4) shows persona v2 on the mini model. A video of v3 on the full model is **not recorded yet** (the owner is short of tokens). |

Services: the RAGFlow stack (6 containers, about 1.2 GB RAM) runs from `ragflow/docker` with `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d`. Its UI is at http://127.0.0.1:19480. The avatar container does not restart by itself: `docker compose --env-file config.local.env up -d avatar`.

## Plan

### P0: what the portfolio needs

| # | task | who | done when |
|---|---|---|---|
| 1 | Generate Jesus talking-head training clips | owner | **done** (Muse, README Phase 6) |
| 2 | Train FeatherTalk on them; build the idle loop | owner + Claude | **done**, epoch 60 |
| 3 | Swap the avatar to `jesus` | Claude | **done** |
| 4 | Try the live voice path once (`python jesus.py`) | owner | **done** |
| 5 | Record the demo with `record_demo.py` | owner (OBS) + Claude | **done** for v2; **v3 not recorded yet**, waiting on tokens |
| 6 | README top section: demo video, architecture diagram, headline numbers | Claude | **done** |
| 7 | Resume bullet and a 2-minute interview story | Claude | **done**, kept local (`docs/INTERVIEW.md` is git-ignored); add the v3 story (episodes as memory, the kind of each turn acted on in code) |
| 25 | ~~Details drift when he tells an episode~~ | Claude | **done**: measured claim by claim (README Phase 8). Two causes: the mini model retells unreliably (18 of 30 tellings wrong), and a loosely fitting episode is bent to fit. The full model fixes most of the first (4 of 23); the second is #31 |
| 31 | **Loosely fitting episodes are bent to fit the person** (full model: 4 of 12 tellings with a reranked score of 0.30–0.39 had an error, 0 of 10 at 0.40 and up) | Claude | offer loose matches with a "tell it as it was, or not at all" note, and measure with `evaluate_fidelity.py` |
| 26 | End-to-end eval of v3 on labels written for episodes (the 55 questions were labelled for passages) | Claude + owner | a judged sample or a new label set, with told / fitting / true-to-text rates |

### P1: quality, if there is time

| # | task | why |
|---|---|---|
| 8 | Grow the eval set: 55 → ~150 questions, and 10 → ~40 off-topic queries; grow the crisis sets past 40 positives | ±5-point noise today; the 0.30 threshold rests on 10 off-topic queries |
| 9 | Add a local `bge-reranker-v2-m3` row to the ablation | completes the "none / open-source local / commercial API" comparison |
| 10 | Look into the rank-1 drop with rerank (75% → 67% hit@1). RAGFlow's source (v1.0.0-rc2, `internal/service/nlp`) shows it already reranks the **child** chunks; it then takes the top `page_size` children and scores each parent by the **mean** of its children's scores, after blending 0.3 keyword similarity with 0.7 Voyage | a section with one strong verse and one weak one loses to a section of middling verses; try the maximum instead of the mean (only possible by reranking ourselves), and re-calibrate the 0.30 threshold after |
| 11 | Quote persona only: the search preamble, the unreliable "Christians understand this in different ways" line | known gaps listed in the README |
| 12 | ~~Passive suicidal ideation missed by both crisis layers~~ | **done**: held-out 15/15. Left: about 0.9 s per message in `--text` mode, and borderline false alarms ("Sometimes I feel worthless") |
| 16 | ~~The live query gap~~ | **addressed**: the app reads each turn itself |
| 17 | Quote persona only: citation slips (off-by-one verses, the wrong book); about 5% of replies | |
| 18 | Quote persona only: a preamble and then nothing | |
| 20 | Phase B sometimes repeats phase A; the model sometimes says what it is about to do ("I'll keep it quiet and steady") | prompt rules reduced it (3 → 1 in 60 replies) but do not remove it |
| 21 | After a local interruption the server sometimes reports `item_retrieve_invalid_item_id` or `response_cancel_not_active` | harmless so far; clean up the delete/truncate/cancel order |
| 22 | The voice is `ash`, the same as SpecterSaysHi's; try `ballad`, `verse` or `echo` if he should sound distinct | owner's taste |
| 27 | Replies run to four or five sentences, longer than the persona's two or three | most visible once he tells a memory |
| 28 | Each turn carries the persona plus two whole episodes: heavier in tokens than v2, and on the full model text input costs $4 per million tokens (6.7 times mini). Four sessions at a time hit the mini model's 200k tokens per minute | one session is fine; batch evals run two at a time; trimming the persona prompt would cut the text share |
| 29 | ~~A story he told is told as something he lived~~ | parables are now marked in the MEMORY note (by their BSB titles, plus four that do not say so) |
| 30 | When a lookup or the realtime model is rate-limited in voice mode, the turn is silent | the reason is logged now; retry once, or say a line |

### P2: optional

| # | task |
|---|---|
| 13 | Send `logs/retrieval.jsonl` traces to Langfuse or Arize Phoenix for a tracing UI |
| 14 | An agentic multi-query mode for comparison questions ("how do Matthew and Luke tell this differently?") |
| 15 | A denomination filter (canon profiles) once books beyond the Gospels are indexed |

Removed: 19 (the v2 end-to-end eval; v2 is superseded), 23 (the 278-saying pool no longer exists), 24 (the hand-written list of lived experience is replaced by the 487 episodes).

## Things to remember

- The Voyage key comes from dashboard.voyageai.com, so it works on `api.voyageai.com` (not `ai.mongodb.com`), and its billing method must stay on file or rate limits drop to 3 RPM.
- RAGFlow 1.0's API differs from its docs. See the setup notes in the README (Phase 4) before changing the ingestion code. Its retrieval internals (child rerank, mean-of-children parent score, the 0.3/0.7 blend after rerank) are only in the source, not the docs.
- Re-running `python ingest_ragflow.py` is safe: only unstarted or failed documents are parsed again. Use `--replace` to re-upload changed sections.
- `python build_episodes.py` reuses its earlier votes; only new sections are asked. Hand-checked answers live in its `REVIEWED` table.
