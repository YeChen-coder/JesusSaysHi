# Why do the details drift? Mini against the full realtime model

2026-10-26 · the 10 conversations of [evaluate_episodes.py](../evaluate_episodes.py) at the 0.30 recall threshold,
typed sessions · each told memory judged claim by claim by `gpt-6-sol` ([evaluate_fidelity.py](../evaluate_fidelity.py))
· runs and their judged claims in [fidelity_runs/](fidelity_runs/)

Errors are claims the judge labelled **wrong** (contradicts the Gospels: order, person, speaker, a parable told as
something seen, two episodes blended, thoughts given to others) or **invented** (in none of the four Gospels).
Setting, his own feelings, and things true elsewhere in the Gospels are retelling, not errors.

| model | prompt | memories told | with no error | claims | errors |
|---|---|---|---|---|---|
| `gpt-realtime-2.1-mini` | before | 12 | 7 (58%) | 63 | 8 |
| `gpt-realtime-2.1-mini` | after, run A | 16 | 7 (44%) | 78 | 19 |
| `gpt-realtime-2.1-mini` | after, run B | 14 | 5 (36%) | 79 | 19 |
| `gpt-realtime-2.1` | after, run A | 10 | 9 (90%) | 32 | 1 |
| `gpt-realtime-2.1` | after, run B | 13 | 10 (77%) | 40 | 4 |

"after" adds three things to the MEMORY note: parables are marked as stories he told, keep the order of what
happened, and do not say what others thought.

**Reading.**
- The prompt changes did not help the mini model (no better, within noise; two runs each of about 15 memories).
- The full model makes about a fifth of the errors and says about half as much about the past. Saying less is part
  of why: fewer claims, fewer chances to be wrong, and fewer memories forced onto a turn.
- The bottleneck is the voice model retelling a whole section in one or two spoken sentences at speed, not the
  retrieval and not the note.

**Latency** (typed sessions, from the user's line to the text of the reply):

| model | first words, p50 / p90 | phase B, p50 / p90 |
|---|---|---|
| `gpt-realtime-2.1-mini` | 0.73 / 1.22 s | 3.45 / 4.49 s |
| `gpt-realtime-2.1` | 0.94 / 1.47 s | 3.44 / 4.43 s |

The full model starts about 0.2 s later; phase B waits on the recall either way. The cost per turn is higher.
