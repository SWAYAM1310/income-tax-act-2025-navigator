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
  1,00,000 → Rs 300001, 1-April → 4-April) and asks the checker about both versions. Result:
  *pending (scheduled after the 2026-10-07 quota reset)*.
- Cost of the phase: 52,425 gpt-oss-20b tokens (the re-run as a gate replayed every check from
  cache); 0 gpt-oss-120b.

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
