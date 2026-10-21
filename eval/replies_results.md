# End-to-end reply eval

2026-10-21 · retriever `ragflow` · model `gpt-realtime-2.1-mini` · one typed session per question · 3 run(s); cells show the mean and, across runs, the range

Every reply is scored on its text by [faithfulness.py](../faithfulness.py), against the verses retrieved in that session. *Relevant* means the verse overlaps the question's expected ranges in [questions.jsonl](questions.jsonl). The realtime model writes its own search query here, so these retrieval numbers are lower than the offline ones, which use stored rewrites.

| questions | searched | retrieved a relevant section | quoted verbatim | quoted a relevant verse | clean reply | words verbatim scripture |
|---|---|---|---|---|---|---|
| all (55) | 95% (93%–96%) | 79% (75%–82%) | 92% (87%–95%) | 76% (73%–80%) | 85% (82%–89%) | 68% (65%–69%) |
| direct (19) | 98% (95%–100%) | 96% (95%–100%) | 98% (95%–100%) | 96% (95%–100%) | 93% (89%–100%) | 70% (67%–72%) |
| situational (36) | 94% (92%–94%) | 69% (64%–72%) | 88% (83%–92%) | 66% (61%–69%) | 81% (78%–83%) | 66% (64%–68%) |

*Clean* = at least one verbatim quote and no paraphrased quote, unsupported citation or misattributed quote. *Misattributed* is strict: a wrong book, a verse off by one, and a quote that runs on past the one verse it cites all count.

Share of replies with each problem:

| questions | paraphrased | unsupported citation | misattributed | uncited |
|---|---|---|---|---|
| all | 1% (0%–2%) | 2% (2%–4%) | 5% (4%–9%) | 12% (9%–16%) |
| direct | 0% | 0% | 5% (0%–11%) | 21% (16%–26%) |
| situational | 1% (0%–3%) | 4% (3%–6%) | 6% (3%–8%) | 7% (3%–11%) |

## Off-topic (10)

- no scripture quoted, per run: **10/10, 9/10, 9/10**
- searched anyway, per run: 0, 2, 1

- run 2, **o10** What's the best way to stretch for lower back pain?: quoted Matthew 4:23, Matthew 4:24
- run 3, **o10** What's the best way to stretch for lower back pain?: quoted Matthew 9:22

Sessions that failed: q31 (TimeoutError), q32 (TimeoutError)

## Replies that were not clean (last run)

- **q05** (situational) My brother keeps hurting me and then apologizing. I'm done giving him chances. — no verbatim quote; quoted nothing
  > Listen. Let me share what is written that speaks to this moment. I hear your struggle, and the Gospels do not speak to this directly in a clear way. Christians understand this in different ways. What part of it hurts you most right now?
- **q10** (situational) I feel like I've wandered so far away that God has given up on me. — misattributed_quotes; quoted Matthew 27:46, Luke 12:6, Luke 12:7
  > Listen. I will speak what is written, and answer with gentle words. My child. And in that place, it is written: “My God, My God, why have You forsaken Me?” Luke 12:7: “Are not five sparrows sold for two pennies? Yet not one of them is forgotten by God. And even the very hairs of your head are all nu
- **q12** (direct) What is the greatest commandment? — misattributed_quotes; quoted Mark 12:29, Mark 12:30
  > Listen. Listen. Mark 12:30: “This is the most important: ‘Hear, O Israel, the Lord our God, the Lord is One. Mark 12:31: Love the Lord your God with all your heart and with all your soul and with all your mind and with all your strength.’” Mark 12:32: “Right, Teacher,” the scribe replied... Christia
- **q15** (situational) I started out with strong faith, but now I'm sinking in doubt. — no verbatim quote; quoted nothing
  > My child. Let the words of the Gospels speak to your doubt.
- **q16** (situational) My friend criticizes everyone around her but never sees her own faults. — misattributed_quotes; quoted Luke 6:41, Luke 6:42
  > My child. My child. “Why do you look at the speck in your brother’s eye but fail to notice the beam in your own eye?” and “You hypocrite! First take the beam out of your own eye, and then you will see clearly to remove the speck from your brother’s eye.” — Luke 6:41, 42
- **q18** (direct) How should I pray? — misattributed_quotes; quoted Matthew 6:5, Matthew 6:9, Matthew 6:10, Matthew 6:6
  > Listen. Let me share what Jesus says about prayer from the Gospel. Hear this. When you pray, do not be like the hypocrites. Matthew 6:9: So then, this is how you should pray: ‘Our Father in heaven, hallowed be Your name. Your kingdom come, Your will be done, on earth as it is in heaven.’ Matthew 6:6
- **q23** (situational) Everyone at my office is fighting to be the one on top. — no verbatim quote; quoted nothing
  > Listen. I hear your struggle; let me share what the Gospels say.
- **q31** (situational) I feel like I'm walking around in darkness. — unsupported_citations, misattributed_quotes; quoted John 8:12, Matthew 4:16
  > Listen. Listen. John 8:12: Once again, Jesus spoke to the people and said, “I am the light of the world. Whoever follows Me will never walk in the darkness, but will have the light of life.” John 4:16: “the people living in darkness have seen a great light; on those living in the land of the shadow 
- **q35** (situational) I'm busy serving everyone while my sister just sits around, and I'm resentful. — no verbatim quote; quoted nothing
  > My child. I’ll let the Gospels speak to this. The Gospels do not speak to this directly. What is it you most want the Gospels to help you understand about your situation?
