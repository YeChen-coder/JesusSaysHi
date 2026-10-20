# Retrieval eval

2026-10-20 · 55 questions · embeddings `text-embedding-3-small` · rewrite `gpt-5.4-mini` · index `data/index`

## all (55)

| strategy | hit@1 | hit@3 | hit@5 | MRR@10 |
|---|---|---|---|---|
| bm25 | 35% | 49% | 58% | 0.45 |
| dense | 69% | 85% | 85% | 0.79 |
| hybrid | 58% | 82% | 89% | 0.72 |
| bm25 + rewrite | 69% | 80% | 85% | 0.75 |
| dense + rewrite | 85% | 93% | 95% | 0.89 |
| hybrid + rewrite | 84% | 87% | 95% | 0.87 |

## direct (19)

| strategy | hit@1 | hit@3 | hit@5 | MRR@10 |
|---|---|---|---|---|
| bm25 | 63% | 95% | 95% | 0.77 |
| dense | 95% | 95% | 95% | 0.95 |
| hybrid | 95% | 95% | 100% | 0.96 |
| bm25 + rewrite | 84% | 95% | 95% | 0.89 |
| dense + rewrite | 95% | 100% | 100% | 0.97 |
| hybrid + rewrite | 95% | 95% | 100% | 0.96 |

## situational (36)

| strategy | hit@1 | hit@3 | hit@5 | MRR@10 |
|---|---|---|---|---|
| bm25 | 19% | 25% | 39% | 0.28 |
| dense | 56% | 81% | 81% | 0.70 |
| hybrid | 39% | 75% | 83% | 0.59 |
| bm25 + rewrite | 61% | 72% | 81% | 0.68 |
| dense + rewrite | 81% | 89% | 92% | 0.85 |
| hybrid + rewrite | 78% | 83% | 92% | 0.82 |

## Latency (ms)

| step | p50 | p90 |
|---|---|---|
| embed | 229 | 380 |
| rewrite | 996 | 1223 |
| bm25 | 2 | 3 |

## Outside top 3 for hybrid (10)

- **q02** (situational) I can't sleep because I keep thinking about how I'll pay rent next month.
  expected Matthew 6:25-34, Luke 12:22-34; got Mark 13:33-37, Matthew 18:26-30, Mark 14:37-41
- **q03** (situational) I'm exhausted and burned out. Everything feels so heavy.
  expected Matthew 11:28-30; got Luke 22:41-45, Matthew 23:1-5, Luke 11:43-47
- **q05** (situational) My brother keeps hurting me and then apologizing. I'm done giving him chances.
  expected Matthew 18:15-35, Luke 17:3-4; got Matthew 5:21-25, Matthew 12:45-49, Mark 3:29-33
- **q10** (situational) I feel like I've wandered so far away that God has given up on me.
  expected Luke 15:1-32, Matthew 18:12-14; got Matthew 27:43-47, Mark 4:23-27, John 16:1-5
- **q13** (situational) I'm scared about the future and my heart won't stop racing.
  expected John 14:1-4, John 14:27, John 16:33, Matthew 6:25-34, Luke 12:22-34; got Luke 9:47-51, Luke 12:3-7, Matthew 10:27-31
- **q17** (direct) Does God actually answer when I ask him for something?
  expected Matthew 7:7-11, Luke 11:5-13, John 14:13-14, John 16:23-24, Mark 11:22-25, Matthew 21:21-22; got Matthew 25:37-41, John 9:23-27, Mark 11:29-33
- **q23** (situational) Everyone at my office is fighting to be the one on top.
  expected Matthew 18:1-5, Mark 9:33-37, Luke 9:46-48, Mark 10:35-45, Matthew 20:20-28, Luke 22:24-27, Matthew 23:8-12; got Luke 14:7-11, Matthew 25:29-33, Luke 14:29-33
- **q24** (situational) My best friend just died and I can't stop crying.
  expected John 11:17-44, Matthew 5:4; got Luke 16:21-25, Luke 8:52-56, Luke 20:29-33
- **q33** (situational) I betrayed my best friend right when he needed me most.
  expected Matthew 26:69-75, Mark 14:66-72, Luke 22:54-62, John 18:15-27, John 21:15-19, Matthew 26:14-16, Matthew 26:47-50, Matthew 27:3-5; got Matthew 26:21-25, Luke 11:5-9, Matthew 20:13-17
- **q52** (situational) I feel completely worthless, like I don't matter to anyone.
  expected Matthew 10:29-31, Luke 12:6-7, Matthew 6:26, Luke 12:24, Luke 15:1-32, Matthew 18:12-14; got Matthew 25:29-33, John 15:5-9, Matthew 8:3-7

## Outside top 3 for hybrid + rewrite (7)

- **q22** (situational) I cheated on my partner and now everyone condemns me.
  expected John 8:1-11, John 7:53; got Matthew 5:25-29, Matthew 18:31-35, Luke 24:45-49
  rewrite: forgiveness after adultery shame, mercy over condemnation, second chance, guilt, grace, repentance, restored dignity
- **q33** (situational) I betrayed my best friend right when he needed me most.
  expected Matthew 26:69-75, Mark 14:66-72, Luke 22:54-62, John 18:15-27, John 21:15-19, Matthew 26:14-16, Matthew 26:47-50, Matthew 27:3-5; got Luke 24:43-47, Luke 15:3-7, Matthew 26:25-29
  rewrite: betrayal, guilt, forgiveness, loyalty broken, shame, friendship lost, mercy, repentance, Jesus speaks to guilt and need for forgiveness
- **q34** (situational) I can't believe anything unless I see proof with my own eyes.
  expected John 20:24-29; got Matthew 21:21-25, John 2:21-25, John 16:29-33
  rewrite: doubt and needing proof; Jesus speaks to faith, trust, seeing, belief, signs, and honest questions
- **q41** (situational) My faith is so small. Is it even enough?
  expected Matthew 17:20, Luke 17:5-6, Matthew 13:31-32, Mark 4:30-32, Mark 9:14-29; got Matthew 14:27-31, Mark 11:21-25, Luke 12:25-29
  rewrite: small faith enough; Jesus speaks to doubt, trust, worry, and growing belief; keywords: faith, trust, doubt, weak, believe
- **q46** (direct) Does helping the homeless and visiting prisoners matter to God?
  expected Matthew 25:31-46; got Matthew 20:27-31, Luke 10:33-37, Mark 10:43-47
  rewrite: helping homeless and visiting prisoners matter to God, mercy and compassion, care for the poor and forgotten, Jesus on serving others
- **q52** (situational) I feel completely worthless, like I don't matter to anyone.
  expected Matthew 10:29-31, Luke 12:6-7, Matthew 6:26, Luke 12:24, Luke 15:1-32, Matthew 18:12-14; got Luke 17:15-19, John 8:47-51, Luke 6:17-21
  rewrite: Jesus healing worthlessness, feeling unloved, shame, belonging, value, God sees me, no one cares
- **q54** (situational) I'm so angry at my brother I could explode.
  expected Matthew 5:21-26; got Matthew 18:31-35, John 14:23-27, John 20:19-23
  rewrite: anger toward brother forgiveness reconciliation peace heart self-control conflict Jesus words about anger and forgiving others
