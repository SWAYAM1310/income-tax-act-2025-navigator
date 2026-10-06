# Project context (read this first)

_Last updated: 2026-10-06. **Phases 0-6 are DONE: the ladder v0-v5 is measured end-to-end.** v5 on dev_mini: fact recall 0.771 (oracle 0.833), citation precision 0.917, amendment type 0.833; dev retrieval recall@5 0.923. All end-to-end numbers were **rescored on 2026-10-06** after a `2 %` (U+202F) normalisation fix. A working chatbot exists (`python -m statnav.chat`). Update this file at the end of every session or phase._

> **Resume here:** see "Next steps" step 1 (Phase 7+). Start Docker Desktop first (`docker start tax_project-db-1` if the container exited; the pgvector container `tax_project-db-1` keeps its data in a named volume, so nothing needs rebuilding). The 2026-10-06 results + metric fix are **uncommitted** (ask before committing).

## Project in one paragraph
This is a RAG system that answers questions about India's **Income-tax Act, 2025** (as amended by the Finance Act 2026) with exact section-level citations. It handles cross-references, tables (e.g. section 393 TDS rates) and the 2026 amendments, and refuses out-of-scope questions. It is a portfolio project for Forward Deployed Engineer roles. The headline deliverable is a **versioned eval ladder (v0 naive → v7 full agent)** showing measured improvements. The full plan is at `C:\Users\ASUS\.claude\plans\pasted-content-id-77ca-project-steady-lemon.md`, rev. 2.

## Decisions (made by the user)
| Area | Choice |
|---|---|
| Agent LLM | Groq free tier: `openai/gpt-oss-120b` (answers) and `openai/gpt-oss-20b` (classify/verify/question drafting). Limits: 8K tokens/min and 200K tokens/day per model, enforced by `llm/client.py` (ledger in `.cache/llm.sqlite`). Evidence is capped at 4.5K tokens per prompt. |
| Embeddings | Jina API `jina-embeddings-v5-text-small` (1024-d, confirmed working), tasks `retrieval.passage` / `retrieval.query` |
| Reranker | **DROPPED (user decision, 2026-10-04): no reranker.** It was the only remaining billable item and v3 hit Phase 5's target without it (amendment recall@5 0.061 to 1.000 at zero cost). `JinaClient.rerank()` exists and is unused; the `reranks` cache table has 0 rows, so it has never been called. Do not enable it. |
| Vector store | Postgres 16 + pgvector 0.8.6 in Docker, port 5433 |
| LLM judge | None for now (deterministic metrics only) |
| Frontend | Vite + React + TS |
| Spending | **Keep everything free from here on (user, 2026-10-04).** Groq is a free tier (200K tokens/day) and covers all generation. Jina embeddings are the only billable service: ~1.4M tokens were spent building the indexes on 2026-10-02/03, and ongoing use is only ~10 tokens per new question (cached). No reranker. Still ask before any paid call or any Jina run over 1M tokens. No local ML. |
| Long-context baseline | Oracle-context baseline instead (`configs/versions/oracle.yaml`) |
| Secrets | Keys live in `.env` (gitignored). `.env.example` must stay blank; the user once pasted keys into it, and they were moved. |

## Status
- **Phase 0, scaffolding — DONE.**
- **Phase 1, ingestion — DONE.** `python -m statnav.ingest.qa` is all PASS:
  - 536/536 sections; 8,108 provision nodes (0 duplicate ids)
  - 152/152 endnotes linked; 98.1% of internal cross-refs resolved
  - 58 tables, 526 rows (0 duplicate row ids); 13 formula images transcribed
- **Phase 2, Jina + pgvector index — DONE.**

  | Index | Chunks | Jina tokens billed |
  |---|---|---|
  | v0 (raw text, 512-token windows) | 869 | 461,710 |
  | v1 (cleaned windows) | 801 | 425,030 |
  | v2 (provision / table-row chunks with breadcrumbs) | 2,936 | 513,300 |
  | **Total** | | **1,400,040** (+ a few thousand for query embeddings, all cached) |

  - Live fixtures pass (`pytest -m jina`): 2(5) is top-1 for "agricultural income"; 393 Sl. 1(i) is the #1 hit for insurance-commission TDS; 2(1) is in the top 5. The insurance query's top-5 evidence is 890 tokens.
- **Phase 3, golden dataset + harness + v0 — DONE (2026-10-03).** Exit check, end-to-end on dev_mini (30 questions; `results/report_dev_mini.md`):

  | | Recall@5 | MRR | Fact recall | Cite prec. | Table exact | Amend. type | Refusal P / R | LLM tok/q |
  |---|---|---|---|---|---|---|---|---|
  | v0 | 0.562 | 0.492 | 0.486 | 0.583 | 0.500 | 0.000 | 0.38 / 0.83 | 4,613 |
  | oracle | — | — | 0.778 | 1.000 | 0.667 | 0.667 | 1.00 / 0.83 | 920 |

  - Fact recall uses **soft matching** (user decision 2026-10-03, option A; `evals/metrics.py:fact_match`): exact match, or ≥80% of content words present with every number exact. The strict score is kept as `fact_recall_exact`, and table exact stays strict. I audited all 8 newly credited facts on dev_mini; there were no false positives. Oracle multi-hop went from 0.17 to 0.58.
  - Harness fixes (2026-10-03):
    - oracle refusals crashed on a missing `k` (they now use v2's `k`);
    - the oracle context now includes the linked amendment endnotes;
    - cached replies keep the latency measured when they were first generated;
    - the report marks incomplete runs.
- **Phase 4, v1 + v2 eval runs — DONE (2026-10-04).** The write-up is in `results/ladder.md`.
  - Retrieval on dev, recall@5 / MRR: v0 0.460 / 0.404; v1 0.472 / 0.391; **v2 0.589 / 0.578**. v2's lookup recall@5 is 0.91 (v0: 0.54). Amendment stays at 0.06 for every version.
  - End-to-end on dev_mini, all three versions now complete at n = 30 (`results/report_dev_mini.md`).
    **Pre-rescore numbers** (Phase 3/4 tables here); the rescored v1/v2/oracle rows are in the
    Phase 6 table below and in `results/ladder.md`:

    | | Fact recall | Cite prec. | Cite rec. | Grounded num. | Table exact | Amend. type | Refusal P / R | Evidence tok | LLM tok/q |
    |---|---|---|---|---|---|---|---|---|---|
    | v0 | 0.486 | 0.583 | 0.542 | 0.583 | 0.500 | 0.000 | 0.38 / 0.83 | 4,106 | 4,613 |
    | v1 | 0.465 | 0.542 | 0.500 | 0.558 | 0.500 | 0.000 | 0.42 / 0.83 | 4,106 | 4,622 |
    | v2 | **0.528** | **0.646** | **0.583** | **0.600** | **0.667** | **0.167** | 0.42 / 0.83 | **1,628** | **2,155** |
    | oracle | 0.778 | 1.000 | 0.917 | 0.925 | 0.667 | 0.667 | 1.00 / 0.83 | 460 | 920 |

  - **v1 (cleaning) is flat to slightly worse than v0 end-to-end at the same cost** — identical evidence tokens, 4,622 vs 4,613 LLM tokens. This matches the retrieval finding: tidying the text doesn't change which 512-token window a provision lands in. The gain comes from structural chunking (v2), which is both better and 53% cheaper per question.
  - **The completed v1 run replaced a misleading partial.** The 19/30 quota-truncated run read 0.588 fact recall; over all 30 it is 0.465. Questions run in a fixed order, so truncated runs are biased samples, not early estimates.
  - False refusals are mostly amendment questions where retrieval missed the endnote (v2 has 7 of 12).
  - Groq spend: 2026-10-03 gpt-oss-120b 193,661 tokens; 2026-10-04 gpt-oss-120b 50,939 tokens (11 new answers + 19 replayed from cache). The daily cap is 200K, with the client stopping at 195K.
- **Interactive chatbot — DONE (2026-10-04),** built out of plan order at the user's request so answer quality could be inspected directly rather than only through metrics.
  - `src/statnav/answer.py` holds the shared generation path: `SYSTEM_PROMPT`, `pack()` (greedy evidence packing), `user_prompt()`, `parse_citations()`, and an `Answerer` class (`for_version()`, `.ask()` → `Answer`). `evals/run.py` imports all of it, so **the chat and the ladder cannot drift apart.**
  - Verified behaviour-preserving: re-running v2 on dev_mini after the refactor produced `metrics.json` and `outputs.jsonl` **byte-identical** to the committed ones, at zero token cost (all replies cached).
  - `src/statnav/chat.py` is the CLI: one-shot or REPL, with `/evidence`, `/k`, `/version`, `/tokens`, `/help`, `/quit`. Logs are suppressed unless `--verbose`. An error renders as `UNAVAILABLE`, never as an answer.
  - `tests/test_answer.py`: 7 offline tests (44 total now).
  - What the live answers showed, beyond what the metrics say:
    - **Lookup is genuinely good** — "how is agricultural income defined" returns all of s2(5) clauses (a)–(d) plus both exclusions, cited to `v2:s2(5)` p.2.
    - **Table answers under-extract rather than hallucinate.** For insurance-commission TDS the model retrieved the exactly right row (`s393:tbl1#1(i)`) and said "Rates in force", which the row genuinely says — but it dropped the row's **"Threshold limit: Rs. 20,000"**. So `table_exact` 0.667 is a *generation* gap (one field missed from a passage it already had), not retrieval and not hallucination. A prompt change ("report every rate, threshold and condition in the cited row") is the fix, not Phase 5's retrieval work.
    - **Amendment questions refuse,** confirming the 0.06 amendment recall end-to-end.
- **Phase 5, v3 hybrid retrieval — retrieval DONE (2026-10-04).** Write-up in `results/ladder.md`.
  - v3 keeps v2's chunks and changes retrieval only: dense k-NN fused by RRF with two
    provision-id lookups driven by references parsed from the question
    (`src/statnav/retrieve/ids.py`). The parser resolves the exact gold id for **all 48**
    amendment questions in the golden set.
  - Retrieval on dev (n = 138), v3 against v2:

    | | recall@5 | MRR | hit@1 |
    |---|---|---|---|
    | v2 | 0.589 | 0.578 | 0.516 |
    | **v3** | **0.879** | **0.882** | **0.831** |

    Per type recall@5 / MRR / hit@1 — amendment **0.061/0.028/0.000 → 1.000/1.000/1.000**;
    multi-hop 0.500/0.621/0.500 → 0.656/0.829/0.750; lookup 0.914/0.843/0.800 →
    0.914/0.826/0.771; table 0.958/0.892/0.833 → 0.958/0.872/0.792.
  - **Amendment retrieval is solved.** Every dev amendment question now ranks its gold
    provision first. Lookup/table recall@5 is untouched; their hit@1 is within one question of
    v2 (24 table questions = 0.042 each).
  - Two corrections found by measurement, not design (both are why the config is shaped as it is):
    - Boosting only the *exact* id drove **table hit@1 0.833 → 0.000**: section 393's own chunk
      is a 36-token heading and the rates live in `s393:tbl1#...`, so a stub took rank 1. Fixed
      by a second retriever (`under`) returning the provision *and descendants* ordered by
      embedding similarity — ids give the candidate set, the embedding gives the order.
    - Ordering only by embedding then lost amendment again (1.000 → 0.121). Fixed by fusing
      both lists and dropping from the exact list any heading stub or **container** (a provision
      whose content sits in deeper chunks). That test is structural, so it separates "the
      question names the answer" from "the question names where to look" **without a question
      classifier**. MRR 0.848 → 0.882, table hit@1 0.583 → 0.792.
  - **FTS is implemented, tested and OFF.** `ts_rank` has no IDF and `simple` keeps stop words,
    so a natural question ANDed matches nothing (verified 0 rows) and OR-ing ranks badly. Even
    restricted to rare terms it cost lookup (0.800 vs 0.914). It *did* lift multi-hop (0.719 vs
    0.656), so `retrievers: [dense, fts, ids, under]` stays available for v4.
  - **Retrieval recall does not reach amendment *answers* yet.** Asked "How was section 99(2)
    amended by the Finance Act, 2026?", v3 retrieves `v2:s99(2)` at rank 1 and still refuses:
    the chunk carries only the `[...]` brackets marking amended text, while the endnote (type
    `substituted`, `amending_act`, `prior_text`) sits in the `amendments` / `amendment_links`
    tables and is never attached. The oracle gets those endnotes, which is why it reaches
    amendment type 0.667 against v2's 0.167. **Attaching linked endnotes to retrieved
    provisions is the next real win** (planned as v6) and is the prerequisite for amendment
    answers, not more retrieval work.
  - Cost: **0 API tokens** for the whole retrieval phase (dev query embeddings cached, id
    lookups are pure Postgres).
- **v4, amendment endnotes in the evidence — BUILT (2026-10-04), end-to-end measurement pending.**
  - `src/statnav/retrieve/amend.py` appends each retrieved chunk's linked endnotes to its own
    text (and re-counts tokens, or packing would overflow the budget). Enabled by
    `retrieval: {endnotes: true}` in `configs/versions/v4.yaml`. It uses the same
    `Endnote {label}: {header} {prior_text}` shape the oracle context uses, so v4 and the
    ceiling are directly comparable.
  - **Why it exists:** v3 ranks `v2:s99(2)` first for "How was section 99(2) amended?" and still
    refuses. The chunk carries only the `[...]` brackets marking amended words; the change is in
    the endnote, which the chunkers keep out of the chunk. v4 now puts this in the rank-1
    passage:
    `Endnote 11: Sub. for "sub-section (1)(a)(i) or (b)" by Act No. 4 of 2026, w.e.f. 1-4-2026.`
  - `header` carries the change type, the replaced words and the effective date, and is present
    for all 152 endnotes; `prior_text` is populated for 76 of them.
  - Evidence cost on dev, v4 against v3: +260 tokens on average (1,765 -> 2,025), max 4,241
    against the 4,500 budget, so nothing is truncated. Per type: table +648 (the largest, and
    the least likely to need it), amendment +309, multi-hop +194, refusal +152, lookup +50.
  - Ladder numbering deviates from the plan deliberately: the plan has v4 as cross-reference
    expansion and v6 as amendment linking, but measurement showed endnotes, not
    cross-references, are what block amendment answers.
- **v5, one-hop cross-reference expansion — retrieval DONE (2026-10-04, uncommitted).**
  - `hybrid.xref_hits` takes the top 3 fused hits' provisions, follows `cross_refs` in both
    directions, and orders the neighbouring chunks by embedding similarity; `hybrid.slot_merge`
    keeps the top 4 untouched and gives places 5-6 to them. Config `configs/versions/v5.yaml`
    (cumulative: includes v4's endnotes).
  - Dev (n = 138), v5 vs v3: recall@5 0.879 -> **0.923**, recall@10 0.903 -> 0.944, MRR and hit@1
    unchanged (0.882 / 0.831). Multi-hop recall@5 0.656 -> **0.828**; lookup, table and amendment
    unchanged. Zero API cost.
  - Pre-check: 19 of the 20 multi-hop misses were one cross-reference hop from a v3 top-5 hit.
  - RRF-fusing the expansion wrecked ranking (lookup hit@1 0.771 -> 0.457), hence the slot merge.
    keep 3 + 2 scored multi-hop 0.859 but dropped table recall@5 0.958 -> 0.917 (one question),
    so keep 4 + 2 was chosen. ~20 settings were tried on dev, so expect a smaller gain on test.
- **Phase 6, v3/v4/v5 end-to-end on dev_mini — DONE (runs finished 2026-10-05, written up
  2026-10-06 in `results/ladder.md`).** All n = 30 complete, no `incomplete`.

  | | Fact rec. | Cite prec. | Cite rec. | Grounded | Table exact | Amend. type | Refusal P / R | LLM tok/q |
  |---|---|---|---|---|---|---|---|---|
  | v2 | 0.583 | 0.646 | 0.583 | 0.683 | 1.000 | 0.167 | 0.42 / 0.83 | 2,155 |
  | v3 | 0.604 | 0.729 | 0.646 | 0.772 | 1.000 | 0.167 | 0.50 / 0.83 | 2,123 |
  | v4 | 0.750 | 0.896 | 0.833 | 1.000 | 0.833 | 0.833 | 0.83 / 0.83 | 2,335 |
  | v5 | **0.771** | **0.917** | **0.854** | 0.952 | 0.833 | 0.833 | 0.83 / 0.83 | 2,454 |
  | oracle | 0.833 | 1.000 | 0.917 | 1.000 | 1.000 | 0.667 | 1.00 / 0.83 | 920 |

  - **Answer to the open question: yes.** v3 alone was ~v2 end-to-end (amendment fact recall 0.17);
    v4's endnotes take amendment fact recall to 0.75 (= oracle), amendment type 0.167 → 0.833,
    false refusals 5 → 1. Biggest end-to-end step on the ladder (+0.15 fact recall, +212 tok/q).
  - v5: multi-hop fact recall 0.42 → 0.50 (one question, f6e5a319). Remaining gap to the oracle is
    lookup (0.83 vs 1.00) and multi-hop (0.50 vs 0.58).
  - **Metric fix (2026-10-06):** `evals/common.py:norm` now maps `2 %` / `2 %` to `2%`. The
    model writes percentages with U+202F, so correct table answers scored 0 (v5 table exact
    looked like 0.333; it is 0.833) and their numbers counted as ungrounded. All 7 dev_mini rows
    were rescored from cache (answers/retrieval/citations byte-identical, 0 Groq tokens); v1-v5 and
    the oracle moved, v0 did not. Tests added in `tests/test_eval_metrics.py` (86 offline pass).
  - The last v4/v5 table miss (a8fea698) is wording: "the rate 'in force'" vs gold "Rates in force".
- Earlier Phase 3 notes:
  - **222 candidates** in `evals/data/candidates.jsonl`: lookup 54 (32 templated definitions + 22 LLM-drafted numeric), table 45, amendment 48, multi-hop 45 (LLM-drafted from cross-reference pairs), refusal 30. Drafting used ~40K gpt-oss-20b tokens.
  - **All 222 accepted into `evals/data/golden.jsonl`.** The user reviewed 2 individually and then explicitly instructed bulk acceptance of the other 220 (2026-10-02). These are logged as `bulk-accept (user instruction)` in `verification_log.csv`. They were not individually edited, so the README must say the questions were spot-checked, not individually verified.
  - Splits (by hash of the question id) — **test is FROZEN** (`evals/splits/test.sha256`):
    - dev: 138 (lookup 35, table 24, amendment 33, multi-hop 32, refusal 14)
    - test: 84
    - dev_mini: 30 (6 per type)
  - Harness pieces:
    - `evals/run.py`: retrieval + end-to-end runs; results in `results/<version>/<split>/`
    - `evals/metrics.py`: recall@k, MRR, fact recall, citation precision/recall, grounded numbers, table exact, amendment type, prior-text F1, refusal P/R, latency, tokens
    - `evals/splits.py` (stable hash splits; test can be frozen) and `evals/report.py` (markdown table + PNG)
  - End-to-end smoke test (v2, 6 unverified candidates) works. Fact matching canonicalises money ("₹50 lakh" = "Fifty lakh rupees").
  - **Provisional** retrieval-only numbers on the 222 unverified candidates (not reportable; re-run on dev after review). Each cell is recall@5 / MRR:

    | | overall | lookup | table | multi-hop | amendment |
    |---|---|---|---|---|---|
    | v0 | 0.471 / 0.403 | 0.54 | 0.84 | 0.46 | 0.06 |
    | v1 | 0.484 / 0.398 | 0.57 | 0.84 | 0.47 | 0.06 |
    | v2 | 0.607 / 0.581 | 0.91 | 0.96 | 0.48 | 0.06 |

    - Cleaning (v1) barely helps retrieval.
    - Structural chunks (v2) are the big lookup/table jump.
    - Amendment retrieval is ~0 at every version: dense embeddings ignore section numbers, which is the target for v3's exact-ID boost and v6's amendment linking.
    - Multi-hop is stuck at ~0.47, the target for v4's cross-reference expansion.
  - **Reportable so far: v0 retrieval-only on dev** (138 questions; `results/v0/dev/`). Each cell is recall@5 / MRR:

    | overall | lookup | table | multi-hop | amendment |
    |---|---|---|---|---|
    | **0.460 / 0.404** | 0.54 / 0.45 | 0.88 / 0.68 | 0.47 / 0.52 | 0.06 / 0.04 |

  - **Groq spend on 2026-10-02 (UTC):** gpt-oss-120b 123,182 tokens (6 smoke + 24 v0 questions); gpt-oss-20b 42,816 (question drafting). v0 costs **~4.6K tokens per question**, not the ~3K I estimated, because its 512-token windows fill the 4.5K evidence budget. Expect v2 to be cheaper per question.
  - 35 tests pass (32 offline + 3 live Jina).

## How to run
Docker Desktop must be running.
```
python -m uv sync
python -m uv run python tasks.py check             # lint + db up/load + offline tests + Jina ping
.venv/Scripts/python.exe -m statnav.ingest.build   # parse PDF (cached)
.venv/Scripts/python.exe -m statnav.ingest.qa      # ingestion scorecard
.venv/Scripts/python.exe -m statnav.index.load     # artefacts -> Postgres
.venv/Scripts/python.exe -m statnav.index.build --version v2 [--dry-run]   # embed + pgvector
.venv/Scripts/python.exe -m statnav.retrieve.search "how is agricultural income defined" -k 5
.venv/Scripts/python.exe -m statnav.chat                       # interactive chatbot (v2)
.venv/Scripts/python.exe -m statnav.chat "<question>"          # one-shot; --evidence, --version, --verbose
.venv/Scripts/python.exe -m evals.build.generate [--llm]   # (re)draft candidates; never overwrites reviewed ones
.venv/Scripts/python.exe -m evals.review --reviewer <name> [--type table]   # HUMAN REVIEW (a/e/r/s/q)
.venv/Scripts/python.exe -m evals.splits [--freeze]  # dev / test / dev_mini from golden.jsonl
.venv/Scripts/python.exe -m evals.run --version v0 --split dev --retrieval-only
.venv/Scripts/python.exe -m evals.run --version v0 --split dev_mini            # end-to-end (Groq)
.venv/Scripts/python.exe -m evals.run --version oracle --split dev_mini
.venv/Scripts/python.exe -m evals.report --split dev
```
Pseudo-splits for pipeline checks only: `candidates` (all non-rejected, unverified) and `smoke` (`evals/data/smoke_ids.txt`).

## Code map
- `src/statnav/ingest/`: PDF → artefacts (`data/parsed/7db7feb6-v3/`)
- `src/statnav/embed/`: Jina client, sqlite cache, token counting
- `src/statnav/index/`: schema, loader, chunkers (v0/v1/v2), index build
- `src/statnav/retrieve/`: `dense.py` (pgvector k-NN; returns `embed_text` with breadcrumbs), `search.py`
- `src/statnav/answer.py`: the generation path shared by the chat and `evals/run.py` (prompt, evidence packing, citation parsing, `Answerer`)
- `src/statnav/chat.py`: interactive/one-shot CLI chatbot
- `src/statnav/llm/client.py`: Groq chat with cache, rate limiter and daily ledger
- `configs/`: `base.yaml`, `models.yaml` (roles; list prices empty until verified), `versions/{v0,v1,v2,oracle}.yaml`
- `evals/`: `common.py` (norm, artefacts), `build/generate.py`, `review.py`, `splits.py`, `run.py`, `metrics.py`, `report.py`
- Ids:
  - provisions `s2(5)(b)`; tables `s393:tbl1`; rows `s393:tbl1#1(i)`
  - chunks `v2:<id>`; table notes `v2:s393:tbl1:note3`; window chunks `v0:<n>`

## Next steps (in order)

**Everything below is free: Groq's free tier covers generation, and the rest is Postgres.**

0. **Ask the user whether to commit** the 2026-10-06 work: the v3/v4/v5 dev_mini results, the
   rescored v0-v2/oracle results, the `norm()` fix + tests, `results/ladder.md`, and the report.
1. **Phases 7–11 per the plan** (the retrieval ladder through v5 is built; v4 endnotes and v5
   cross-reference expansion are done): LangGraph agent with table/amendment routing and a
   citation verifier, MCP + FastAPI, Vite frontend, CI + README. The chat already works
   (`python -m statnav.chat`, default v5), so a web UI over `statnav.answer.Answerer` can start
   without waiting on the agent.
2. Consider a prompt step that makes table answers report **every** field of a cited row: the
   model retrieves the right row and faithfully reports the rate but drops the threshold
   (e.g. the Rs. 20,000 on `s393:tbl1#1(i)`, seen in the chat). Lower priority now: after the
   rescore, table fact recall is 1.00 on dev_mini from v2 on. Keep it as its own ladder version so
   it is not confounded with a retrieval change. The same step could ask the model to quote
   table cells verbatim ("Rates in force").
3. Before reporting on **test**, run v5 (and oracle) end-to-end on more than dev_mini's 30
   questions; per-type differences on dev_mini are one question (0.17) each. A full dev run is
   ~138 × 2.4K ≈ 330K tokens, i.e. two Groq days.
4. Optional: FTS (`retrievers: [dense, fts, ids, under]`) lifted multi-hop on dev but cost
   lookup; revisit only if multi-hop is still weak after the end-to-end numbers.
5. Optional: reword the templated table questions in **dev** that copy row text, since they
   inflate table scores. The test split is frozen, so it can't change.

## Known issues
- **Tables:** section 204's unnumbered rate table has 0 rows; section 352's table has stray `(i)` text before row 1; section 52's table row 3 has one stray word.
- **Cross-references:** 95 internal references don't resolve exactly.
- **Templated table questions copy the row text,** which inflates table retrieval scores. They were not reworded, because the dataset was bulk-accepted.
- **Dataset provenance:** 220 of 222 golden questions were bulk-accepted on the user's instruction without per-item edits. State this in the README; don't describe them as individually human-verified.
- **Multi-hop gold facts are partly weak** (LLM-drafted, e.g. multi_hop-071d02c9, multi_hop-343e19fd). Soft matching fixed the paraphrase misses (oracle 0.17 → 0.58), but the weak facts remain.
- **dev_mini is small** (6 per type): one question moves a per-type score by 0.17.
- **Quota-truncated runs produce biased scores, not early estimates.** Questions are evaluated in a fixed order, so a partial run over-weights whatever types come first. v1's 19/30 run read 0.588 fact recall against 0.465 over the full 30. Only compare rows where `run_meta.json` has `n_completed == n_questions` and no `incomplete` field; `evals/report.py` marks the rest.
- **Latency:** most answers were replayed from cache; v0's p50 rests on 6 measured calls. Don't compare latency across versions yet.
- **Oracle refusal recall is 0.83:** one refusal question was answered from the v2 distractor passages.
- **Amendment questions name a provision number;** dense retrieval can't match on numbers (expected; v3 fixes this).
- **Table answers drop fields they already retrieved.** The model returns the right row but omits a second column (e.g. the Rs. 20,000 threshold on `s393:tbl1#1(i)`). This is a generation gap, not retrieval — a prompt change is the fix, and it should be a *separate* ladder step so it isn't confounded with v3's retrieval changes.
- **The per-minute rate limiter is in-process only.** The daily ledger is shared in `.cache/llm.sqlite`, but the 8K tokens/min window lives in each `ChatClient`. So running the chat right after an eval run triggers real provider 429s (`QuotaExhausted: provider says retry after ...`, seen up to ~1000s) even with the daily cap nowhere near. Leave a few minutes between an eval run and interactive use, or persist the window.
- **`amendment_type` is a keyword check** (does the answer contain the change-type stem). It
  can't see direction: on s99(2) the oracle states the substitution backwards and v4 states it
  correctly, and neither difference is scored. v4/v5's 0.833 against the oracle's 0.667 is one
  question of noise ("amended" vs gold "inserted").
- **Strict fact matching still uses substring containment,** so a gold `2%` would also match
  inside `12%`. This has not been seen in outputs; worth a word-boundary check if the metric changes again.
- **Citation parsing is case-sensitive:** a lowercase `"c1"` from the model is silently dropped. Pinned by `tests/test_answer.py::test_parse_citations_is_case_sensitive_today`, because widening it would move the committed citation scores. Revisit when a version changes the prompt.
- **Groq throttling is almost certainly a rolling 24-hour token window, not a per-minute limit
  (hypothesis, 2026-10-04; the 429 body was not captured).** Evidence: a direct request was
  accepted while the same run was being 429'd with 11-15 minute `Retry-After`s; the response
  headers showed ~7,900 of 8,000 per-minute tokens and 982 of 1,000 requests free; and the
  backoffs are the 10-15 minute size you would expect while yesterday's ~194K tokens age out of
  the window. Consequence: a dev_mini run advances ~2 answers per 15 minutes until yesterday's
  spend leaves the window (about 03:00-06:00 UTC the next day), then the full allowance returns.
  Plan for **v3 + v4 + v5 end-to-end (~170K tokens) to take ~12 hours of wall clock**.
  `llm/client.py` treats any `Retry-After` over 120s as `QuotaExhausted`, so a rolling-window
  wait and the true daily cap look the same in `run_meta.json`. Sleep the reported retry-after
  plus a margin between passes (`scripts/e2e_queue.sh` does); eager retries do not help.
- **Git:** public repo https://github.com/SWAYAM1310/income-tax-act-2025-navigator (branch `main`). The `gh` CLI is at `C:\Program Files\GitHub CLI\gh.exe`, logged in as SWAYAM1310. Ask before committing or pushing.

## Environment gotchas
- Windows + Git Bash. For heredoc-Python file patches, use raw strings (`\b` becomes a backspace) and no backslash line continuations; prefer the Edit tool. Run `ruff check src tests evals tasks.py` after patches.
- Set `PYTHONIOENCODING=utf-8` when printing Act text.
- `python-dotenv`'s `load_dotenv()` with no path crashes in stdin scripts; pass `".env"`.
- Ruff: `known-first-party = ["statnav", "evals"]`.
