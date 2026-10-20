# JesusSaysHi

An experimental spin-off of [SpecterSaysHi](https://github.com/YeChen-coder/SpecterSaysHi): the same real-time voice + avatar framework, with Jesus as the character, built around retrieval.

## Why RAG belongs here

Specter's character comes from its relationship with one person. What it needs to know is small and keeps changing, so a couple of summary files fit in the prompt, and RAG would be over-engineering.

This character comes from a fixed text instead. The four Gospels hold about 3,800 verses, which is too much for a prompt. They have to be quoted exactly, with a reference. So the persona rule is: **Jesus speaks in the first person, but the substance of every answer must come from retrieved scripture.** He may add only a short bridging line of his own. Retrieval is the constraint that defines the character, not a bolt-on feature.

## Status: phase 1, text-only retrieval and eval

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

## Run it

```bash
pip install -r requirements.txt
cp config.example.env config.local.env      # point JESUS_EXISTING_ENV at a .env holding OPENAI_API_KEY
curl -o data/raw/bsb.txt https://bereanbible.com/bsb.txt
python build_index.py                       # about 1 minute, well under a cent
python ask.py "I'm exhausted and everything feels heavy" --rewrite
python evaluate.py                          # rewrites eval/results.md
python -m pytest
```

## Next

- **Phase 2:** take the voice loop from SpecterSaysHi, turn retrieval into a `search_scripture` tool, write the persona prompt and the hard safety boundaries, and add a check that compares what was spoken against the retrieved verses.
- **Phase 3:** add the FeatherTalk avatar with Jesus assets, show an on-screen card with the cited verse, and record a scripted demo.
