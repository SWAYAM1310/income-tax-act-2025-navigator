| Version | What changed | n | Recall@5 | MRR | Fact recall | Cite prec. | Table exact | Amend. type | Refusal rec. | p50 s | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v0 | Naive baseline - raw page text, fixed 512-token chunks, dense only | 30 | 0.562 | 0.492 | 0.486 | 0.583 | 0.500 | 0.000 | 0.833 | 0.930 | 4613.000 |
| v1 | Header/footer removal and footnote separation | 30 | 0.500 | 0.379 | 0.507 | 0.542 | 0.667 | 0.000 | 0.833 | 0.950 | 4621.700 |
| v2 | Hierarchy-aware chunks with provision metadata | 30 | 0.583 | 0.599 | 0.583 | 0.646 | 1.000 | 0.167 | 0.833 | 0.800 | 2154.700 |
| v3 | Hybrid retrieval - dense + exact provision-id lookup, fused with RRF | 30 | 0.812 | 0.882 | 0.604 | 0.729 | 1.000 | 0.167 | 0.833 | 0.860 | 2122.600 |
| v4 | Hybrid retrieval plus linked amendment endnotes in the evidence | 30 | 0.812 | 0.882 | 0.750 | 0.896 | 0.833 | 0.833 | 0.833 | 0.870 | 2334.800 |
| v5 | Hybrid retrieval + endnotes + one-hop cross-reference expansion | 30 | 0.854 | 0.880 | 0.771 | 0.917 | 0.833 | 0.833 | 0.833 | 0.920 | 2453.800 |
| oracle | Oracle context - gold provisions given directly (generation upper bound) | 30 | — | — | 0.833 | 1.000 | 1.000 | 0.667 | 0.833 | 0.920 | 920.100 |
