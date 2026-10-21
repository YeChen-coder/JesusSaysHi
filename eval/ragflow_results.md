# RAGFlow retrieval eval

2026-10-21 · 55 questions · one result per BSB section · hit = first section overlapping an expected range

| configuration | hit@1 | hit@3 | hit@5 | MRR | situational hit@3 | p50 ms | p90 ms |
|---|---|---|---|---|---|---|---|
| dense | 56% | 82% | 91% | 0.70 | 78% | 319 | 642 |
| dense + rewrite | 75% | 87% | 95% | 0.82 | 83% | 297 | 361 |
| hybrid (full-text 0.3) | 65% | 82% | 85% | 0.74 | 78% | 301 | 367 |
| hybrid (full-text 0.3) + rewrite | 73% | 91% | 95% | 0.82 | 86% | 307 | 390 |
| hybrid (full-text 0.7, RAGFlow default) | 60% | 78% | 84% | 0.70 | 72% | 297 | 360 |
| hybrid (full-text 0.7, RAGFlow default) + rewrite | 75% | 93% | 95% | 0.83 | 89% | 294 | 404 |
| hybrid 0.3 + rerank (rerank-2.5) | 76% | 87% | 89% | 0.82 | 83% | 446 | 710 |
| hybrid 0.3 + rerank (rerank-2.5) + rewrite | 67% | 95% | 98% | 0.79 | 92% | 445 | 599 |

## Abstention: best score, real questions vs off-topic

| configuration | real: min / p10 / median | off-topic: max / median | separable |
|---|---|---|---|
| dense | 0.582 / 0.594 / 0.622 | 0.587 / 0.561 | no |
| dense + rewrite | 0.612 / 0.643 / 0.657 | 0.587 / 0.561 | yes |
| hybrid (full-text 0.3) | 0.432 / 0.702 / 0.727 | 0.710 / 0.692 | no |
| hybrid (full-text 0.3) + rewrite | 0.731 / 0.748 / 0.759 | 0.710 / 0.692 | yes |
| hybrid (full-text 0.7, RAGFlow default) | 0.185 / 0.869 / 0.881 | 0.874 / 0.866 | no |
| hybrid (full-text 0.7, RAGFlow default) + rewrite | 0.880 / 0.889 / 0.895 | 0.874 / 0.866 | yes |
| hybrid 0.3 + rerank (rerank-2.5) | 0.338 / 0.376 / 0.466 | 0.286 / 0.207 | yes |
| hybrid 0.3 + rerank (rerank-2.5) + rewrite | 0.314 / 0.373 / 0.449 | 0.287 / 0.207 | yes |
