https://github.com/user-attachments/assets/d54dbde9-24d5-4467-b5d5-5570ba46a23a

# JesusSaysHi

A real-time Jesus you talk to out loud, with a voice and an avatar, a little like going to confession. He listens first and answers in his own words, as a man shaped by what he lived through in the Gospels. When one of his own sayings fits the moment, it is retrieved and said word for word, never quoted from the model's memory.

> **Sibling project of [SpecterSaysHi](https://github.com/YeChen-coder/SpecterSaysHi).** It uses the same real-time voice and avatar framework with a different character, and it is built around retrieval (RAG), which Specter deliberately does without.

> **Avatar:** a photoreal Jesus, trained on clips generated with Muse and lip-synced live with FeatherTalk. See [Phase 6](#phase-6-the-jesus-avatar).

**Demo:** [docs/demo/jesus-demo-20261022.mp4](docs/demo/jesus-demo-20261022.mp4) (2 min 22 s). The person is a TTS voice fed in as the microphone, and everything else is the normal live pipeline: transcription, memory recall, the two-phase reply, the faithfulness check, verse cards and the avatar, recorded by OBS. The timeline with every reply and its faithfulness report is [next to it](docs/demo/jesus-demo-20261022.timeline.json).

### At a glance

| | |
|---|---|
| **Persona** | First a person, then his lived experience, then a godfather who watches over you. Scripture reaches him only as a *memory*: up to three of his own sayings, retrieved for what you just said. He uses one only if it fits, and only word for word. [Phase 5](#phase-5-persona-v2-a-person-first-scripture-as-memory) |
| **Latency** | He starts speaking about 1 to 1.3 s after you stop. The memory is recalled while his first sentence plays: query rewrite, RAGFlow and local ranking. |
| **Retrieval** | 95% hit@3 and 98% hit@5 on 55 hand-labelled questions, at a p50 of 445 ms (RAGFlow 1.0: structure-aware chunks, hybrid search, Voyage rerank-2.5). Rewriting the query adds 8 points. [Ablation](eval/ragflow_results.md) |
| **Faithfulness** | Every reply is checked against the retrieved text and against all four Gospels. In the first memory trial he said all 16 sayings he was given word for word, and quoted no scripture he was not given. The earlier quote-only persona had 85% clean replies over 3 runs. [Reply eval](eval/replies_results.md) |
| **Abstention** | Decided in code on the reranked score (threshold 0.30): off-topic queries top out at 0.287, and real ones start at 0.314. |
| **Safety** | An optional crisis check outside the model (phrase patterns plus a classifier model; on by default, `JESUS_CRISIS_CHECK=false` turns it off). It catches 15/15 held-out crisis messages, including passive ideation, up from 8/15, with 0/15 false alarms. [Crisis eval](eval/crisis_results.md) |

```mermaid
flowchart LR
    you(["You (mic)"]) --> stt["Transcript<br/>gpt-transcribe"]
    stt --> a["Phase A: one sentence<br/>that receives you"]
    stt --> rw["Rewrite into themes"]
    rw --> rag["RAGFlow<br/>hybrid → Voyage rerank<br/>abstain below 0.30"]
    rag --> rank["His sayings in those sections<br/>curated offline · ranked locally"]
    rank -- "MEMORY: up to 3" --> b["Phase B: he goes on,<br/>may say one word for word"]
    a --> out(["Speaker +<br/>avatar"])
    b --> out
    b --> faith["Faithfulness check<br/>vs retrieved text and all four Gospels"]
    faith --> cards["Verse cards"]
    faith --> log[("logs/")]
    stt -. optional .-> crisis{"Crisis check"}
```

## Why RAG belongs here

Specter's character comes from its relationship with one person. What it needs to know is small and keeps changing, so a couple of summary files fit in the prompt, and RAG would be over-engineering.

This character comes from a fixed text instead: the four Gospels, about 3,800 verses, too much for a prompt. His way of seeing comes from what he lived through there, and when he says one of his own sayings, it has to be exactly what is written. A model cannot be trusted to do that from memory: in testing it recited a verse from another translation. So scripture reaches him only through retrieval, and every reply is checked against the text. The first persona (phases 1 to 4) went further and let him say nothing of substance that was not retrieved. That made him a verse dispenser, and [Phase 5](#phase-5-persona-v2-a-person-first-scripture-as-memory) changes it.

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
- **Crisis check** ([safety.py](safety.py)): this runs outside the model. Phrase patterns, then a small classifier model (with OpenAI moderation as the fallback if it fails), flag self-harm, abuse at home, and medical emergencies. The classifier takes about 0.9 s at p50. In voice mode it runs alongside the reply, so it adds no latency unless it fires; in `--text` mode it runs before the message is sent. A match cancels the model's own reply and requests a tool-free reply that names the right number (988, 1-800-799-7233, or 911).

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
| passive ideation ("I could just disappear and nobody would notice") missed by phrases and moderation | a classifier layer, measured on a tuning set and a separately written held-out set ([eval/crisis_results.md](eval/crisis_results.md)) | fixed: held-out 15/15, up from 8/15, 0 false alarms |

The lesson that carried across: a rule in the prompt is a request, and the mini realtime model drops some of them. Anything that must hold, such as safety, the quote format and the citation format, is enforced or measured in code.

## Phase 3: avatar and verse cards

- **Avatar runtime** ([avatar/](avatar/)): FeatherTalk lip sync (Apache 2.0, see [avatar/THIRD_PARTY_NOTICES.md](avatar/THIRD_PARTY_NOTICES.md)), copied from GPTSaysHi's standalone runtime. The voice loop sends the audio the moment it reaches the speaker, so the lips follow what is heard rather than what the model has generated ahead.
- **Characters:** [avatar/characters.json](avatar/characters.json) lists `gentleman` (SpecterSaysHi's model, the earlier placeholder) and `jesus` ([Phase 6](#phase-6-the-jesus-avatar)). `JESUS_AVATAR_CHARACTER`, `JESUS_AVATAR_MODE` and `JESUS_AVATAR_ASSETS` choose between them.
- **Verse cards:** after each reply, the verses it quoted appear under the avatar. Neighbouring verses are merged into one card. A card shows the **retrieved** text, not the spoken one, so if the voice paraphrases, the screen still shows the verse as written. Cards clear when the person starts speaking and when the session ends.
- **Demo recorder** ([record_demo.py](record_demo.py)): ported from SpecterSaysHi. A TTS "user" is fed in as the microphone, the normal pipeline answers, and OBS records the page with `?clean=1` together with the speaker. A timeline with the faithfulness report of every reply is written next to the recording. It uses the same persona and crisis-check settings as `jesus.py`, and waits for phase B before the next line.

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
3. **Only reranked scores can drive abstention.** Hybrid scores squeeze the two sets together. Without the rewrite they overlap. With it, the gap is only 0.006 (real queries at least 0.880, off-topic at most 0.874), and the medians are 0.895 and 0.866. Reranked scores pull them apart: real queries score at least 0.314 (median 0.449), off-topic queries at most 0.287 (median 0.207). The 0.30 threshold sits in that gap. The gap is narrow and the off-topic set has only 10 queries, so treat the threshold as a first calibration.
4. Retrieval stays inside a voice budget: about 0.45 s with reranking, which is covered by the model's one-word preamble.
5. Phase 1 and phase 4 do not count hits on the same unit: phase 1 retrieves 5-verse windows, phase 4 whole sections (about 8 verses on average), and a larger unit overlaps an expected range more easily. The phase 4 rows compare cleanly with each other; the comparison with phase 1 is only approximate.

Setup notes: RAGFlow 1.0's HTTP API differs from its own docs. Datasets take `parse_type` and `parser_id`, not `chunk_method`; parser settings are scoped to pipeline components (`GeneralChunker:*`, `Extractor:*`); document state is `ingestion_status`; model ids are `model@instance@provider`; and parse requests must be batched. A Voyage key from dashboard.voyageai.com only works on `api.voyageai.com` (keys from MongoDB Atlas use `ai.mongodb.com`), and it needs a payment method on file for usable rate limits, even though the free tokens still apply.

## Phase 5: persona v2, a person first, scripture as memory

**Why.** The quote-only persona answered "I said terrible things to my mother today" with "…anyone who says, 'You fool!' will be subject to the fire of hell." It did exactly what its rules said: nothing of its own, only verses. The persona was rewritten in a fixed order: **first a person** (a man from Nazareth who has worked, wept and been let down), **then his lived experience**, with each memory tied to the situations it speaks to (the boy in the temple who grew in wisdom little by little, for someone who feels slow; no place to lay his head, for someone far from home; Peter's denial and the breakfast after it, for someone who let a friend down), **then a godfather** who is steady, on your side and not shocked by anything. He speaks in plain images, gives little practical advice, and does not break character to say he is an AI unless asked directly. The drafts and trials, in Chinese, are in [docs/](docs/).

**Scripture as memory** ([memory.py](memory.py)). The model has no search tool. From your second turn on, the system does the remembering:

1. **Rewrite** what you said into themes with a small model. In the RAGFlow ablation this added 8 points of hit@3. It costs about 1 s, which phase A covers (below).
2. **RAGFlow** retrieves sections: hybrid search, Voyage rerank, and abstention below 0.30.
3. **Rank his sayings** inside those sections. These are 2,109 red-letter spans (Jesus' own words), cut from the BSB USFM and checked to be exact pieces of each verse ([build_memory_index.py](build_memory_index.py)). They are ranked by embedding similarity to both your words and the rewrite, which takes milliseconds locally.
4. **Only curated sayings are candidates.** An LLM judged each saying once, offline: can it be said as it is to someone who came to be comforted? 278 were kept. Rebukes, warnings, predictions of persecution, commands and fragments were dropped ([curate_memory.py](curate_memory.py)). A word list also drops judgment and absolution ("your sins are forgiven").
5. Up to three go to the model as a `MEMORY` note. It says one word for word, or none.

The judgment that a per-turn LLM selector used to make (about 1 s) moved to index time. The only LLM call left on the spoken path is the rewrite.

**Two-phase reply.** OpenAI Realtime tool calls are pseudo-synchronous: the model says a short preamble while the tool runs. Phase 5 does the same, but the app controls it. As soon as the transcript arrives, **phase A** speaks one sentence that receives you, with no advice and no scripture. While it plays, the memory is recalled. **Phase B** then continues from what phase A said, with the memory available. Phase A once started on the audio alone, before the transcript, and the model misheard: "favorite scene" became "sin", and "I don't feel happy" was taken as happy. So both phases now get the transcript and are told to trust it.

| version | you stop speaking → his first words |
|---|---|
| serial: rewrite → RAGFlow → LLM selector → reply | 3.5–4.8 s |
| no LLM on the path (selector moved offline, rewrite off) | 1.7–2.8 s |
| two-phase, phase A on the audio alone | 0.5–0.9 s (but misheard) |
| two-phase, phase A on the transcript, rewrite back on (current) | about 1–1.3 s |

**Crisis check in v2.** When it fires, phase A is allowed to finish (it is one short sentence with no scripture), phase B is skipped, and the safety reply follows. Cutting phase A after 0.7 s had sounded like being talked over. Minor injuries ("I hurt my arm") are no longer read as emergencies.

**Debugging.** Each session writes a timeline to `logs/sessions/<time>_<session>.jsonl`. It records voice-activity start and stop, the transcript, both phases, the memory (rewrite, sections and scores, ranked sayings, why nothing was offered, timings), which saying was used and how, playback, every interruption, and every moment the microphone was not sent and why. Text is kept only with `JESUS_LOG_TRANSCRIPTS=true`.

`JESUS_PERSONA=memory` is the default; `JESUS_PERSONA=quote` runs the original persona with its search tool.

## Phase 6: the Jesus avatar

The placeholder is replaced by a Jesus trained for this project. Full notes, in Chinese: [feathertalk_jesus_20261021/README.zh-CN.md](feathertalk_jesus_20261021/README.zh-CN.md) and [Jesus_material/muse_video_20261021/README.zh-CN.md](Jesus_material/muse_video_20261021/README.zh-CN.md).

- **Training clips from Muse.** One photoreal base image, then 24 ten-second speaking clips (22 train, 2 held out) and two silent idle clips, generated on Muse (muse.ai) and downloaded unchanged. Two prompt problems had to be fixed first. Asked for natural small movements, Muse turned the head by up to about 50 degrees, which is useless for training a mouth; the prompt now locks the head "as if braced on a headrest", and every clip is checked for head turn, tilt, shift and scale. Lines of about 22 words finished in 7 seconds, and Muse repeated the last clause to fill the clip; lines are now 26 to 30 words, and every clip is transcribed to check that the line is said exactly once.
- **Trained on the window it runs with.** FeatherTalk reads 20 frames of audio around each video frame, 9 of them in the future. The earlier characters were trained on whole-clip audio and then run without waiting for the future, so the model saw zeros where it had learned to expect speech. Here the realtime wait is capped at 2 frames (80 ms, under the 100 ms limit set for this project), everything later is zeroed, and every training frame is encoded the same way the live session does it, from the same code ([jesus_stream.py](feathertalk_jesus_20261021/jesus_stream.py)). The avatar's `stream80` mode applies the same rule.
- **Choosing the checkpoint.** 150 epochs. Held-out mouth L1 stopped moving after about 30 epochs, so the choice also used lip-sync correlation against the held-out footage (best lag was 0 frames for every checkpoint) and how far the mouth opens. Epoch 60 was picked, with epoch 150 kept as a fallback.
- **The base had to be slowed down.** The idle clip Muse made blinked about 42 times a minute, and the mouth looked like it was twitching. Measured on the mouth region, the generated mouth changed fast (6 to 7 percent of its motion above 6 Hz, against 2.5 to 4 percent in real footage), because the model takes the current idle frame as its reference and that frame was always moving. Asking Muse for fewer blinks did not work. The idle clip is now slowed 1.5 times with motion interpolation, which brings blinking down to about 28 a minute and slows every change of the reference. Of the four versions compared side by side, this one looked best.
- **Live numbers** (RTX 4070 SUPER, 100 ms audio packets): first frame about 145 to 240 ms after the first packet, 250 of 251 frames for 10 seconds of speech, back to idle about 10 ms after an interruption.
- **Known limits.** The model outputs a 144 by 144 mouth, so lips and teeth are softer than in the footage and the mouth opens a little less. The mouth still changes faster than in real footage. The model, the idle frames and the Muse source videos are large and stay local; the scripts, prompts and records that rebuild them are in the repo.

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
python evaluate_replies.py                  # end to end, 3 runs: eval/replies_results.md (about 15 min)
python evaluate_crisis.py                   # crisis check per layer: eval/crisis_results.md
python build_memory_index.py                # his sayings (red-letter spans), embedded: data/memory/
python curate_memory.py                     # one-off LLM judgment of which sayings can comfort
python jesus.py --text                      # typed conversation, with a faithfulness line per reply
python jesus.py                             # voice: default microphone and speaker
docker compose --env-file config.local.env up -d --build --wait avatar   # then open http://127.0.0.1:19388/
python record_demo.py                       # needs OBS with the JesusDemo profile; see the file header
python -m pytest
```

## Next

- Run the end-to-end reply eval on the memory persona; its numbers above come from the first memory trial and from the quote-only persona.
- See [ROADMAP.md](ROADMAP.md) for the rest.

# Development log

不得不说呀，RAG 实在是太容易忘了，就真的雁过无痕、水过无声，在脑子里一点印象都没有。距离我写这个笔记才刚过去两天，我现在又给忘了 Rerank 是干啥的了。我光记得它是做一个精排，比如从 50 个里面挑 5 个，但是它具体在技术上怎么做的，我又给忘干净了。

所以这边就基于那个 Jesus 项目，顺手说一下吧。

以"房租"这道题为例：

用户说："I can’t sleep because I keep thinking about how I’ll pay rent next month."
（我一直在想下个月房租怎么付，睡不着。）

正确答案应该是 Matthew 6:34："不要为明天忧虑……"

### 把原quota找个小LLM模型做改写

先看下改写吧。

改写这边是调了一个小模型（我用的是 GPT 5.4 Mini），给它一段指令让它自由写一段检索词。这个没有固定分组，不是一开始就分什么 friends、family 这种，就是写了一段 prompt。

我这边大概是让它把用户的话改写成一句用来搜文档的查询：

指令原文在 retrieval.py 里：

把用户的话改写成一句用来搜四福音书的查询。说出背后的人的需要，以及耶稣谈到过的主题，用现代英文圣经会用的朴素词语，再加几个具体关键词。不要猜章节号。25 个词以内。

这次模型现场写出来的是：

“worry about money and rent, sleepless fear, trust God’s care, daily needs, anxiety, provision”

主要是因为四福音书跟现在的英文口语实在对不上，所以必须得有改写。后来做了 ablation study，反正不管其他的变量怎么变，每次加了改写的都比不加好太多了

注意它做的事：用户嘴里说的是"房租"”睡不着"，这些词经文里没有；改写把它翻译成了经文会用的说法："worry"（忧虑）、"daily needs"（日用所需）、"provision"（供应）。

为什么不用固定分类？ 因为分类是死的。"我对我妈说了难听话"该归"家庭"还是"愧疚"还是"愤怒"？三个都有。自由改写可以同时写出"guilt, hurting family, anger, reconciliation"，不用硬塞进一个格子。

### 向量和语义空间：空间不是人划分的，是模型学出来的

向量：embedding 模型（text-embedding-3-small）把任何一段文字变成 1536 个数字，刚才跑出来的长度就是 1536。

语义空间：你可以把它想象成一张 1536 维的地图，每段文字都是地图上的一个点。这张地图没有人去规定"第 3 维代表家庭、第 7 维代表金钱"，每一维也没有人能叫出名字。模型是在海量文本上训练出来的，学到的唯一规则是：意思相近的文字，位置就靠近。

相似度：两个点有多近，用"余弦相似度"量，越接近 1 越像。

---

我这边先补充一下：其实项目里处于从 0 到 1 的阶段出的结果真的很乱。所以我再简单把流程梳理说明一下。

各种东西为了追求效果叠在一起，让整个事情变得非常 chaotic.

先说一下，之前一直说的那个全文检索，其实就是 BM25;

step 1 生成 487 个段落文件（pericopes.py）

每个 BSB 段落存成一个文本文件，第一行是标题，后面每行一节经文。这是一个真实的文件：

Matthew 11:25-30 · Rest for the Weary

Matthew 11:25 At that time Jesus declared, "I praise You, Father, ...

Matthew 11:26 Yes, Father, for this was well-pleasing in Your sight.
...

Matthew 11:28 Come to Me, all you who are weary and burdened, and I will give you rest.

Matthew 11:29 Take My yoke upon you and learn from Me, ...

Matthew 11:30 For My yoke is easy and My burden is light."

统计一下这 487 个段落，一个段落一般就是一个小故事或一段讲话：

| | 最短 | 中位数 | 平均 | 最长 |
|---|---|---|---|---|
| 节数 | 2 节 | **6 节** | 7.7 节 | 37 节 |
| 英文词数 | 26 词 | **135 词** | | 808 词 |

135 个英文词，大概就是**中文一小段话的长度**，读出来不到一分钟。按长度分布：

| 每段节数 | 段落数 |
|---|---|
| 1–3 节 | 86 |
| 4–6 节 | 166 |
| 7–10 节 | 115 |
| 11–20 节 | 108 |
| 21 节以上 | 12 |

超过 20 节的只有 12 段，都是很长的对话或讲论。最长的三段是"生命的粮"（John 6，37 节）、"文士和法利赛人有祸了"（Matthew 23）、"撒玛利亚妇人"（John 4）。

"劳苦的人得安息"这个段落一共 6 节，就是刚才看到的那个文件：

```
Matthew 11:25-30 · Rest for the Weary            ← 标题行（也算一个子块）
Matthew 11:25 At that time Jesus declared, ...   ← 子块
Matthew 11:26 Yes, Father, ...                   ← 子块
Matthew 11:27 All things have been entrusted ... ← 子块
Matthew 11:28 Come to Me, all you who are weary  ← 子块
Matthew 11:29 Take My yoke upon you ...          ← 子块
Matthew 11:30 For My yoke is easy ...            ← 子块
└──────────────── 整个文件 = 一个父块 ────────────────┘
```

- **子块**就是文件里的**一行**：一节经文，或者标题行。检索时用子块来匹配，因为一行意思集中，好对上。
- **父块**就是**整个文件**，也就是整个段落。某一行被命中后，交出去的是整个段落，这样模型能看到上下文：比如 11:28 前面的 11:25 是耶稣在祷告，后面的 11:29 讲"负我的轭"。

项目里，"块"其实很直观：**子块 = 一节经文，父块 = 一个带小标题的段落。**

## Jesus 整体流程

先讲整体的大流程，细节后面再补充。

整个流程从用户输入一句话（原文）开始：

1. 改写输入
用一个小的生成式 model，配合刚才提到的 prompt，对用户的原始输入进行改写。

2. 检索段落（RAG flow）
这一步分为两个小阶段：
(a) 初筛出 30 个 candidate。
(b) 进行 rerank，最终返回 3 个结果及其 rerank score（with their rerank score）。要求 score 必须高于 0.3，不高于 0.3 的段落直接丢弃。

3. 匹配耶稣原话
根据段落 ID 到知识库中查询这 3 个段落对应的耶稣原话。比如找到了 15 句，但因为之前已经做过一轮筛选，需要检查这 15 句是否在预设的 278 句范围内：在的话保留，不在就直接剔除。经过这一步后，假设只剩下 5 句候选。

4. 候选排序并取 Top 3
在本地花几毫秒单纯比对向量相似度，对剩下的 5 句候选排个序，取前 3 句交给模型。

补充说明：为什么第 4 步还要拿改写后的原话去做向量相似度排序？
虽然当前例子里只有 5 句，全塞进一条 memory 给模型也能处理，但常规情况下候选句可能多达 20 几句，直接全塞进 memory 会给模型造成负担。所以加了这一步相似度比对并排序，筛选出 Top 3。反正就是得把它的输出量给标准化嘛。

因为之前去挑、去 match，谁知道它会出来一个什么结果呢？少了无所谓，但万一很多，你让模型怎么办呢？

它那个 real-time 的 context window 也得控制啊。你 context 炸了，时延就长了；时延一长，沉浸感就差很多了.

补充一下，第四步这边的重新排序其实迭代了好几版：

第一版原本是用 cross-encoder 的 model 来调，后来又找了一个小模型来看它们是不是有关系。它本来是一个保全策略，但太慢了，得花一秒，体验很不好。

现在用的是本地的向量排序，就是为了让它能快速开口，目前几毫秒就可以搞定。

如果换成 Voyage 重排就是来算当前筛出来的这几句话单独是不是跟用户谈的这件事情有关系，claude code 估了一下大概要 150 多毫秒。这在效果上确实可以改进，但 trade-off 就是要多花大概 100 多毫秒

5. 组装 Memory 并由模型输出
将排名前 3 的内容作为 memory 输入给模型。Prompt 中要求模型在进入第二阶段回复时，最多挑一句并逐字说出来，不用自己发挥。因为这里要求完全还原原文，所以会通过相似度比对来作为一个 evaluation 指标。

如果跑完这么一套流程，实在是连一句耶稣原话都没有，那也行，就什么都不给。

这个会在最后 real time 那边的 prompt 里写明，直接不引用了.

<img width="945" height="186" alt="image" src="https://github.com/user-attachments/assets/d39402f0-6075-4029-9129-0d8ffab8d951" />

上面这张图是拿那 55 个 ground truths 跑出来的结果分析。

针对那 14 道题，这其实不是检索的问题，RAGFlow 那边找的段落是对的。但因为段落里对应的耶稣原话不在那 278 句里，所以出了问题。

补充说明一下那 278 句的筛选规则：核心是看“能不能原样对一个寻求安慰的人说”。原文里很多耶稣原话确实没法直接说，比如“要爱你们的仇敌”、“要饶恕他 70 个 7 次”，像这类的就被过滤掉了。其实这个也是我的原因。我确实不太乐意把它搞成一个……就是我真的不太乐意让它听起来像是说教的。

我确实对宗教不是很了解，但我对“人机恋”这个群体还是很了解的。反正我在人机恋的圈子里，就看到大家跟不同的模型会有一些情感上的连接。经常会有说换了模型、或者模型降智、又或者被暗改路由到不知道那里去了，反正各种各样的事情，导致用户被模型“创”到。

这样不好，就是不好。所以我这边就尽可能让它走一个更加温和的路线了

以及，再怎么样也得考虑一下 scenario：我们这个 scenario 一开始就是冲着 voice companion 来的，它毕竟不是一个真的 Jesus。

不过这个无所谓，都很好改：把那 278 句扩充一下，再把筛选规则放宽一点就行。这些都能调整，不是什么大问题。

最终模型生成回复并呈现给用户，这就是完整的大致流程

### 0.导入。生成段落文件+四道工序给RAGFlow

先看代码，按实际实现来讲，不凭印象：

再拿一个真实的段落文件，并把一次检索的分数逐项打印出来：

先纠正一个误会：**你其实一直在用 BM25。** 阶段 1 那个我手写的 BM25 已经不用了，但 RAGFlow 的"全文检索"本身就是 BM25 类的关键词打分，由 Infinity 内置。它在混合检索里占 0.3 的权重。

下面分成"导入时做了什么"和"每次查询时做了什么"两部分。

---
导入时（离线，只做一次）

**1. 生成 487 个段落文件**（`pericopes.py`）

每个 BSB 段落存成一个文本文件，第一行是标题，后面每行一节经文。这是一个真实的文件：

```
Matthew 11:25-30 · Rest for the Weary
Matthew 11:25 At that time Jesus declared, "I praise You, Father, ...
Matthew 11:26 Yes, Father, for this was well-pleasing in Your sight.
...
Matthew 11:28 Come to Me, all you who are weary and burdened, and I will give you rest.
Matthew 11:29 Take My yoke upon you and learn from Me, ...
Matthew 11:30 For My yoke is easy and My burden is light."
```

**2. 上传给 RAGFlow，它按 4 道工序处理**（参数在 `ingest_ragflow.py` 里）

| 工序 | 做什么 | 你的设置 |
|---|---|---|
| Parser | 读文件 | 普通文本 |
| GeneralChunker | 切块 | **整个文件是一个父块**；**按换行切出子块**，每节经文一个子块 |
| Extractor | 调 LLM 给每个块加内容 | 每块生成 **5 个关键词**和 **3 个"可能会被问到的问题"** |
| Tokenizer + Embedding | 建两种索引 | **全文索引**（把词拆开、记下每个词出现在哪里、有多常见）；**向量索引**（`text-embedding-3-small` 生成 1536 维向量） |

以 Matthew 11:28 这个子块为例，它在 Infinity 里大概存着这些：

- 经文原文："Come to Me, all you who are weary and burdened…"
- LLM 生成的关键词，类似：weary, burdened, rest, invitation, comfort
- LLM 生成的问题，类似："Where can I find rest when I'm exhausted?"
- 一个 1536 维的向量
- 它属于哪个父块（"Rest for the Weary"这个文件）

（具体是哪 5 个关键词、哪 3 个问题，是当时 LLM 生成的，上面只是示意。）

**全文检索为什么这次有用？** 阶段 1 的 BM25 只能匹配经文原文的字，而"burned out"这种词经文里根本没有。现在每个块多了 LLM 写的关键词和问题，里面有很多现代说法，关键词匹配就有东西可对了。

---

## 二、每次查询时（以"我累垮了"为例）

```
改写后的查询："Jesus rest for the weary, burden, heavy heart, tired and burned out, ..."
        │
        ▼
① 在 Infinity 里同时做两路检索，对象是所有子块
   ├─ 全文（BM25）：查询里的词和块里的词（原文+关键词+问题）重合了多少，越少见的词越值钱
   └─ 向量：查询向量和块向量在语义空间里有多近
        │
        ▼
② 合并：总分 = 0.3 × 全文分 + 0.7 × 向量分，取前 30 个候选
        │
        ▼
③ Voyage 重排：把查询和这 30 个候选逐个"一起读"，重新打分、重新排序
        │
        ▼
④ 每个段落只留一个（多节经文都命中同一段时，不重复算），取前 3
        │
        ▼
⑤ 拒答判断：第一名的分数 < 0.30 → 一个都不返回
        │
        ▼
⑥ 子块命中 → 返回它所属的整个段落（父块）
```

刚才实际跑出来的前 5 名，对比加不加重排：

| 排名 | 只用混合检索 | 分数 | 加上重排 | 分数 |
|---|---|---|---|---|
| 1 | 劳苦的人得安息 Matthew 11:25 | 0.767 | 劳苦的人得安息 Matthew 11:25 | 0.519 |
| 2 | 差遣七十二人 Luke 10:1 | 0.756 | 我留下平安给你们 John 14:27 | 0.484 |
| 3 | 我留下平安给你们 John 14:27 | 0.755 | 喂饱五千人 Mark 6:30（"来歇一歇"） | 0.445 |
| 4 | 客西马尼园祷告 Matthew 26:36 | 0.751 | 奉我的名求 John 16:23 | 0.413 |
| 5 | 差遣十二门徒 Matthew 10:5 | 0.749 | 撒玛利亚妇人 John 4:1 | 0.402 |

从这张表能直接看出两件事：

1. **重排改变了排名**：只用混合检索时，第 2 名是"差遣七十二人"，和"累垮了"没什么关系，大概是因为里面有"平安"这类词。重排把它挤了出去，换上了"来歇一歇"这种真正贴题的段落。
2. **重排把分数拉开了**：混合检索的 5 个分数挤在 0.749–0.767 之间，几乎分不出好坏；重排后从 0.519 一路排到 0.402，差距明显。这就是为什么"低于 0.30 就拒答"的门槛只能设在重排分数上。

另外说明一下：RAGFlow 1.0 返回的结果里虽然有"全文分""向量分"两个字段，但实际值和总分一模一样，**拿不到两路各自的分数**。所以上面没法列出 0.3 和 0.7 各贡献了多少，这是这个版本 API 的限制。

### rerank 用的是个transformer 模型

"凭什么"打得准？因为它就是专门为这件事训练出来的。 训练数据是海量的"问题 + 段落 + 是否相关"三元组，来源包括搜索引擎里人们点了哪个结果、人工标注、更大的模型给出的判断等等。训练目标很简单：相关的配对打高分，不相关的打低分。看了几百万个例子之后，它就成了一个专门判断"相关不相关"的阅卷老师。

（Voyage 是闭源模型，具体用了哪些训练数据没有公开；上面说的是这类重排模型的通用原理，业内叫 cross-encoder，向量检索那种叫 bi-encoder。）

那为什么不全部用重排？ 因为太慢。它必须在提问的那一刻把问题和每个候选逐对读一遍，没法提前算好。四福音书有几千节，全读一遍来不及。

注意一下，这个项目在第二步 RAG flow 找段落那个部分，是先用混合检索粗筛，然后再重排（Rerank）的。

在第四步挑耶稣的话的时候，他只是用了一个本地的向量相似度,因为这样快，而且它真的不需要那么大的算力，只需要几毫秒。

如果用 Voyage 重排的话，不仅计算量更大，还要再走一次网络，耗时仍然会比这个多一点，其实完全没必要

---
这个注意一下：那 30 个 candidate 是“块”，不是 30 个不同的段落。

其实确实得用“块”，不能说“节”，因为里面的 subtitle 也作为一个独立的东西算作子块了，所以用“节”不好描述，统一都用“块”吧。我们就说拿到这 30 个子块。

对，是 30 个，但要说清楚两个细节。代码里相关的参数是（`ragflow_retrieval.py`）：

```python
"keywords_similarity_weight": 0.3,   # 全文（BM25）占 0.3，向量占 0.7
"rerank_candidates_count": 30,       # 混合检索的前 30 名交给重排
"page_size": max(k * 3, 10),         # k=3，所以重排后返回前 10 个
```

完整的数量变化是这样的：

```
所有块
  │ 混合检索：0.3 × BM25 + 0.7 × 向量
  ▼
前 30 个候选子块 ──→ Voyage 逐个重排
  │
  ▼
重排后的前 10 个子块（RAGFlow 返回给你的程序）
  │ 你的代码：同一个段落只留一个(这边代码设定是它 rerank 之后再次算关键词分+Voyage分权重总得分，要前 10 个。因为如果设定少了，对应段落去重回来的全都是同一个段落，这样就不太好了)
  ▼
从合并到的所有段落里，按平均分排序，只要前 3 个段落（再判断第一名是否 ≥ 0.30， 如果第一个都低于0.3，就全部不要； 当时的思路是：0.30 是用来判断"这个问题本身该不该回答"的，不是用来筛选单个段落的。

它的标定方法就能说明这一点：拿 55 道真实问题和 10 道离题问题（比如"芝加哥天气怎么样"），只比较每个问题的第一名分数：

真实问题的第一名，最低是 0.314；
离题问题的第一名，最高是 0.287。
0.30 刚好卡在两者中间。所以它回答的是"这个问题和四福音书有没有关系"：第一名都不到 0.30，说明整本福音书里都找不到相关的内容，干脆不回忆。第一名过了线，说明问题是相关的，就把前 3 个都交给下一步。）
```

上面那个平均分在源码有写：合并完之后，RAGFlow 会按段落的平均分从高到低重新排序（源码注释就写着 Sort by similarity descending）。

平均分是这么来的：

前 10 个子块，每个都有一个最终分（0.3 × 关键词分 + 0.7 × Voyage 分）。属于同一个段落的那几个子块，把它们的最终分加起来再除以个数，就是这个段落的分数。

拿到前面的前三个段落之后，再去找它们对应的 278 个耶稣亲口说的话。接着把他说过的这些话，用本地几毫秒的向量相似度重新排序，再取前三个送给模型。

---
权重其实用了两次，两次都是针对子块：

第一轮，选 30 个候选时：每个子块的分数 = 0.3 × 关键词分（BM25） + 0.7 × 向量分，按这个分数取前 30 个子块。

第二轮，重排之后：每个子块的分数 = 0.3 × RAGFlow 自己写的关键词重合度（TokenSimilarity） + 0.7 × Voyage 分，按这个分数取前 10 个子块。

<img width="847" height="212" alt="image" src="https://github.com/user-attachments/assets/4d238a6a-f01d-4091-a2e3-7989f62976d8" />

BM25 是两部分相乘，"这个词在这一块里出现得多不多" × “这个词在整个库里有多稀有”。第二部分就是你说的"比例"，叫 IDF。

但要纠正一个细节：这个比例不是按 400 多个段落算的，是按大约 3,800 个子块（一节一节的经文）算的。 因为 Infinity 里真正被索引、被搜索的单位是子块，段落（父块）只是最后用来拼回去的。

举个例子：

“weary”（劳苦）只在少数几节经文里出现，非常稀有。一旦匹配上，就是很强的信号，分数高。
“the”几乎每节都有，太常见了，匹配上也几乎不加分。

（实际公式还多做了两件事：一个词重复很多次，分数不会无限涨，会封顶；一块越长，单个词的分量越轻。这样长经文不会因为字多而占便宜。）

BM25（第一轮，选 30 个候选时用）它问的是："这一块里有你的词吗？有的话，这些词有多珍贵？"

对查询里的每个词，算一个分，再全部加起来：这个词的分 = 稀有程度 × 在这一块里出现的次数

稀有程度：在全部约 3,800 节经文里，有多少节含有这个词。越少越珍贵。

“weary”只有几节有 → 很珍贵，分高

“heart”有很多节都有 → 普通，分低

出现次数：在这一节里出现了几次。但有封顶，出现 10 次不会是 1 次的 10 倍。而且一节越长，每个词的分量越轻。哦，它这个是按“节”算的，因为这个“节”在这里面就是子块的意思。这是因为在第一步初筛、到 rerank 之前，它筛出来的这些东西，最终要拿出来的结果是子块，而不是一个一个段落。所以它这里面才会说是按照那 3000 多个子块来算的

这一节里含有 weary、burden、rest 三个词，都比较稀有，所以总分高。

特点：看全局的稀有程度，分数没有上限，是 Infinity 数据库自带的功能。

---

第二个：关键词重合度（第二轮，重排之后用）

它问的是："你的问题里，有百分之多少的词，在这一块里出现了？"

做法：

给查询里每个词一个重要性权重（RAGFlow 自己算的，大致也是越特别的词越重要）；
看这一块（经文原文 + 标题 + LLM 生成的关键词和问题）里有没有这个词，只看有没有，不数次数；
出现了的词的权重之和 ÷ 所有查询词的权重之和。

假设权重是 weary 3、burden 3、rest 2、heart 2、peace 1，总共 11：

这一节出现了 weary、burden、rest → (3 + 3 + 2) ÷ 11 = 0.73

（还有一个小细节：两个相邻的词组成的词组，比如"heavy heart"，如果整个词组都匹配上，会额外加分。所以短语完整匹配比只零散匹配上几个字更值钱。）

特点：结果在 0 到 1 之间，表示"问题被覆盖了多少"；不数次数，只在那 30 个候选里算。


为什么第二轮要换成重合度？因为它要和 Voyage 的分数相加，而 Voyage 的分数在 0 到 1 之间。BM25 没有上限，直接加会乱套；重合度天然就在 0 到 1 之间，可以直接按比例混合。

<img width="845" height="305" alt="image" src="https://github.com/user-attachments/assets/ba02eeb4-8272-4e35-a660-df6fddaee6e6" />


---

**细节 1：这 30 个是"块"，不是 30 个不同的段落。**

同一个段落里可能有好几节经文同时被命中。比如 Matthew 11:28、11:29、11:30 都和"累垮了"很像，它们会各占一个名额。所以 30 个候选块可能只来自十几个段落。这就是为什么 RAGFlow 返回 10 个之后，代码还要按段落去一次重，才剩下 3 个。

**细节 2：重排读的是是单节经文，即为子块。**

另外，这三个数字（0.3、30、10）都是可以调的参数。0.3 是在消融实验里比较 0.3 和 0.7 之后定下来的；30 和 10 当时没有专门做实验，用的是经验值。

---

等一下，谈到这儿事情还没完，我好生气啊！

我之前光看他跟我谈话输出的效果，觉得还挺可以的，挺符合那种 Jesus 该有的形象。对不起啊，我确实不是一个非常懂这边文化的人，我是按照类似于天父那样仁慈、慈悲、非常亲和的印象来判断的。

可是今天把上面这么一大串逻辑走了一遍，看他怎么挑段落、怎么送给模型，我才发现事情非常不对。我第二版的 prompt 搞错了，完全走歪了。当时我光看结果，那天实在太晚，我又急着弄别的事就没好好搞，对不起。

现在得写第三版 prompt 了。第二版纯粹是从 278 个句子里挑，那这整件事有什么意义呢？我直接把那 278 句话送给 real-time model 不好吗？哪怕是拿那两千多句耶稣亲口说的话，两千多句也不是很大的 token 啊。直接送给模型让它去判断，不比现在这么绕一大圈脱裤子放屁更好吗？哎呦，我就是气得没办法了，真是气得脑袋疼

而且这也违背了我的初衷。我之所以坚持要从四福音书里挑子块，是因为我希望这个人物说话时是带有背景的，而不是单独抛出一句话。单单一句话放在不同的情境、不同的身份下，表达的意思完全不一样。我之所以要从段落里取，就是希望他带着上下文背景，去贴合用户真正在聊的事情。

所以现在得重新改了。唉，这就是技术债吧。要不是今天从头到尾跑了一遍，我还真没发现它跟我的本意差了这么多

更生气了。

因为要他改嘛，然后他跟我说在 v2 版本里面，那个 prompt 他居然手写了这次的一些经历，手写了十段！

我说怎么那时候验收的时候，明明当时我真的觉得效果还挺好，觉得他说得特别像，“当他在什么时候，遇到了一个什么事情”。刚才我还以为是我的幻觉或者我记错了，结果这玩意儿居然是手写的吗？哎呀，我真的要生气了！
