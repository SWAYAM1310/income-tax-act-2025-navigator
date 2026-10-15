# Eval ladder notes

Each section records what one step of the ladder changed and what it measurably bought. The full tables are `report_dev.md` (retrieval-only, 138 dev questions) and `report_dev_mini.md` (end-to-end, 30 questions, 6 per type).

Setup for every run:
- Answers come from `openai/gpt-oss-120b` on Groq; evidence is capped at 4.5K tokens.
- All metrics are deterministic; there is no LLM judge.
- Fact recall counts a gold fact as present if it appears verbatim after normalisation, **or** if ≥80% of its content words appear and every number in it appears exactly. The strict score is kept as `fact_recall_exact`, and table exact stays strict.
- **All end-to-end numbers were rescored on 2026-10-06** after a normalisation fix: the model
  often writes percentages as `2 %` with a narrow no-break space (U+202F), which did not match a
  gold `2%`, so correct table answers scored 0 and their numbers counted as ungrounded. Every
  version was rescored from the same cached answers (answers, retrieval and citations
  byte-identical; 0 LLM tokens). This lifted table exact for v1-v5 and the oracle alike. A
  second pass the same day also maps "2 per cent" / "2 percent" (the Act's own wording) to
  "2%", which lifted v0 too. A third pass lets a gold fact that is only a change type
  ("substituted") accept the same stems as `amendment_type` ("replaced"), after it was found
  rewarding a backwards answer over a correct one (Phase 11). Pre-fix numbers are in git
  history.
- **v3-v5 dev_mini were re-run on 2026-10-06** after a retrieval bug fix (see Phase 7): their
  subtree and cross-reference lookups were silently dropping candidates. Dev recall, MRR and
  hit@1 were unchanged, but the evidence changed on 4-5 dev_mini questions per version, so those
  answers were regenerated.

## Baselines (Phase 3)

- **v0:** raw page text in 512-token windows, dense retrieval with Jina v5 embeddings.
- **oracle:** the gold provisions and their amendment endnotes are handed directly to the generator. This is the ceiling for generation with perfect retrieval.

On dev_mini, v0 reaches 0.542 fact recall against the oracle's 0.833.

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
| v0 | 0.542 | 0.583 | 0.542 | 0.583 | 0.833 | 0.000 | 0.38 / 0.83 | 4,106 | 4,613 |
| v1 | 0.521 | 0.542 | 0.500 | 0.625 | 0.833 | 0.000 | 0.42 / 0.83 | 4,106 | 4,622 |
| v2 | **0.583** | **0.646** | **0.583** | **0.683** | **1.000** | **0.167** | 0.42 / 0.83 | **1,628** | **2,155** |
| oracle | 0.833 | 1.000 | 0.917 | 1.000 | 1.000 | 0.667 | 1.00 / 0.83 | 460 | 920 |

- **Cleaning (v1) does not pay off end-to-end either.** Against v0 it is flat to slightly worse (fact recall 0.521 vs 0.542, citation precision 0.542 vs 0.583, table exact equal at 0.833) for the same cost: identical evidence tokens and 4,622 vs 4,613 LLM tokens per question. Stripping headers and footers does not change which 512-token window a provision falls into, so the generator sees the same evidence; the differences are within dev_mini's noise. This mirrors the retrieval result and is the useful negative finding of the phase — the win comes from chunking structurally, not from tidying the text.
- **v2 is better and cheaper.** Fact recall rises 0.04, citation precision 0.06 and table exact 0.17, while tokens per question fall 53% (4.6K → 2.2K). Smaller, precise chunks leave the model less irrelevant text to cite.
- **The gap to the oracle is mostly retrieval.**
  - Per-type fact recall for v2 against the oracle is: lookup 0.83 vs 1.00, table 1.00 vs 1.00, multi-hop 0.33 vs 0.58, amendment 0.17 vs 0.75.
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
  (end-to-end numbers below). Cost: +260 evidence tokens per question on average.
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

### End-to-end, dev_mini (n = 30), v2 to v5

| | Fact recall | Citation precision | Citation recall | Grounded numbers | Table exact | Amendment type | Prior-text F1 | Refusal precision / recall | Evidence tok | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 | 0.583 | 0.646 | 0.583 | 0.683 | 1.000 | 0.167 | 0.116 | 0.42 / 0.83 | 1,628 | 2,155 |
| v3 | 0.604 | 0.729 | 0.646 | 0.772 | 1.000 | 0.167 | 0.137 | 0.50 / 0.83 | 1,600 | 2,126 |
| v4 | 0.771 | 0.896 | 0.833 | **1.000** | 0.833 | **0.833** | **0.671** | **0.83** / 0.83 | 1,787 | 2,342 |
| **v5** | **0.792** | **0.917** | **0.854** | 0.952 | 0.833 | **0.833** | 0.551 | **0.83** / 0.83 | 1,888 | 2,444 |
| oracle | 0.833 | 1.000 | 0.917 | 1.000 | 1.000 | 0.667 | 0.594 | 1.00 / 0.83 | 460 | 920 |

Per-type fact recall:

| | lookup | table | multi-hop | amendment |
|---|---|---|---|---|
| v2 | 0.83 | 1.00 | 0.33 | 0.17 |
| v3 | 0.83 | 1.00 | 0.42 | 0.17 |
| v4 | 0.83 | 1.00 | 0.42 | **0.83** |
| v5 | 0.83 | 1.00 | **0.50** | **0.83** |
| oracle | 1.00 | 1.00 | 0.58 | 0.75 |

- **v3's perfect amendment retrieval did not reach the answers on its own.** End-to-end it is
  no better than v2 (amendment fact recall 0.17 and amendment type 0.167 for both). The
  model found the right provision and refused, because the change lives in the endnote.
- **v4's endnotes turn it into correct answers.** Amendment fact recall 0.17 → 0.83, amendment
  type 0.167 → 0.833, prior-text F1 0.14 → 0.67, amendment citation precision and recall 0.33 →
  1.00. False refusals of answerable questions fall from 5 (v3) to 1, so refusal precision rises
  0.50 → 0.83. This is the largest single end-to-end step on the ladder: overall fact recall
  +0.17 for +216 LLM tokens per question.
- **v4 scores above the oracle on amendment type (0.833 vs 0.667) — this is one question of noise,
  and the metric is a keyword check.** On 085c86df the oracle wrote "amended" where the gold is
  "inserted"; on 1de9b7c7 v4 did the same. `amendment_type` only looks for the change-type stem,
  so it cannot see direction: the oracle states s99(2)'s substitution backwards and still scores
  1. Phase 11 adds `amendment_direction` for exactly this.
- **v5's cross-reference expansion shows up end-to-end as predicted, at dev_mini resolution.**
  Multi-hop fact recall 0.42 → 0.50 and citation recall 0.50 → 0.58 — one question
  (multi_hop-f6e5a319: recall@5 0.5 → 1.0, fact recall 0.5 → 1.0, and it was v4's only false
  refusal). Its one new false refusal is lookup-2f3d865e ("transfer"), whose gold is in neither
  version's top 5; v4 answered it wrongly from s174(7)(a), so v5 refusing is the better behaviour
  even though both score 0. Cost +102 LLM tokens per question.
- **Table questions do not regress.** Before the rescore v4/v5 appeared to lose table exact
  (0.667 → 0.500 → 0.333); that was the `2 %` normalisation bug, not the extra endnote tokens.
  The one remaining v4/v5 table miss is table-a8fea698, where the model wrote "the rate 'in
  force'" for the gold "Rates in force" — right meaning, strict-match miss. Table fact recall is
  1.00 for every version from v2 on.
- **The remaining gap to the oracle is lookup and multi-hop** (0.83 vs 1.00 and 0.50 vs 0.58);
  amendment and table are at the ceiling on dev_mini. v5's evidence is still 4× the oracle's
  (1,888 vs 460 tokens).
- Groq spend: the runs finished on 2026-10-05 (ledger: 123,708 gpt-oss-120b tokens that day, on
  top of v3's partial on 2026-10-04); the rescores replayed every answer from cache at 0 tokens.

## Phase 7: v6 (LangGraph agent)

v6 wraps v5's retrieval in a LangGraph graph (`statnav/agent/graph.py`):

    classify --(out of scope)--> refuse
        \--(in scope)--> retrieve (= v5) --> tools --> pack --> generate

Each node targets a failure v5 still had, found by reading its misses:

| v5 failure | Node | What it does |
|---|---|---|
| "What is the meaning of "transfer"?" ranks sections that *use* the word, never s2(109) | `tools` (definitions) | 442 defined terms parsed from `"X" means/includes` clauses; the defining clause goes to rank 1 |
| An `Ins.` endnote reported as "amended"; Schedule XIV 4(3) reported as "substituted" (that endnote was 4(1)(a)'s) | structured endnotes | `[applies to Schedule XIV, paragraph 4(3); amendment type: inserted; by Act No. 4 of 2026; ...]` |
| "How do I claim a refund that is stuck on the portal?" answered | `classify` (scope) | gpt-oss-20b screens the topic; out-of-scope questions are refused before retrieval |

Routing is deterministic (regexes; every dev amendment and table question routes correctly).
Only the scope check uses an LLM: gpt-oss-20b, on its own daily quota. The prompt, evidence
packing and answer model are unchanged, so the differences below come from the graph.

### Retrieval and scope, dev (n = 138)

| | recall@5 | MRR | hit@1 | lookup recall@5 / hit@1 | scope precision / recall |
|---|---|---|---|---|---|
| v5 | 0.923 | 0.882 | 0.831 | 0.914 / 0.771 | — |
| **v6** | **0.940** | **0.913** | **0.871** | **0.971 / 0.914** | **1.00 / 1.00** |

- **Definitions fix the lookup misses.** "transfer" and "India" go from outside the top 10 to
  rank 1, and three more definition questions move their gold from rank 2-3 to rank 1. Table,
  amendment and multi-hop are unchanged. Only one defining provision per term: also adding a
  second one ("University" in both s66(40) and s402(44)) pushed a multi-hop question's other
  gold out of the top 5.
- **The scope check catches all 14 out-of-scope dev questions and refuses no answerable one.**
  That took one prompt revision, so it is tuned on dev. The first prompt let gpt-oss-20b judge
  from memory whether the Act covers a topic, and it refused 5 of 124 answerable questions
  ("The Act does not define 'zero coupon bond'" -- s2(112) does). The revision tells it that it
  has not seen the Act and must judge the topic only. Expect the test split to be less clean.
- Cost: ~420 gpt-oss-20b tokens per question for the scope check; 0 Jina tokens.

### End-to-end, dev_mini (n = 30)

| | Fact recall | Citation precision | Citation recall | Grounded numbers | Table exact | Amendment type | Refusal precision / recall | Evidence tok | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|
| v5 | 0.792 | 0.917 | 0.854 | 0.952 | 0.833 | 0.833 | 0.83 / 0.83 | 1,888 | 2,444 |
| **v6** | **0.875** | **0.958** | **0.896** | **1.000** | **1.000** | **1.000** | **1.00 / 1.00** | 1,652 | 2,531 |
| oracle | 0.833 | 1.000 | 0.917 | 1.000 | 1.000 | 0.667 | 1.00 / 0.83 | 460 | 920 |

Per-type fact recall, v5 → v6: lookup 0.83 → **1.00**, amendment 0.83 → **1.00**, table 1.00 →
1.00, multi-hop 0.50 → 0.50 (oracle: 1.00 / 0.75 / 1.00 / 0.58).

- **Three questions change, all for the better, each attributable to one node:**
  lookup-2f3d865e ("transfer") goes from refused to correct (definitions); amendment-1de9b7c7 now
  says "inserted" (structured endnotes); refusal-270744d1 ("refund stuck on the portal") is
  refused (scope). No question regresses.
- **v6 is the first version with no false refusal and no missed refusal on dev_mini.** Even the
  oracle answers one out-of-scope question from its distractor passages.
- **It scores above the oracle on fact recall (0.875 vs 0.833).** The oracle is a ceiling for
  *generation* given gold provisions in the raw endnote format; it has neither the scope check
  nor structured endnotes, so it answers one refusal question and words two amendments loosely.
  The remaining gap to the oracle is **multi-hop (0.50 vs 0.58)**.
- **Cost:** +87 LLM tokens per question overall: ~390 gpt-oss-20b scope tokens on every
  question, offset by 120b calls skipped on refused questions and by smaller evidence (1,652 vs
  1,888 tokens, because the definition clause replaces looser passages).
- Groq spend for this phase (2026-10-06, including the v3-v5 reruns and the first v6 attempt):
  117,485 gpt-oss-120b and 112,199 gpt-oss-20b tokens.

### The retrieval bug found on the way

`under_ids` and `xref_hits` (v3 onward) ran `WHERE <small filter> ORDER BY embedding <=> q
LIMIT k`. Postgres planned that as an HNSW index scan with the filter applied afterwards, and the
scan only visits about `hnsw.ef_search` nearest neighbours, so a candidate set like "the subtree
of s2(52)" usually came back empty (it did at ef_search 40 and 100; 1000 found it). Results also
depended on whether an earlier `knn` call had raised `ef_search` on the same connection. The fix
ranks the filtered set exactly in a `MATERIALIZED` CTE. On dev it changed 15-16 of 138 ranked
lists, all below the gold hit, so recall, MRR and hit@1 did not move; v3-v5 dev_mini were re-run
because their evidence changed.

## Phase 8: v7 (verifier) -- a measured negative result

The plan's v7 is a citation verifier. Before building it I checked what it could fix on v6's
dev_mini answers:

- **Deterministic citation rules flag mostly false positives.** "Every number appears in the
  cited text" trips on years such as 2026 that come from the endnotes; "every named provision is
  cited" trips on provisions such as s237(1) that the cited passage itself names. Grounded
  numbers are already 1.000.
- **The visible gap was under-citation:** multi-hop answers rely on two passages and cite one
  (v6 cites `s173` but not `s66(16)`; `s394` but not `s402(33)`), with both passages in the
  evidence. Citation recall 0.896.

So v7 adds a `verify` node: gpt-oss-20b splits the answer into claims and names the passages
that support each, across *all* the evidence; a claim with no support sends the answer back to
`generate` once, with the claim named (`statnav/agent/verify.py`).

| dev_mini | Fact recall | Citation precision | Citation recall | Grounded numbers | LLM tok/q |
|---|---|---|---|---|---|
| v6 | 0.875 | 0.958 | 0.896 | 1.000 | 2,531 |
| v7, citations re-derived from the checker | 0.875 | 0.896 | 0.854 | 0.952 | 4,625 |
| **v7, checker as a gate (shipped)** | 0.875 | 0.958 | 0.896 | 1.000 | 4,625 |

- **The checker judged every one of the 24 answers supported, on the first attempt.** No
  retries, no changed answers.
- **The under-citation hypothesis was wrong.** For "fixed place of business", s173 alone does
  say "a fixed place of business through which the business ... is wholly or partly carried
  on"; the gold's second hop, s66(16), is needed to *find* that passage, not to support the
  answer's wording. The multi-hop gold labels both hops, so "citation recall" there partly
  measures a labelling convention.
- **Replacing the generator's citations with the checker's support made them worse**
  (precision 0.958 → 0.896, recall 0.896 → 0.854): the 20b checker cites more loosely than the
  120b answer model (it added a table note and a neighbouring section) and once chose the wrong
  Schedule XIV paragraph. So the shipped v7 keeps the generator's citations and uses the
  verdict only as a gate (`verify_citations: false`), which makes it identical to v6 on dev_mini
  at +83% LLM tokens (2,094 gpt-oss-20b tokens per answered question).
- **Whether the gate is worth that cost depends on whether it catches wrong answers**, which
  dev_mini cannot show (v6 left none with an ungrounded number). `python -m evals.verifier_check`
  measures it directly: it corrupts one quantity in each correct v6 answer (30% → 91%, Rs
  1,00,000 → Rs 300001, 1-April → 4-April) and asks the checker about both versions
  (`results/v7/dev_mini/verifier_check_v6.json`, run 2026-10-07):

  | dev_mini, v6 answers (n = 10) | Corrupted answer flagged | Original answer flagged |
  |---|---|---|
  | rate or amount changed (30% → 91%, 2% → 7%, Rs 1,00,000 → Rs 300001; n = 6) | **6 of 6** | 0 of 6 |
  | effective date changed (1-April-2026 → 4-April-2026; n = 4) | **0 of 4** | 0 of 4 |
  | **all** | **catch rate 0.60** | **false-flag rate 0.00** |

  - **The gate catches wrong numbers and misses wrong dates.** All four misses are amendment
    answers whose only quantity is the effective date. The evidence states it as
    `w.e.f. 1-4-2026` and the answer as "1-April-2026"; the likely reason (not probed) is that the
    20b checker does not convert between the two formats, so "4-April-2026" looks close enough to
    "1-4-2026". A deterministic date check
    (normalise `d-m-yyyy` and month names, then compare) would close this more cheaply than the
    LLM.
  - **It cannot see direction either.** Two of the "correct" originals state their substitution
    backwards (s99(2) and s195(1)(i), the v6 errors v8 fixes), and the checker passed both: the
    same words appear in the evidence, only their roles are swapped.
  - So v7 stays a gate and is not the shipped version: v8 fixes the direction errors at no extra
    cost, and the checker's one demonstrated catch (a corrupted rate or amount) is a case where
    v6-v8 have scored grounded numbers 1.000 on dev_mini anyway.
  - Cost: 30,293 gpt-oss-20b tokens (the 10 original-answer checks were cached).
- Cost of the phase: 52,425 gpt-oss-20b tokens (the re-run as a gate replayed every check from
  cache) + 30,293 for the mutation test; 0 gpt-oss-120b.

## Phase 11: v8 (explicit before/after wording in the endnotes)

`amendment_type` only checks the change-type word. Reading answers in the frontend's Before / Now
view showed them stating substitutions **backwards**, so Phase 11 added `amendment_direction`
(`evals/metrics.py`): for the substitutions whose endnote quotes the replaced words (`Sub. for
"60%"`; 13 of the 48 amendment questions, 10 in dev), it finds both wordings in the answer and
reads the connective between them ("from X to Y", "X replaced by Y", "Y substituted for X"). It
abstains when the answer does not quote both or the connective is unclear.

The cause is the Act's abbreviation: `Sub. for "60%"` means 60% is the **earlier** wording, and
the model reads it as "substituted with 60%" (v6: section 195(1)(i) went "from 30% to 60%"; the
Act says 60% → 30%). v8 is v6 with `endnotes: explicit`, which adds the wording on each side to
the endnote line: `wording before: "60%"; wording now: "30%"` (old words from the endnote, new
words from the bracket the endnote tags in the provision) and `inserted (not in the Act before):
"..."` for insertions. Nothing else changes.

| dev substitutions (n = 10) | Direction right (scored) | Amendment type | Fact recall | LLM tok/q |
|---|---|---|---|---|
| oracle (gold passages, raw endnotes) | 2 of 6 | 0.90 | 0.90 | 937 |
| v6 | 0 of 3 | 1.00 | 0.90 | 3,313 |
| **v8** | **7 of 7** | 1.00 | **0.95** | 3,306 |

- **Every scored v6 answer had the direction backwards, and so did most of the oracle's**: with
  the gold provisions in hand, the model still reverses 4 of 6. This was an evidence-format
  problem, not retrieval.
- **v8 gets all 7 right, and states both wordings more often** (7 answers scorable vs 3), at
  the same token cost.
- **On dev_mini v8 equals v6 on every other metric** (fact recall 0.875, citation precision
  0.958, refusal P/R 1.00/1.00) and moves amendment direction 0.0 → 1.0 (2 scorable questions).
- **The fact metric was rewarding the wrong answer.** amendment-27f49307's gold facts are
  "substituted" and "60%": v6's backwards answer contains both, and v8's correct "replace 60%
  with 30%" lacked the word "substituted", so v8 first scored *below* v6 (0.854 vs 0.875). A gold
  fact that is only a change type now accepts the `amendment_type` stems; every version was
  rescored from cache (this moved v3 0.562 → 0.604 and v4 0.708 → 0.771).
- Cost: ~66K gpt-oss-120b tokens on 2026-10-06 for the substitution runs (v6, v8, oracle) and v8's dev_mini answers.

## Phase 14: v9 (answers explained for non-experts)

v9 is v8 with a different answer prompt (`answer.py:EXPLAINED_PROMPT`) and nothing else: same
retrieval, evidence and agent. The answer is Markdown: **In short**, **What this means for you**,
a block chosen by the agent's route (general: *Conditions to check*; table: *The numbers*;
amendment: *What changed*; definition: *What it includes and excludes*), **Watch out**, a worked
**Example**, and **Key terms**, with a `[Cn]` marker on each sentence (shown as a clickable §
mark) and two or three `follow_ups`. It answers with its own model role, `answer_explained`
(gpt-oss-120b, medium reasoning, 2,400-token cap).

### End-to-end, dev_mini (n = 30), against v8

| | Fact rec. | Exact | Cite prec. | Cite rec. | Grounded | Table exact | Amend. type | Amend. dir. | Refusal P / R | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|
| v8 | 0.875 | 0.701 | **0.958** | 0.896 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 / 1.00 | **2,532** |
| **v9** | **0.917** | **0.736** | 0.868 | **0.958** | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 / 1.00 | 3,835 |

- **More of the expected facts appear, and no measured score regresses except citation
  precision.** The longer answers name more of the conditions and numbers the gold facts list.
- **Citation precision 0.958 → 0.868** is v9 citing neighbouring passages as well: a table row's
  notes beside the row (table-2e663b9b cites `s393:tbl1#3(i)` plus notes 2 and 4), or several
  sub-sections of the same section. The metric counts any passage outside the gold set as
  imprecise, so this is extra support rather than wrong support, but it is a real loss of
  focus and is reported as measured.
- **Grounded numbers ignore the Example section** (`evals/metrics.py:stated_numbers`): its
  "Suppose you pay Rs. 30,000" amounts are made up on purpose. Answers up to v8 have no such
  section, so their scores are unchanged.
- **Found while tuning (on dev_mini's 4 UI examples and one s126 question, not on test):**
  - At low reasoning effort the model read s126(2)(b)'s "up to Rs. 25000 in aggregate" for
    "parent or parents" as a limit *per parent*; medium reasoning and a reading rule ("in
    aggregate ... is one combined limit") fixed it. High reasoning does not fit the free tier:
    Groq counts prompt + `max_tokens` against the 8K tokens/minute limit.
  - Given a "Key terms" section, the model explained words from memory ("senior citizen: 60
    years or older, as defined elsewhere") and invented meanings for clause numbers. Prompt
    rules did not stop it, so `answer.tidy` now keeps a term only if a passage defines it
    (`"term" means/includes`). It also moves a "Follow-ups" section the model sometimes writes
    into the text into `follow_ups`.
  - Worked examples are the main new risk. On s126 the model several times added an "if you
    also paid ..." step that broke a restriction it had just stated (s126(7): no medical-expense
    deduction for an insured senior citizen). The prompt now orders *Watch out* before *Example*
    and forbids extra steps; it still happens occasionally on s126(4)'s two separate caps, which
    the model tends to read as one. No metric measures example correctness.
  - The first amendment run dropped amendment type to 0.667: answers gave both wordings
    correctly but never said "substituted". The *What changed* block now asks for the type.
- Cost: ~175K gpt-oss-120b tokens on 2026-10-10 (tuning, the UI fixture and two dev_mini passes,
  the second only re-asking the 6 amendment questions).

## Phase 15: lay-person questions (how much of the ladder survives plain language)

A review of this repo pointed out that the golden set flatters the design: most questions use
the Act's own coordinates. `python -m evals.lay_lint` measures it: **172 of 222 golden questions
fail a lay-question lint** (145 name a section or Schedule, 34 quote the defined term, 58 copy a
run of 5+ content words from the gold text). Real users ask "I pay my landlord 60,000 a month, do
I cut tax from the rent?", which names nothing. So the `ids` / `under` retrievers and the
definitions tool, which drive v3-v8's gains, mostly never fire for them.

**The lay set** (`evals/data/lay.jsonl`, built by `evals/build/lay.py`), 140 accepted questions:
- **86 situations**, hand-written (`evals/build/lay_situations.py`): salary, rent, home loans, TDS/TCS on everyday
  payments, selling a flat or shares, gifts, farm income, deductions, advance tax, late fees,
  refunds, the 2026 changes a taxpayer would notice, and 15 refusals that stay refusals
  (computing my tax, pick-for-me advice, forms, the portal, my notice, GST, stamp duty...). Gold
  provisions were found by reading the Act's headings and text, **not by running the
  retriever**, so the gold is not biased toward what the system already finds.
- **69 paraphrases** of *dev* golden questions by gpt-oss-20b (test questions are never
  paraphrased), same gold labels; 54 accepted (15 rejected: jargon a lay user would not use,
  or the rewrite changed the meaning), 18 of those reworded by hand.
- Every row passes the lint and every gold fact occurs verbatim in its gold text (tested in
  `tests/test_lay.py`). All decisions are in `verification_log.csv` with reviewer `claude`: the
  set was written or reviewed by Claude against the Act's text, **not checked by a tax expert**.
- Splits by id hash: `lay_dev` 95, `lay_test` 45 (**frozen**, `lay_test.sha256`, before any
  version is tuned on lay questions), `lay_mini` 30 (6 per type), `lay_orig` = the golden
  originals of the 32 answerable lay_dev paraphrases. `dev`, `test` and `dev_mini` are untouched.

### Retrieval, lay_dev (78 answerable questions), recall@5 / MRR / hit@1

| | v0 | v2 | v3 | v5 | v6 / v8 |
|---|---|---|---|---|---|
| all lay questions | 0.545 / 0.472 / 0.372 | **0.788** / 0.683 / 0.577 | 0.788 / 0.683 / 0.577 | 0.782 / 0.686 / 0.577 | 0.692 / 0.603 / 0.500 |
| situations (46) | 0.663 / 0.585 / 0.478 | 0.804 / 0.703 / 0.609 | 0.804 / 0.703 / 0.609 | 0.783 / 0.709 / 0.609 | 0.696 / 0.622 / 0.522 |
| paraphrases (32) | 0.375 / 0.311 / 0.219 | 0.766 / 0.653 / 0.531 | 0.766 / 0.653 / 0.531 | 0.781 / 0.653 / 0.531 | 0.688 / 0.575 / 0.469 |
| **same 32, original wording** | 0.484 / 0.401 / 0.312 | 0.781 / 0.741 / 0.688 | 0.969 / 0.953 / 0.906 | 0.969 / 0.953 / 0.906 | **0.969 / 0.969 / 0.938** |
| scope: answerable refused | | | | | **8 / 78** |
| scope: refusals caught | | | | | 17 / 17 |

- **On the same gold, lay wording costs v8 0.28 recall@5 and 0.39 MRR** (0.969 → 0.688,
  0.969 → 0.575). The originals' 0.969 is mostly the id lookup: v2, without it, scores 0.781 on
  them.
- **Everything after v2 is worth nothing on lay questions, and v6's scope check makes them
  worse.** v3/v5 equal v2 (no provision is named, so nothing is looked up). v6/v8 drop to 0.692
  because the scope check refuses 8 of 78 answerable questions before retrieval: first-person
  questions read as "personal tax advice" (freelancer TDS, a late fee "my income is about 4
  lakh", the average rate "I pay"), and TCS read as GST or "sales tax" (car dealers, tour
  operators). On the 70 it lets through, v8 is 0.771 against v2's 0.764 on the same questions:
  the definitions tool fired on 3 of 70, and 62 of 70 took the `general` route.
- **What is left is a vocabulary gap.** Of the 21 misses, typical ones are "notional rent" (the
  Act: *annual value*, s21(6)), "money I can't explain" (*unexplained* income, s195), "tax bill is
  small" (advance tax "Rs. 10000 or more", s404), "shares held about 2 years" (the 12.5% in
  s197(1) loses to s214's non-resident table), "who is the officer who examines my return"
  (*Assessing Officer*, s2(12)).
- **A crash found on the way (fixed):** on one lay question ("I'm sending more than 10 lakh
  abroad...") gpt-oss-20b's scope check returned no JSON at all (Groq 400
  `json_validate_failed`), and `router.scope` let the error through, which stopped the eval run
  and would have failed the live API's answer. A classifier `LLMError` now fails open, like an
  unparseable verdict; `QuotaExhausted` still propagates (`tests/test_agent.py`).

### End-to-end, v9 on lay_mini (n = 30) against dev_mini

| | Fact rec. | Exact | Cite prec. | Cite rec. | Grounded | Table exact | Amend. type | Refusal P / R | recall@5 | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|
| v9, dev_mini | 0.917 | 0.736 | 0.868 | 0.958 | 1.000 | 1.000 | 1.000 | 1.00 / 1.00 | 0.896 | 3,835 |
| **v9, lay_mini** | **0.708** | 0.479 | **0.479** | 0.750 | 0.958 | 0.833 | **0.167** | **0.67 / 1.00** | 0.708 | 4,172 |

- **The generator refuses answerable lay questions too.** The scope check let all 24 answerable
  lay_mini questions through, but the answer model refused 3 ("What does the Income-tax Act call
  interest?", "I grow wheat ... is the money from selling the crops taxed?", "My mother is 62 and
  lives on FD interest..."), each time with the gold provision partly retrieved.
- **Amendment type 0.167 is a routing gap, not a retrieval one** (amendment recall@5 is 1.00):
  `route()` picks the amendment route only when the question names a provision, so a lay "did
  the 2026 budget change ..." question never gets v9's *What changed* block, and its answers say
  "raised" or "changed" without naming the change type.
- Citation precision 0.479 partly reflects narrow gold: a situation's gold is usually one
  provision, while the answer also cites the neighbouring ones it used.
- Cost: ~113K gpt-oss-120b tokens (one pass) and ~98K gpt-oss-20b tokens (drafting, scope
  checks) on 2026-10-12; Jina ~2.4K tokens (95 new query embeddings).

**Conclusion for Phase 16:** the system is a good statute lookup tool and a much weaker lay
advisor. The fixes in order: a lay scope prompt (first-person questions about what the Act says
are in scope), rewriting the question into the Act's vocabulary before retrieval (without
section numbers, which a 20b model would take from the 1961 Act), and routing on the rewrite so
amendment and table questions get their answer blocks. Tuned on `lay_dev` only; `lay_test` is
frozen for the final check.

## Phase 16: v10 (lay questions: one classifier call that scopes, rewrites and routes)

v10 is v9 with `agent: {scope_check: lay, rewrite: true}` and `weights.rewrite: 0.25`
(`configs/versions/v10.yaml`). v6's scope check is replaced by one gpt-oss-20b call,
`router.understand` (max 700 tokens), that returns:

- a **category**: forms / courts / other_law / own_case / current_facts / advice / act.
  `in_scope` is derived in code: a first version asked for a bare `in_scope` and the model
  answered true while its own reason said "asks which return form to file" (4 of 17 lay_dev
  refusals let through).
- **1-2 queries in the Act's vocabulary** ("deduction for interest on deposits with a savings
  account"), with any provision number removed (`clean_queries`), because the 20b model knows the
  1961 Act's numbering.
- a **kind** (amendment / table / definition / general) that picks v9's answer block.

The rewrites and kind-based routing are used only when the question names no provision and no
defined term; questions in the Act's own terms keep v9's path exactly. The rewrites are searched
densely beside the question (`hybrid.search(..., extra_qvecs)`) at 0.25 weight each.

**Tuned on lay_dev only** (cached 20b replies made the sweeps free):
- The category prompt says TCS by a seller of coal, scrap, cars or tour packages is income tax,
  that an income-tax term such as *stamp duty value* is "act", that PPF/FD/EPF rates are
  current_facts, and that a trailing "did the 2026 budget raise it?" is an amendment question.
  Where the model still ignored the prompt, small code overrides apply: TDS/TCS in words
  (`_AT_SOURCE_LAY`, with no GST mentioned) is never other law, and "budget"/"Finance Act" makes
  the kind amendment.
- Rewrite weight, recall@5 / MRR at 0 / 0.25 / 0.5 / 0.75 / 1.0: 0.795/0.705, **0.833/0.735**,
  0.808/0.711, 0.808/0.713, 0.788/0.695. At full weight two generic rewrites outrank the specific
  table row that the question's own embedding found.

**Then on dev (the old golden questions):** recall@5 0.940 (v8 0.940), MRR 0.915 (0.913), but the
lay prompt let two of 14 refusals through: "What is the penalty under the Black Money Act for
undisclosed foreign assets?" and "What does the Finance Bill, 2027 propose?". Two more code
overrides fixed both: a Finance Bill, Finance Act or budget for 2027 or later is current_facts
(`_FUTURE_BUDGET`; a "2027-28" tax year is not), and a penalty, punishment or prosecution "under
the *X* Act", where X is not the Income-tax Act, is other law (`_OTHER_ACT_PENALTY`). Naming such
an Act is not enough, because the Act itself cites the Black Money, Benami, Wealth-tax and FEMA
Acts. Over all 376 golden, lay and candidate questions the two rules fire only on those two. Dev
scope is then 1.00 / 1.00, which makes it a tuned number, not an independent one.

### Retrieval and scope, lay_dev (tuned) and lay_test (held out), recall@5 / MRR / hit@1

| | v8 | **v10** |
|---|---|---|
| lay_dev, all 78 answerable | 0.692 / 0.603 / 0.500 | **0.833 / 0.735 / 0.615** |
| lay_dev, situations (46) | 0.696 / 0.622 / 0.522 | 0.848 / 0.743 / 0.609 |
| lay_dev, paraphrases (32) | 0.688 / 0.575 / 0.469 | 0.812 / 0.724 / 0.625 |
| lay_dev, answerable refused | 8 / 78 | **1 / 78** |
| lay_dev, refusals caught | 17 / 17 | 17 / 17 |
| **lay_test, all 40 answerable** | 0.750 / 0.548 / 0.375 | **0.850 / 0.610 / 0.425** |
| lay_test, situations (25) | 0.840 / 0.556 / 0.360 | 0.920 / 0.577 / 0.360 |
| lay_test, paraphrases (15) | 0.600 / 0.533 / 0.400 | 0.733 / 0.667 / 0.533 |
| **lay_test, answerable refused** | 3 / 40 | **1 / 40** |
| **lay_test, refusals caught** | **5 / 5** | 3 / 5 |
| dev (138), recall@5 / MRR | 0.940 / 0.913 | 0.940 / 0.915 |

v2 on lay_dev, for reference: 0.788 / 0.683 / 0.577.

- **The held-out gain holds:** +0.10 recall@5 on lay_test (lookup 0.82 → 0.94, table 0.67 →
  0.83; amendment 0.71 and multi-step 0.75 unchanged), and fewer answerable questions refused
  (v10's one: "How much of my yearly advance tax should be paid by the middle of December?",
  called advice).
- **But the held-out scope check is worse: 3 of 5 refusals caught (v8 5 of 5).** v10 let through
  "Can my landlord legally raise my rent by 20% this year?" (tenancy law) and "What will next
  year's budget change for salaried people?" (a future budget with no year, which
  `_FUTURE_BUDGET` cannot see). Both are categories the prompt names; the 20b model still says
  "act", the same failure the dev overrides patched. They were not patched, since lay_test is held
  out, and with n = 5 it is two questions. Whether the answer model then refuses them was not
  measured (neither is in lay_mini).
- Amendment retrieval on lay_dev is v10's weak spot: 0.700 (v2 0.800).

### End-to-end, lay_mini (n = 30, drawn from lay_dev) and dev_mini (n = 30), against v9

| | Fact rec. | Exact | Cite prec. | Cite rec. | Grounded | Table exact | Amend. type | Refusal P / R | recall@5 | LLM tok/q |
|---|---|---|---|---|---|---|---|---|---|---|
| v9, lay_mini | 0.708 | 0.479 | 0.478 | 0.750 | 0.958 | 0.833 | 0.167 | 0.67 / 1.00 | 0.708 | 4,172 |
| **v10, lay_mini** | **0.854** | **0.708** | **0.644** | **0.833** | 0.953 | 0.833 | **1.000** | **0.86 / 1.00** | **0.792** | 4,548 |
| v9, dev_mini | 0.917 | 0.757 | 0.868 | 0.958 | 1.000 | 1.000 | 1.000 | 1.00 / 1.00 | 0.896 | 3,835 |
| **v10, dev_mini** | 0.917 | 0.743 | 0.868 | 0.958 | 1.000 | 1.000 | 1.000 | 1.00 / 1.00 | **0.917** | 4,257 |

- **Lay answers improve on every measure but grounded numbers** (−0.005). Amendment type 0.17
  → 1.00 is the kind routing: a "did the 2026 budget change ..." question now gets the *What
  changed* block. lay_mini is part of lay_dev, so these gains are measured on the tuning set.
- **dev_mini does not regress.** Per question: one citation-precision gain and one loss, one
  recall gain, and one strict-fact drop (multi_hop-24fe673c) with the soft score unchanged.
- **Cost:** the classifier call is ~830 tokens against v6's ~420, so v10 is ~4.3-4.5K tokens per
  question (~10% over v9).
- **v10 is the version the app runs** (chat, API, MCP; 2026-10-15).
- Cost of the phase: Groq's free tier only (gpt-oss-20b classification of lay_dev, dev and
  lay_test, re-run after each prompt change; ~110K gpt-oss-120b tokens for lay_mini) and ~1K Jina
  tokens for new query embeddings.

## Final numbers: frozen test split (n = 84, retrieval only)

The test split was frozen by checksum in Phase 3 and run once, at the end, with `--final`
(which verifies `test.ids` against `test.sha256`). **Only retrieval was run on test.** The planned
end-to-end runs (~1M gpt-oss-120b tokens, ~5-6 days of Groq's free tier) were stopped on
2026-10-07 by user decision; end-to-end numbers remain the dev_mini ones above.

| test (n = 84) | recall@5 | MRR | hit@1 | lookup | table | multi-hop | amendment | scope P / R |
|---|---|---|---|---|---|---|---|---|
| v0 | 0.493 | 0.403 | 0.324 | 0.526 | 0.810 | 0.423 | 0.067 | — |
| v1 | 0.507 | 0.413 | 0.338 | 0.579 | 0.762 | 0.500 | 0.067 | — |
| v2 | 0.640 | 0.586 | 0.515 | 0.895 | 0.952 | 0.423 | 0.067 | — |
| v3 | 0.904 | 0.849 | 0.779 | 0.947 | 0.952 | 0.654 | 1.000 | — |
| v4 | 0.904 | 0.849 | 0.779 | 0.947 | 0.952 | 0.654 | 1.000 | — |
| v5 | 0.912 | 0.850 | 0.779 | 1.000 | 0.905 | 0.692 | 1.000 | — |
| **v6 / v8** | **0.912** | **0.868** | **0.809** | 1.000 | 0.905 | 0.692 | 1.000 | 1.00 / 0.88 |

Per-type columns are recall@5 (lookup 19, table 21, multi-hop 13, amendment 15, refusal 16
questions). v4 and v8 change only the evidence text, not what is retrieved, so they equal v3 and
v6. Dev for comparison: v6 0.940 / 0.913 / 0.871.

- **The ladder's shape holds on unseen questions.** Structure (v2, +0.13 recall@5) and exact
  provision lookup (v3, +0.26; amendment 0.07 → 1.00) are the two big steps on test as on dev;
  cleaning (v1) is again noise.
- **The dev-tuned steps shrink, as predicted.** v5's cross-reference expansion gains +0.04
  multi-hop on test (+0.17 on dev) and costs one table question (0.952 → 0.905). v6's
  definitions tool and ranking lift MRR 0.850 → 0.868 and hit@1 0.779 → 0.809, smaller than on
  dev (0.882 → 0.913).
- **The scope check, tuned on dev to 1.00/1.00, is 1.00 / 0.875 on test**: it refused no
  answerable question, and let 2 of 16 out-of-scope questions through to retrieval (where the
  answer model can still refuse; that path was not measured on test).
- Multi-hop remains the weakest type (recall@5 0.69).

### Caveats

- dev_mini has 6 questions per type, so a single question moves a per-type score by 0.17. Treat per-type end-to-end differences under ~0.2 as noise. The 138-question retrieval numbers are the reliable signal.
- **Partial runs are not a preview of the full score.** v1's first attempt stopped at 19 of 30 on the Groq daily cap and read 0.588 fact recall; completing the same run over all 30 gave 0.465 (both before the
  2026-10-06 rescore). The questions are evaluated in a fixed order, so a truncated run is a biased sample, not an early estimate. Only rows with n = 30 are compared here.
- **v1 versus v0 on retrieval depends on the split.** On the 138-question dev set v1 edges v0 (recall@5 0.472 vs 0.460); on dev_mini the order reverses (0.500 vs 0.562). Both gaps are small, which is the point: cleaning has no real effect either way, and dev_mini is too small to resolve it.
- Table retrieval scores are inflated: templated table questions reuse the row's own wording.
- 220 of the 222 golden questions were bulk-accepted after spot checks, not individually verified.
- **`amendment_direction` covers only quoted word substitutions** (13 of 48 amendment questions)
  and abstains when an answer does not quote both wordings, so its n is small.
- **v6's scope prompt and the definitions tool's one-provision rule were both revised after
  looking at dev results.** The frozen test split is the check on both.
- Latency is not comparable across versions: most answers were replayed from cache, and v0's p50 rests on 6 measured calls.
