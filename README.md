# Income-tax Act, 2025 navigator

Ask a question about India's **Income-tax Act, 2025, as amended by the Finance Act, 2026**, and
get an answer that quotes the Act and cites the exact provisions it relies on. It handles
definitions, the rate tables (TDS/TCS under sections 393 and 394), the 2026 amendments, and
questions that need two provisions linked by a cross-reference. It refuses questions the Act
cannot answer (the Rules, forms, circulars, case law, the e-filing portal, personal advice).

> **Not tax advice.** The system answers from the text of the Act only and can be wrong or
> incomplete. Read the cited provision before relying on an answer.

The project is built as an **eval ladder**: each version changes one thing, is scored on the
same questions, and is kept or rejected on the numbers. The write-up of every step, including
the ones that did not work, is in [`results/ladder.md`](results/ladder.md).

## Results

End to end on `dev_mini` (30 questions: 6 each of lookups, rate tables, amendments, multi-step
questions and out-of-scope questions), answers from `openai/gpt-oss-120b` on Groq's free tier;
retrieval on `dev` (138 questions).

| | What changed | Top-5 recall (dev) | Facts found | Citations correct | Amendment type | Refusals right / caught | LLM tokens / q |
|---|---|---|---|---|---|---|---|
| v0 | raw page text, 512-token windows, dense retrieval | 0.460 | 0.542 | 0.583 | 0.000 | 0.38 / 0.83 | 4,613 |
| v1 | header/footer clean-up | 0.472 | 0.521 | 0.542 | 0.000 | 0.42 / 0.83 | 4,622 |
| v2 | one chunk per provision, with its place in the Act | 0.589 | 0.583 | 0.646 | 0.167 | 0.42 / 0.83 | 2,155 |
| v3 | hybrid retrieval: dense + exact provision ids (RRF) | 0.879 | 0.604 | 0.729 | 0.167 | 0.50 / 0.83 | 2,127 |
| v4 | the Act's amendment endnotes attached to the evidence | 0.879 | 0.771 | 0.896 | 0.833 | 0.83 / 0.83 | 2,342 |
| v5 | one-hop cross-reference expansion | 0.923 | 0.792 | 0.917 | 0.833 | 0.83 / 0.83 | 2,444 |
| v6 | LangGraph agent: scope check, definition lookup, structured endnotes | 0.940 | 0.875 | 0.958 | 1.000 | 1.00 / 1.00 | 2,531 |
| v7 | v6 + an LLM claim checker (kept as a gate only) | — | 0.875 | 0.958 | 1.000 | 1.00 / 1.00 | 4,625 |
| **v8** | **v6 + endnotes that state the wording before and after** | **0.940** | **0.875** | **0.958** | **1.000** | **1.00 / 1.00** | 2,532 |
| oracle | the gold provisions handed to the model (ceiling) | — | 0.833 | 1.000 | 0.667 | 1.00 / 0.83 | 920 |

What the ladder shows:

- **Structure beats cleaning.** Tidying the text (v1) changed nothing; one chunk per provision
  (v2) cut tokens per question by 53% and lifted every score.
- **Numbers need exact lookup.** Amendment questions name a provision ("How was section 99(2)
  amended?"), and embeddings carry no signal for a number: amendment retrieval was 0.06 until v3
  looked the reference up by id (1.00).
- **Retrieval was not the bottleneck for amendments; evidence was.** v3 found the right provision
  every time and still could not answer, because what changed lives in the Act's endnotes. v4
  attached them: amendment-type accuracy 0.17 → 0.83, the largest single step.
- **v6 beats the gold-passage "oracle"** (0.875 vs 0.833) because it changes what the model sees,
  not just what is retrieved: a scope check refuses out-of-scope questions before retrieval,
  the defining clause of a term goes first, and endnotes say in words what changed and where.
- **Negative results are kept.** v7's claim checker found nothing to fix and its citations were
  worse than the answer model's, so it ships as a retry gate only, at +83% tokens. A mutation
  test (`evals/verifier_check.py`) shows what the gate is worth: it flagged 6 of 6 answers with a
  corrupted rate or amount and 0 of 4 with a corrupted effective date, with no false flags on
  the originals (catch rate 0.60). It also passed the answers that state an amendment backwards.
- **A metric gap found by looking at answers.** The frontend's Before / Now view showed answers
  stating amendments backwards, which `amendment_type` (a keyword check) cannot see. The Act's
  `Sub. for "60%"` means 60% is the *old* wording, and the model read it the other way. A new
  `amendment_direction` metric scored v6 0 of 3 and the gold-passage oracle 2 of 6 on dev's
  quoted substitutions. v8 spells out `wording before / wording now` in the evidence: **7 of 7**,
  at the same cost, with every other score unchanged. v8 is the version the app runs.

Honest caveats (more in [`results/ladder.md`](results/ladder.md#caveats)):

- `dev_mini` is small: one question moves a per-type score by 0.17. The 138-question retrieval
  numbers are the steadier signal.
- 220 of the 222 golden questions were **bulk-accepted after spot checks**, not individually
  verified; the multi-step questions' expected facts are partly weak (LLM-drafted).
- Some choices were tuned on dev (v5's expansion slots, v6's scope prompt). The test split (84
  questions) is frozen by checksum and is used only for the final numbers.
- `amendment_direction` covers only the 13 amendment questions whose endnote quotes the replaced
  words, and abstains when an answer does not quote both wordings, so its n is small.

### Final numbers on the frozen test split

84 questions, frozen by checksum before any tuning and run once at the end. Retrieval only:
end-to-end test runs (about a week of Groq's free tier) were not done, so the answer-quality
numbers above stay the dev_mini ones.

| test (n = 84) | Top-5 recall | MRR | Right passage first | Amendment top-5 | Multi-step top-5 |
|---|---|---|---|---|---|
| v0 | 0.493 | 0.403 | 0.324 | 0.067 | 0.423 |
| v2 | 0.640 | 0.586 | 0.515 | 0.067 | 0.423 |
| v3 | 0.904 | 0.849 | 0.779 | 1.000 | 0.654 |
| v5 | 0.912 | 0.850 | 0.779 | 1.000 | 0.692 |
| **v6 / v8** | **0.912** | **0.868** | **0.809** | **1.000** | 0.692 |

The two big steps (structural chunks, exact provision lookup) hold on unseen questions; the
steps tuned on dev shrink, as expected (v5's multi-step gain is +0.04 on test against +0.17 on
dev). The out-of-scope check, 1.00 / 1.00 on dev, refuses no answerable test question and
catches 14 of 16 out-of-scope ones. All versions in
[`results/ladder.md`](results/ladder.md#final-numbers-frozen-test-split-n--84-retrieval-only).

## How it works

```
                       PDF (666 pages)
                             |
   ingest: layout -> provisions (8,108), tables (58, 526 rows), endnotes (152),
           cross-references (5,437), hand-transcribed formula images (13)
                             |
   index: one chunk per provision with its breadcrumb -> Jina embeddings -> Postgres + pgvector
                             |
   agent (LangGraph):  classify --(out of scope)--> refuse
                          \--> retrieve: dense + provision-id lookups (RRF) + one-hop
                               cross-references; endnotes attached
                          --> tools: defined-term lookup  --> pack (4.5K tokens) --> generate
                             |
   served by: FastAPI (SSE) | MCP server (5 tools) | CLI chat | Vite + React UI
```

The chat UI streams answers token by token. Groq cannot stream in JSON mode, so the chat calls
the model without it and reads the answer out of the JSON as it arrives. That call is cached
separately, so a chat answer can differ slightly from the measured one; the evals never stream.

- **Ingestion** (`src/statnav/ingest/`) parses the official PDF into provisions with stable ids
  (`s2(5)(b)`, `sch:XIV:4(3)`, table rows `s393:tbl1#1(i)`), links each Finance Act, 2026
  endnote to the words it amends, and resolves 98% of internal cross-references.
- **Retrieval** (`src/statnav/retrieve/`) fuses dense k-NN with exact provision-id lookups
  parsed from the question, then reserves two slots for provisions one cross-reference away.
- **The agent** (`src/statnav/agent/`) is a LangGraph graph; routing is deterministic regexes,
  and the only LLM call before generation is a gpt-oss-20b scope check.
- **Generation** (`src/statnav/answer.py`) is one prompt shared by every version, the chat, the
  API and the eval harness, so what the UI shows is what the ladder measures.
- **Evals** (`evals/`) are deterministic: retrieval recall/MRR, fact recall (exact or ≥80% of
  content words with every number exact), citation precision/recall, grounded numbers, table
  exactness, amendment type and direction, refusal precision/recall, tokens. There is no LLM
  judge.

## Run it

Requirements: Python 3.11 with [uv](https://docs.astral.sh/uv/), Docker, Node 22 for the UI.
Keys (free tiers): `GROQ_API_KEY` for answers, `JINA_API_KEY` for query embeddings. Copy
`.env.example` to `.env` and fill them in.

```bash
python -m uv sync
docker compose up -d db
```

The database needs the index. Either **restore the published dump** (19 MB; parsed Act +
embeddings, see the [release notes](https://github.com/SWAYAM1310/income-tax-act-2025-navigator/releases/tag/index-2026-10-06)):

```bash
curl -LO https://github.com/SWAYAM1310/income-tax-act-2025-navigator/releases/download/index-2026-10-06/statnav-index-2026-10-06.dump
bash scripts/db_restore.sh statnav-index-2026-10-06.dump
```

or **build it** from the official PDF (place `Income-tax-Act-2025.pdf` in the repo root; its
SHA-256 is checked against `configs/base.yaml`). The embedding step spends about 1.4M Jina tokens
and asks before any run over 1M:

```bash
python -m uv run python -m statnav.ingest.build
python -m uv run python -m statnav.index.load
python -m uv run python -m statnav.index.build --version v2
```

Then:

```bash
python -m uv run python -m statnav.chat "What is the meaning of \"transfer\"?"   # CLI
python -m uv run python -m statnav.api           # API on :8000, docs at /docs
cd frontend && npm install && npm run dev         # UI on :5173 (chat history stays in the browser)
docker compose up                                 # or everything: UI on http://localhost:8080
python -m uv run python -m statnav.mcp_server     # MCP server over stdio
```

Evaluate:

```bash
python -m uv run python -m evals.run --version v6 --split dev --retrieval-only
python -m uv run python -m evals.run --version v6 --split dev_mini     # end to end (Groq)
python -m uv run python -m evals.report --split dev_mini
python -m uv run python tasks.py check            # lint, database load, offline tests
```

Every LLM reply and embedding is cached (`.cache/`), so re-running an eval costs nothing.

## Repository

| Path | What is there |
|---|---|
| `src/statnav/ingest/` | PDF → provisions, tables, endnotes, cross-references |
| `src/statnav/index/` | schema, loader, chunkers (v0-v2), embedding build |
| `src/statnav/retrieve/` | dense, hybrid (RRF + id lookups + cross-reference expansion), endnotes |
| `src/statnav/agent/` | the LangGraph agent: router, scope check, definitions, verifier |
| `src/statnav/answer.py` | the one generation path |
| `src/statnav/api/`, `mcp_server.py`, `chat.py`, `repo.py` | the API, MCP tools, CLI, Act lookups |
| `frontend/` | the UI (Vite + React + TS) and its Playwright smoke test |
| `evals/` | golden set, splits, harness, metrics, report, verifier mutation test |
| `configs/versions/` | one YAML per ladder version |
| `results/` | every run's metrics and outputs, `ladder.md` (the write-up) |

## Stack

Groq (`openai/gpt-oss-120b` answers, `openai/gpt-oss-20b` scope check and verifier) · Jina
`jina-embeddings-v5-text-small` · Postgres 16 + pgvector · LangGraph · FastAPI · MCP Python SDK
· React 19 + Vite · Playwright. Everything runs on free tiers.
