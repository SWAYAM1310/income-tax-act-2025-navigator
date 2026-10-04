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
| v1 | 0.465 | 0.542 | 0.500 | 0.558 | 0.500 | 0.000 | 0.42 / 0.83 | 4,106 | 4,622 |
| v2 | **0.528** | **0.646** | **0.583** | **0.600** | **0.667** | **0.167** | 0.42 / 0.83 | **1,628** | **2,155** |
| oracle | 0.778 | 1.000 | 0.917 | 0.925 | 0.667 | 0.667 | 1.00 / 0.83 | 460 | 920 |

- **Cleaning (v1) does not pay off end-to-end either.** Against v0 it is flat to slightly worse on every generation metric (fact recall 0.465 vs 0.486, citation precision 0.542 vs 0.583, table exact unchanged at 0.500) for the same cost: identical evidence tokens and 4,622 vs 4,613 LLM tokens per question. Stripping headers and footers does not change which 512-token window a provision falls into, so the generator sees the same evidence; the small differences are within dev_mini's noise. This mirrors the retrieval result and is the useful negative finding of the phase — the win comes from chunking structurally, not from tidying the text.
- **v2 is better and cheaper.** Fact recall rises 0.04, citation precision 0.06 and table exact 0.17, while tokens per question fall 53% (4.6K → 2.2K). Smaller, precise chunks leave the model less irrelevant text to cite.
- **The gap to the oracle is mostly retrieval.**
  - Per-type fact recall for v2 against the oracle is: lookup 0.83 vs 1.00, table 0.78 vs 0.78, multi-hop 0.33 vs 0.58, amendment 0.17 vs 0.75.
  - Table is already at the ceiling. Amendment and multi-hop are where the remaining points are.
- **Low refusal precision (~0.4) is a retrieval symptom, not a generation fault.**
  - In v2, 7 of the 12 refusals are answerable questions: 5 amendment and 2 multi-hop.
  - In each case the needed endnote or cross-referenced provision wasn't retrieved, so refusing was the correct behaviour given the evidence.
  - With gold evidence, the oracle refuses no answerable question.

## Phase 5: v3 (hybrid retrieval)

v3 keeps v2's chunks and changes only retrieval: dense k-NN is fused by RRF with two
**provision-id lookups**, driven by references parsed straight out of the question
(`statnav/retrieve/ids.py` handles "section 228(3)(b)(ii)(A)" and
"Schedule XI, Part A, paragraph 4(f)"). The parser resolves the exact gold id for **all 48**
amendment questions in the golden set.

### Retrieval, dev (n = 138)

| | recall@5 | MRR | hit@1 |
|---|---|---|---|
| v2 | 0.589 | 0.578 | 0.516 |
| **v3** | **0.879** | **0.882** | **0.831** |

Per type, recall@5 / MRR / hit@1:

| | v2 | v3 |
|---|---|---|
| lookup | 0.914 / 0.843 / 0.800 | 0.914 / 0.826 / 0.771 |
| table | 0.958 / 0.892 / 0.833 | 0.958 / 0.872 / 0.792 |
| multi-hop | 0.500 / 0.621 / 0.500 | **0.656 / 0.829 / 0.750** |
| amendment | 0.061 / 0.028 / 0.000 | **1.000 / 1.000 / 1.000** |

- **Amendment retrieval is solved: 0.061 to 1.000 recall@5, and MRR and hit@1 are also 1.000.**
  Every dev amendment question now ranks its gold provision first. The questions always name
  the provision, and dense embeddings carry no signal for a number -- Postgres' `simple`
  tokeniser even splits `483(1)` into `483` and `1`. Looking the reference up by id makes it an
  exact match instead of a semantic one.
- **Multi-hop improved as a side effect** (0.500 to 0.656 recall@5, hit@1 0.500 to 0.750):
  these questions often cite the section they cross-reference.
- **Lookup and table recall@5 are untouched** (0.914, 0.958), with hit@1 within one question of
  v2 (24 table questions, so 0.042 each). Getting there took two corrections, both found by
  measurement rather than design:
  - Boosting only the *exact* id drove **table hit@1 from 0.833 to 0.000**. Section 393's own
    chunk is a 36-token heading and the rates live in `s393:tbl1#...` chunks, so the exact-match
    boost put an empty stub at rank 1. Fix: a second retriever (`under`) returns the provision
    *and its descendants* ordered by embedding similarity, so the ids give the candidate set and
    the embedding gives the order.
  - Ordering *only* by embedding then lost amendment again (1.000 to 0.121), because dense
    ranking buries the provision the question names. Fix: fuse both lists, and drop from the
    exact list any match that is a heading stub or a **container** -- a provision whose content
    sits in deeper chunks. That test is structural (does a deeper chunk exist?), so it separates
    "the question names the answer" from "the question names where to look" **without needing to
    know the question's type**. It lifted MRR from 0.848 to 0.882 and table hit@1 from 0.583 to
    0.792.
- **Full-text search is implemented, tested and switched off.** Postgres' `ts_rank` applies no
  IDF and `simple` keeps stop words, so a natural question ANDed together matches nothing
  (verified: 0 rows) and OR-ing it ranks badly. Even restricted to rare terms it lowered overall
  recall@5 to 0.871 by costing lookup (0.800 vs 0.914). It did lift multi-hop (0.719 vs 0.656),
  so `retrievers: [dense, fts, ids, under]` stays available for the cross-reference work in v4.
- The whole phase cost **0 API tokens**: dev query embeddings were already cached, and the id
  lookups are pure Postgres.

## Phase 6: v4 (amendment endnotes) and v5 (cross-reference expansion)

Numbering departs from the plan on purpose: measurement showed endnotes, not cross-references,
were what blocked amendment *answers*, so amendment linking came before cross-reference expansion.

- **v4** appends each retrieved chunk's linked amendment endnotes to its text
  (`statnav/retrieve/amend.py`). v3 ranked `v2:s99(2)` first for "How was section 99(2) amended?"
  and still refused, because the chunk carries only the `[...]` brackets and the change sits in
  the endnote. Retrieval metrics are identical to v3 by construction; the effect is on answers
  (end-to-end numbers: see below / pending). Cost: +260 evidence tokens per question on average.
- **v5** adds one-hop cross-reference expansion for multi-hop questions.

### v5 retrieval, dev (n = 138), against v3

| | recall@5 | recall@10 | MRR | hit@1 |
|---|---|---|---|---|
| v3 | 0.879 | 0.903 | 0.882 | 0.831 |
| **v5** | **0.923** | **0.944** | 0.882 | 0.831 |

| recall@5 | v3 | v5 |
|---|---|---|
| multi-hop | 0.656 | **0.828** |
| lookup | 0.914 | 0.914 |
| table | 0.958 | 0.958 |
| amendment | 1.000 | 1.000 |

- **Why it should work, checked before building:** for 19 of the 20 dev multi-hop questions whose
  gold provision was missing from v3's top 5, it was exactly one cross-reference hop from
  something v3 had ranked there, and the hop sets are small (median 23 provisions).
- **The merge matters more than the expansion.** Fusing the expansion list with RRF raised
  multi-hop recall but wrecked ranking: lookup hit@1 0.771 to 0.457, overall MRR 0.882 to 0.736,
  because expansion candidates displaced correct rank-1 hits. Reserving slots instead (keep the
  top 4 untouched, give places 5-6 to expansion candidates) leaves MRR and hit@1 unchanged by
  construction.
- **A regression I nearly shipped:** keep 3 + 2 slots scored higher on multi-hop (0.859) but an
  expansion hit took rank 4 from a correct row on one section-393 table question, cutting table
  recall@5 0.958 to 0.917. My first sweep printed table hit@1 but not table recall@5, so it
  looked clean. Keep 4 regresses no question type and costs one multi-hop question.
- **Overfitting caution:** about 20 settings were tried on dev's 32 multi-hop and 24 table
  questions, and the good ones differ by a question or two. Expect the test-split gain to be
  somewhat smaller than +0.17 on multi-hop.
- Zero API tokens: dev embeddings are cached and the expansion is Postgres.

### Caveats

- dev_mini has 6 questions per type, so a single question moves a per-type score by 0.17. Treat per-type end-to-end differences under ~0.2 as noise. The 138-question retrieval numbers are the reliable signal.
- **Partial runs are not a preview of the full score.** v1's first attempt stopped at 19 of 30 on the Groq daily cap and read 0.588 fact recall; completing the same run over all 30 gave 0.465. The questions are evaluated in a fixed order, so a truncated run is a biased sample, not an early estimate. Only rows with n = 30 are compared here.
- **v1 versus v0 on retrieval depends on the split.** On the 138-question dev set v1 edges v0 (recall@5 0.472 vs 0.460); on dev_mini the order reverses (0.500 vs 0.562). Both gaps are small, which is the point: cleaning has no real effect either way, and dev_mini is too small to resolve it.
- Table retrieval scores are inflated: templated table questions reuse the row's own wording.
- 220 of the 222 golden questions were bulk-accepted after spot checks, not individually verified.
- Latency is not comparable across versions: most answers were replayed from cache, and v0's p50 rests on 6 measured calls.
