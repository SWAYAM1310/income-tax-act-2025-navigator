# Eval ladder notes

Each section records what one step of the ladder changed and what it measurably bought. The full tables are `report_dev.md` (retrieval-only, 138 dev questions) and `report_dev_mini.md` (end-to-end, 30 questions, 6 per type).

Setup for every run:
- Answers come from `openai/gpt-oss-120b` on Groq; evidence is capped at 4.5K tokens.
- All metrics are deterministic; there is no LLM judge.
- Fact recall counts a gold fact as present if it appears verbatim after normalisation, **or** if ≥80% of its content words appear and every number in it appears exactly. The strict score is kept as `fact_recall_exact`, and table exact stays strict.

## Baselines (Phase 3)

- **v0:** raw page text in 512-token windows, dense retrieval with Jina v5 embeddings.
- **oracle:** the gold provisions and their amendment endnotes are handed directly to the generator. This is the ceiling for generation with perfect retrieval.

On dev_mini, v0 reaches 0.486 fact recall against the oracle's 0.778.

## Phase 4: v1 (cleaned text) and v2 (structural chunks)

### Retrieval, dev (n = 138)

Each cell is recall@5 / MRR.

| | overall | lookup | table | multi-hop | amendment |
|---|---|---|---|---|---|
| v0 | 0.460 / 0.404 | 0.54 / 0.45 | 0.88 / 0.68 | 0.47 / 0.52 | 0.06 / 0.04 |
| v1 | 0.472 / 0.391 | 0.57 / 0.42 | 0.92 / 0.65 | 0.45 / 0.51 | 0.06 / 0.05 |
| v2 | **0.589 / 0.578** | **0.91 / 0.84** | **0.96 / 0.89** | 0.50 / 0.62 | 0.06 / 0.03 |

- **Cleaning (v1) does almost nothing for retrieval.** Recall@5 rises 0.01 and MRR falls 0.01. Removing headers and footers doesn't change which 512-token window a definition lands in.
- **Structural chunking (v2) is the big step.** Lookup recall@5 goes from 0.54 to 0.91 and overall MRR from 0.40 to 0.58. One chunk per provision, carrying a breadcrumb such as "Section 2 > (5)", lets the embedding match the definition itself rather than a window that mixes three clauses.
- **Amendment retrieval is about 0.06 at every version.** The questions name a provision number ("How was section 99(2) amended…"), and dense embeddings don't match on numbers. This is the target for v3's section-ID boost and full-text search.
- **Multi-hop stays near 0.5.** One retrieval pass rarely surfaces both ends of a cross-reference. This is the target for v4's cross-reference expansion.

### End-to-end, dev_mini (n = 30)

| | Fact recall | Citation precision | Citation recall | Grounded numbers | Table exact | Amendment type | Refusal precision / recall | Evidence tok | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|
| v0 | 0.486 | 0.583 | 0.542 | 0.583 | 0.500 | 0.000 | 0.38 / 0.83 | 4,106 | 4,613 |
| v2 | 0.528 | 0.646 | 0.583 | 0.600 | 0.667 | 0.167 | 0.42 / 0.83 | 1,628 | 2,155 |
| oracle | 0.778 | 1.000 | 0.917 | 0.925 | 0.667 | 0.667 | 1.00 / 0.83 | 460 | 920 |

v1 end-to-end is pending: it stopped at 19 of 30 on the Groq daily quota.

- **v2 is better and cheaper.** Fact recall rises 0.04, citation precision 0.06 and table exact 0.17, while tokens per question fall 53% (4.6K → 2.2K). Smaller, precise chunks leave the model less irrelevant text to cite.
- **The gap to the oracle is mostly retrieval.**
  - Per-type fact recall for v2 against the oracle is: lookup 0.83 vs 1.00, table 0.78 vs 0.78, multi-hop 0.33 vs 0.58, amendment 0.17 vs 0.75.
  - Table is already at the ceiling. Amendment and multi-hop are where the remaining points are.
- **Low refusal precision (~0.4) is a retrieval symptom, not a generation fault.**
  - In v2, 7 of the 12 refusals are answerable questions: 5 amendment and 2 multi-hop.
  - In each case the needed endnote or cross-referenced provision wasn't retrieved, so refusing was the correct behaviour given the evidence.
  - With gold evidence, the oracle refuses no answerable question.

### Caveats

- dev_mini has 6 questions per type, so a single question moves a per-type score by 0.17. Treat per-type end-to-end differences under ~0.2 as noise. The 138-question retrieval numbers are the reliable signal.
- Table retrieval scores are inflated: templated table questions reuse the row's own wording.
- 220 of the 222 golden questions were bulk-accepted after spot checks, not individually verified.
- Latency is not comparable across versions: most answers were replayed from cache, and v0's p50 rests on 6 measured calls.
