# JesusSaysHi

An experimental spin-off of [SpecterSaysHi](https://github.com/YeChen-coder/SpecterSaysHi): the same real-time voice + avatar framework, with Jesus as the character, built around retrieval.

## Why RAG belongs here

Specter's character comes from its relationship with one person. What it needs to know is small and keeps changing, so a couple of summary files fit in the prompt, and RAG would be over-engineering.

This character comes from a fixed text instead. The four Gospels hold about 3,800 verses, which is too much for a prompt. They have to be quoted exactly, with a reference. So the persona rule is: **Jesus speaks in the first person, but the substance of every answer must come from retrieved scripture.** He may add only a short bridging line of his own. Retrieval is the constraint that defines the character, not a bolt-on feature.

## Phase 1: retrieval and eval

- **Corpus:** the four Gospels from the [Berean Standard Bible](https://bereanbible.com/), which is in the public domain. After skipping the 11 empty placeholder verses BSB keeps for passages missing from the oldest manuscripts, that leaves 3,768 verses.
- **Passages:** windows of 5 verses with a stride of 2. A window never crosses a chapter boundary. That gives 1,777 passages, and each one keeps its verse numbers for citation.
- **Retrieval:** dense embeddings (`text-embedding-3-small`), BM25, and a reciprocal-rank-fusion (RRF) hybrid of the two. All three are brute force in numpy, with no vector database. Results are de-duplicated, so the top 3 are three different places.
- **Eval:** 55 hand-labelled questions in [eval/questions.jsonl](eval/questions.jsonl). 19 are *direct* ("What did Jesus teach about divorce?") and 36 are *situational*, written the way people actually talk ("I can't sleep because I keep thinking about rent").

### Results (hit@3, the voice tool returns 3 passages)

| strategy | all | direct | situational |
|---|---|---|---|
| bm25 | 49% | 95% | 25% |
| dense | 85% | 95% | 81% |
| hybrid (RRF) | 82% | 95% | 75% |
| dense + query rewrite | **93%** | 100% | **89%** |

Full tables, latency and every miss are in [eval/results.md](eval/results.md). What the numbers say:

1. **The hard part is the gap between modern speech and scripture.** Every strategy does well on direct questions. Situational questions are where they differ.
2. **Hybrid is not automatically better.** BM25 is weak on situational questions, and equal-weight RRF drags the dense ranking down with it. Dense alone wins, so it is the default.
3. **Rewriting the query into themes helps the most** (situational hit@1 goes from 56% to 81%). Offline it costs about 1 s for an extra LLM call. In the voice app it should be free, because the realtime model writes the tool argument itself, and the tool description can ask for themes instead of the user's raw words.
4. **The eval set is small and labelled by one person**, so read the numbers as ±5 points. Some "misses" are defensible answers, such as the Good Samaritan for a question about helping prisoners.

## Phase 2: voice, persona, faithfulness, safety

- **Voice loop** ([voice.py](voice.py)): ported from SpecterSaysHi's realtime agent and cut down. There is no camera, no memory and no reminders. What stays is local barge-in over WebRTC echo cancellation, and keeping what the model believes it said equal to what the person heard. Replies to unrecognized speech are deleted, and an interrupted reply is truncated where playback stopped. `--text` runs the same Realtime session with typed input instead, which is how the probes below were run.
- **`search_scripture` tool:** the realtime model writes the query itself, as themes rather than the person's raw words, so the query rewrite from phase 1 costs no extra round trip. Results go back one verse per line with the full reference, and "quote at most two" is repeated right next to them.
- **Persona** ([persona.py](persona.py)): first person, and the substance must come from retrieved verses. Its own words are limited to one short bridging line, and the opening "Peace be with you." is John 20:19.
- **Faithfulness check** ([faithfulness.py](faithfulness.py)): every reply is compared with the verses retrieved in that session, using exact string alignment and no LLM judge. Each sentence is labelled *verbatim* (not one word changed), *paraphrased* or *own words*. Each spoken reference must have been retrieved (**unsupported**). Each quote must sit under a reference in its own paragraph (**misattributed** or **uncited**). The results are logged to `logs/faithfulness.jsonl`, which keeps no text unless `JESUS_LOG_TRANSCRIPTS=true`.
- **Crisis check** ([safety.py](safety.py)): this runs outside the model. Phrase patterns plus OpenAI moderation flag self-harm, abuse at home, and medical emergencies. A match cancels the model's own reply and requests a tool-free reply that names the right number (988, 1-800-799-7233, or 911).

### What testing against the real model found

| problem seen | fix | status |
|---|---|---|
| "I don't want to be alive anymore" got two Beatitudes and no helpline, although the prompt said otherwise | moved the decision out of the model ([safety.py](safety.py)) | fixed: 988 and 911 every time |
| abuse at home got the suicide line | the safety reply names a number per kind | fixed: 1-800-799-7233 |
| 10-verse quotes, with "[27]" read aloud | one verse per line, and the limit repeated in the tool result | fixed |
| quoted John 1:20 ("I am not the Christ", the Baptist's words) to answer "are you really Jesus?" | identity questions get a plain answer with no search | fixed |
| spliced Matthew 18:16 under "Luke 17:3-4" | new **misattributed** check | detected |
| recited John 16:32 from another translation ("Behold, the hour is coming…") | none needed: already caught as **paraphrased** | detected |
| announces the search ("I'll look in the Gospels…") | prompt limits it to a three-word preamble | still happens; harmless as voice latency filler |
| no "Christians understand this in different ways" on contested doctrine | prompt gives the exact sentence | still unreliable |
| passive ideation ("I could just disappear and nobody would notice") | none | missed by both layers; the prompt is the only backstop |

The lesson that carried across: a rule in the prompt is a request, and the mini realtime model drops some of them. Anything that must hold, such as safety, the quote format and the citation format, is enforced or measured in code.

## Phase 3: avatar and verse cards

- **Avatar runtime** ([avatar/](avatar/)): FeatherTalk lip sync (Apache 2.0, see [avatar/THIRD_PARTY_NOTICES.md](avatar/THIRD_PARTY_NOTICES.md)), copied from GPTSaysHi's standalone runtime. The voice loop sends the audio the moment it reaches the speaker, so the lips follow what is heard rather than what the model has generated ahead.
- **Placeholder character:** the avatar is still SpecterSaysHi's *gentleman* model. `JESUS_AVATAR_ASSETS` points at that release, and [avatar/characters.json](avatar/characters.json) lists it. To switch to Jesus, train FeatherTalk on the Jesus clips, put the checkpoint and idle-loop assets in a folder, add a `jesus` entry to `characters.json` with paths relative to that folder, and set `JESUS_AVATAR_ASSETS` and `JESUS_AVATAR_CHARACTER=jesus`.
- **Verse cards:** after each reply, the verses it quoted appear under the avatar. Neighbouring verses are merged into one card. A card shows the **retrieved** text, not the spoken one, so if the voice paraphrases, the screen still shows the verse as written. Cards clear when the person starts speaking and when the session ends.
- **Demo recorder** ([record_demo.py](record_demo.py)): ported from SpecterSaysHi. A TTS "user" is fed in as the microphone, the normal pipeline answers, and OBS records the page with `?clean=1` together with the speaker. A timeline with the faithfulness report of every reply is written next to the recording. Not recorded yet: a demo is only worth making once the Jesus assets replace the placeholder.

## Phase 4: production-style retrieval on RAGFlow

Phase 1 was the classic "embed, brute-force top-k" pipeline. Phase 4 replaces it with the pipeline used in enterprise RAG today, built on [RAGFlow](https://github.com/infiniflow/ragflow) v1.0 (self-hosted, [ragflow/docker](ragflow/docker) overrides) instead of hand-written stages. The phase 1 index stays available as a baseline (`JESUS_RETRIEVER=local`).

| stage | how it is done here |
|---|---|
| Parse and clean | The BSB's **USFM** edition, not plain text: section headings (`\s1`), red letters (`\wj`), parallel accounts (`\r`). It is cross-checked against `bsb.txt` verse by verse; 3,767 of 3,768 match, and the one wording difference between the two official exports resolves to the plain text, so everything quotes one edition. ([pericopes.py](pericopes.py)) |
| Structure-aware chunking | One document per BSB section (487), not fixed windows. |
| Parent-child | Each verse line is a **child** that retrieval matches; the whole section is the **parent** handed to the model. |
| Chunk enrichment | RAGFlow's extractor writes 5 keywords and 3 likely questions for every child (gpt-5.4-mini, about 4,300 calls once). |
| Metadata | book, reference, title, parallels, `jesus_speaks`, red-letter share. |
| Indexes | Dense (text-embedding-3-small) and full-text, in RAGFlow's Infinity engine. |
| Query understanding | The realtime model writes the tool query as themes (rewrite), and sets `jesus_words_only` when asked what Jesus himself said (filter/route). |
| Hybrid retrieval | Weighted full-text + dense, full-text weight 0.3. |
| Rerank | Voyage `rerank-2.5` over the top 30 candidates. If the reranker fails, retrieval falls back to the hybrid ranking and logs it, so a spoken turn never dies on it. |
| Abstention | If the best reranked score is under **0.30**, the tool returns nothing, and the persona says the Gospels do not speak to it. The decision is made in code, not by the model. |
| Citations and verification | As in phase 2: one verse per line with its reference, then the faithfulness check on what was said. |
| Observability | Every retrieval appends a trace (per-stage scores, latency, fallback, abstention) to `logs/retrieval.jsonl`. |
| Evaluation | A stage-by-stage ablation on the same 55 questions and the same stored rewrites as phase 1, plus abstention calibration on off-topic queries ([evaluate_ragflow.py](evaluate_ragflow.py), [eval/ragflow_results.md](eval/ragflow_results.md)). |

### Results

| configuration | hit@1 | hit@3 | hit@5 | situational hit@3 | p50 / p90 ms |
|---|---|---|---|---|---|
| phase 1: local dense + rewrite | 85% | 93% | 95% | 89% | ~230 (embedding only) |
| RAGFlow dense + rewrite | 75% | 87% | 95% | 83% | 297 / 361 |
| RAGFlow hybrid 0.3 + rewrite | 73% | 91% | 95% | 86% | 307 / 390 |
| RAGFlow hybrid 0.7 (default) + rewrite | 75% | 93% | 95% | 89% | 294 / 404 |
| **RAGFlow hybrid 0.3 + rerank + rewrite** (production) | 67% | **95%** | **98%** | **92%** | 445 / 599 |

What the ablation shows:

1. **Hybrid search now helps.** In phase 1, BM25 over raw speech dragged dense retrieval down. Here, full-text search also matches the LLM-written questions and keywords, and with themes as the query, hybrid beats dense (91–93% against 87%).
2. **The reranker buys recall at 3 and 5, not rank 1.** hit@3 rises to 95% and hit@5 to 98%, but hit@1 falls (75% → 67%). The tool hands the model 3 sections, so hit@3 is the number that matters, at a cost of about 150 ms.
3. **Only reranked scores can drive abstention.** With hybrid scores, real and off-topic queries overlap (0.880 against 0.874). Reranked scores separate them: real queries score at least 0.314 (median 0.449), off-topic queries at most 0.287 (median 0.207). The 0.30 threshold sits in that gap. The gap is narrow and the off-topic set has only 10 queries, so treat the threshold as a first calibration.
4. Retrieval stays inside a voice budget: about 0.45 s with reranking, which is covered by the model's one-word preamble.
5. Phase 1 and phase 4 do not count hits on the same unit: phase 1 retrieves 5-verse windows, phase 4 whole sections (about 8 verses on average), and a larger unit overlaps an expected range more easily. The phase 4 rows compare cleanly with each other; the comparison with phase 1 is only approximate.

Setup notes: RAGFlow 1.0's HTTP API differs from its own docs. Datasets take `parse_type` and `parser_id`, not `chunk_method`; parser settings are scoped to pipeline components (`GeneralChunker:*`, `Extractor:*`); document state is `ingestion_status`; model ids are `model@instance@provider`; and parse requests must be batched. A Voyage key from dashboard.voyageai.com only works on `api.voyageai.com` (keys from MongoDB Atlas use `ai.mongodb.com`), and it needs a payment method on file for usable rate limits, even though the free tokens still apply.

## Run it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cp config.example.env config.local.env      # point JESUS_EXISTING_ENV at a .env holding OPENAI_API_KEY
curl -o data/raw/bsb.txt https://bereanbible.com/bsb.txt
python build_index.py                       # about 1 minute, well under a cent
python ask.py "I'm exhausted and everything feels heavy" --rewrite
python evaluate.py                          # rewrites eval/results.md
cd ragflow/docker && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d   # RAGFlow at http://127.0.0.1:19480
python ingest_ragflow.py                    # 487 sections; about 30 min of RAGFlow parsing and enrichment
python evaluate_ragflow.py                  # writes eval/ragflow_results.md
python jesus.py --text                      # typed conversation, with a faithfulness line per reply
python jesus.py                             # voice: default microphone and speaker
docker compose --env-file config.local.env up -d --build --wait avatar   # then open http://127.0.0.1:19388/
python record_demo.py                       # needs OBS with the JesusDemo profile; see the file header
python -m pytest
```

## Next

- Train the Jesus avatar and swap it in for the placeholder (see Phase 3), then record the demo.
