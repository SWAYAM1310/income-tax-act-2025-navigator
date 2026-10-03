| Version | What changed | n | Recall@5 | MRR | Fact recall | Cite prec. | Table exact | Amend. type | Refusal rec. | p50 s | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v0 | Naive baseline - raw page text, fixed 512-token chunks, dense only | 30 | 0.562 | 0.492 | 0.486 | 0.583 | 0.500 | 0.000 | 0.833 | 0.930 | 4613.000 |
| v1 | Header/footer removal and footnote separation **(incomplete: 19/30; not comparable)** | 19 | 0.632 | 0.478 | 0.588 | 0.684 | 0.500 | 0.000 | — | 1.130 | 4616.400 |
| v2 | Hierarchy-aware chunks with provision metadata | 30 | 0.583 | 0.599 | 0.528 | 0.646 | 0.667 | 0.167 | 0.833 | 0.800 | 2154.700 |
| oracle | Oracle context - gold provisions given directly (generation upper bound) | 30 | — | — | 0.778 | 1.000 | 0.667 | 0.667 | 0.833 | 0.920 | 920.100 |
