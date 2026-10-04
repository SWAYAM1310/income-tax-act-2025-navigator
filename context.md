# Project context (read this first)

_Last updated: 2026-10-04. **Phases 0–4 are all DONE** and committed/pushed to `main`. The eval ladder through v2 is written up in `results/ladder.md`. There is now also a **working interactive chatbot** (`python -m statnav.chat`) sharing the eval harness's exact generation path. **Phase 5 (v3: hybrid FTS + RRF + reranker + section-ID boost) is in progress.** Update this file at the end of every session or phase._

> **Resume here:** see "Next steps" step 1. Start Docker Desktop first (`docker start tax_project-db-1` if the container exited; the pgvector container `tax_project-db-1` keeps its data in a named volume, so nothing needs rebuilding).

## Project in one paragraph
This is a RAG system that answers questions about India's **Income-tax Act, 2025** (as amended by the Finance Act 2026) with exact section-level citations. It handles cross-references, tables (e.g. section 393 TDS rates) and the 2026 amendments, and refuses out-of-scope questions. It is a portfolio project for Forward Deployed Engineer roles. The headline deliverable is a **versioned eval ladder (v0 naive → v7 full agent)** showing measured improvements. The full plan is at `C:\Users\ASUS\.claude\plans\pasted-content-id-77ca-project-steady-lemon.md`, rev. 2.

## Decisions (made by the user)
| Area | Choice |
|---|---|
| Agent LLM | Groq free tier: `openai/gpt-oss-120b` (answers) and `openai/gpt-oss-20b` (classify/verify/question drafting). Limits: 8K tokens/min and 200K tokens/day per model, enforced by `llm/client.py` (ledger in `.cache/llm.sqlite`). Evidence is capped at 4.5K tokens per prompt. |
| Embeddings | Jina API `jina-embeddings-v5-text-small` (1024-d, confirmed working), tasks `retrieval.passage` / `retrieval.query` |
| Reranker | Jina API `jina-reranker-v3.5` (from v3) |
| Vector store | Postgres 16 + pgvector 0.8.6 in Docker, port 5433 |
| LLM judge | None for now (deterministic metrics only) |
| Frontend | Vite + React + TS |
| Spending | **Ask before any paid API call or any Jina run over 1M tokens.** No local ML. |
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
  - End-to-end on dev_mini, all three versions now complete at n = 30 (`results/report_dev_mini.md`):

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
1. **Phase 5 — v3 hybrid retrieval (IN PROGRESS).** Postgres FTS + dense with RRF, the Jina reranker (`jina-reranker-v3.5`, cached) and an exact section-ID boost. The target is **amendment retrieval, stuck at 0.06 recall@5 at every version** because dense embeddings can't match on provision numbers; the section-ID boost is the specific fix. Lookup (0.91) and table (0.96) are already near ceiling, so the headroom is amendment and multi-hop (~0.50).
   - Add `configs/versions/v3.yaml`, extend `src/statnav/retrieve/` with FTS + RRF + rerank, then:
     ```
     .venv/Scripts/python.exe -m evals.run --version v3 --split dev --retrieval-only
     .venv/Scripts/python.exe -m evals.run --version v3 --split dev_mini
     .venv/Scripts/python.exe -m evals.report --split dev
     ```
   - Reranker calls are paid Jina usage — **ask before the first live rerank run** and check the token estimate.
   - Budget the end-to-end run: ~50K Groq tokens per dev_mini version against the 200K/day cap, so at most ~3 full dev_mini runs per day.
2. **Phases 6–11 per the plan:** LangGraph agent with cross-reference expansion (targets multi-hop), table/amendment routing, citation verifier, MCP + FastAPI, Vite frontend, CI + README.
3. Optional: reword the templated table questions in **dev** that copy row text, since they inflate table scores. The test split is frozen, so it can't change.

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
- **Citation parsing is case-sensitive:** a lowercase `"c1"` from the model is silently dropped. Pinned by `tests/test_answer.py::test_parse_citations_is_case_sensitive_today`, because widening it would move the committed citation scores. Revisit when a version changes the prompt.
- **Git:** public repo https://github.com/SWAYAM1310/income-tax-act-2025-navigator (branch `main`). The `gh` CLI is at `C:\Program Files\GitHub CLI\gh.exe`, logged in as SWAYAM1310. Ask before committing or pushing.

## Environment gotchas
- Windows + Git Bash. For heredoc-Python file patches, use raw strings (`\b` becomes a backspace) and no backslash line continuations; prefer the Edit tool. Run `ruff check src tests evals tasks.py` after patches.
- Set `PYTHONIOENCODING=utf-8` when printing Act text.
- `python-dotenv`'s `load_dotenv()` with no path crashes in stdin scripts; pass `".env"`.
- Ruff: `known-first-party = ["statnav", "evals"]`.
