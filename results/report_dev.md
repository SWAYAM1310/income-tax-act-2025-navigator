| Version | What changed | n | Recall@5 | MRR | Fact recall | Cite prec. | Table exact | Amend. type | Refusal rec. | p50 s | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|---|
| v0 | Naive baseline - raw page text, fixed 512-token chunks, dense only (retrieval only) | 138 | 0.460 | 0.404 | — | — | — | — | — | — | — |
| v1 | Header/footer removal and footnote separation (retrieval only) | 138 | 0.472 | 0.391 | — | — | — | — | — | — | — |
| v2 | Hierarchy-aware chunks with provision metadata (retrieval only) | 138 | 0.589 | 0.578 | — | — | — | — | — | — | — |
| v3 | Hybrid retrieval - dense + exact provision-id lookup, fused with RRF (retrieval only) | 138 | 0.879 | 0.882 | — | — | — | — | — | — | — |
| v4 | Hybrid retrieval plus linked amendment endnotes in the evidence (retrieval only) | 138 | 0.879 | 0.882 | — | — | — | — | — | — | — |
| v5 | Hybrid retrieval + endnotes + one-hop cross-reference expansion (retrieval only) | 138 | 0.923 | 0.882 | — | — | — | — | — | — | — |
| v6 | LangGraph agent - scope check, definition lookup, structured endnotes (over v5) (retrieval only) | 138 | 0.940 | 0.913 | — | — | — | — | — | — | — |
