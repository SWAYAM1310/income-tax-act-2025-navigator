# Project context (read this first)

_Last updated: 2026-10-02 (end of session). Phase 2 is done. Phase 3 is mid-way: the dataset is accepted, splits are frozen and v0 retrieval on dev is done; the v0 and oracle end-to-end runs are paused by the Groq daily quota. Update this file at the end of every session or phase._

> **Resume here:** see "Next steps" step 1. Start Docker Desktop first (the pgvector container `tax_project-db-1` keeps its data in a named volume, so nothing needs rebuilding).

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
- **Phase 3, golden dataset + harness + v0 — IN PROGRESS (exit runs started).**
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

  - **v0 end-to-end on dev_mini: paused at 24 of 30.** Those 24 answers are in `.cache/llm.sqlite`, so a re-run replays them for free and only calls Groq for the last 6. Nothing was written to `results/v0/dev_mini/` yet; the harness writes at the end of a run.
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
- `src/statnav/llm/client.py`: Groq chat with cache, rate limiter and daily ledger
- `configs/`: `base.yaml`, `models.yaml` (roles; list prices empty until verified), `versions/{v0,v1,v2,oracle}.yaml`
- `evals/`: `common.py` (norm, artefacts), `build/generate.py`, `review.py`, `splits.py`, `run.py`, `metrics.py`, `report.py`
- Ids:
  - provisions `s2(5)(b)`; tables `s393:tbl1`; rows `s393:tbl1#1(i)`
  - chunks `v2:<id>`; table notes `v2:s393:tbl1:note3`; window chunks `v0:<n>`

## Next steps (in order)
1. **Finish the Phase 3 exit runs**. The Groq daily quota resets at 00:00 UTC (05:30 IST). Run these one at a time:
   ```
   .venv/Scripts/python.exe -m evals.run --version v0 --split dev_mini       # 24 cached + 6 new (~28K tokens)
   .venv/Scripts/python.exe -m evals.run --version oracle --split dev_mini   # ~30 x 2.5K = ~75K tokens
   .venv/Scripts/python.exe -m evals.report --split dev_mini
   .venv/Scripts/python.exe -m evals.report --split dev
   ```
   If a run prints `incomplete` (quota), just re-run it the next day; cached answers are free.
2. Then commit the results and push (ask the user first).
3. **Phase 4:**
   - `evals.run` for v1 and v2 on dev (retrieval-only, free) and on dev_mini end-to-end (v2 needs ~2–3K tokens per question);
   - `evals.report`;
   - write up the deltas.
4. **Phase 5:** hybrid Postgres FTS + RRF, Jina reranker (`jina-reranker-v3.5`, cached) and an exact section-ID boost, which targets amendment retrieval (0.06 now). Then Phases 6–11 per the plan: LangGraph agent with cross-reference expansion, table/amendment routing, citation verifier, MCP + FastAPI, Vite frontend, CI + README.
5. Optional: reword the templated table questions in **dev** that copy row text, since they inflate table scores. The test split is frozen, so it can't change.

## Known issues
- **Tables:** section 204's unnumbered rate table has 0 rows; section 352's table has stray `(i)` text before row 1; section 52's table row 3 has one stray word.
- **Cross-references:** 95 internal references don't resolve exactly.
- **Templated table questions copy the row text,** which inflates table retrieval scores. They were not reworded, because the dataset was bulk-accepted.
- **Dataset provenance:** 220 of 222 golden questions were bulk-accepted on the user's instruction without per-item edits. State this in the README; don't describe them as individually human-verified.
- **Amendment questions name a provision number;** dense retrieval can't match on numbers (expected; v3 fixes this).
- **Git:** public repo https://github.com/SWAYAM1310/income-tax-act-2025-navigator (branch `main`). The `gh` CLI is at `C:\Program Files\GitHub CLI\gh.exe`, logged in as SWAYAM1310. Ask before committing or pushing.

## Environment gotchas
- Windows + Git Bash. For heredoc-Python file patches, use raw strings (`\b` becomes a backspace) and no backslash line continuations; prefer the Edit tool. Run `ruff check src tests evals tasks.py` after patches.
- Set `PYTHONIOENCODING=utf-8` when printing Act text.
- `python-dotenv`'s `load_dotenv()` with no path crashes in stdin scripts; pass `".env"`.
- Ruff: `known-first-party = ["statnav", "evals"]`.
