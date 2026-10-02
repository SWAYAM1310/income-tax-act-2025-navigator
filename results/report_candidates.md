| Version | What changed | n | Recall@5 | MRR | Fact recall | Cite prec. | Table exact | Amend. type | Refusal rec. | p50 s | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v0 | Naive baseline - raw page text, fixed 512-token chunks, dense only (retrieval only) | 222 | 0.471 | 0.403 | — | — | — | — | — | — | — |
| v1 | Header/footer removal and footnote separation (retrieval only) | 222 | 0.484 | 0.398 | — | — | — | — | — | — | — |
| v2 | Hierarchy-aware chunks with provision metadata (retrieval only) | 222 | 0.607 | 0.581 | — | — | — | — | — | — | — |
