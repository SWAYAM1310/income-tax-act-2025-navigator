# Statute Navigator: Income-tax Act, 2025

An amendment-aware question-answering system over the Income-tax Act, 2025 (as amended by the Finance Act, 2026). It returns exact section-level citations, and a versioned evaluation pipeline tracks each improvement.

> **Not tax advice.** This project answers questions about the text of the Act only. It does not compute anyone's tax liability, and it does not cover the Income-tax Rules, forms, circulars or case law.

Status: under construction.

## Quick start (development)

```
python -m pip install --user uv
python -m uv sync                 # deps (embeddings + reranking use the Jina API)
cp .env.example .env              # add JINA_API_KEY (and GROQ_API_KEY from Phase 3)
python -m uv run python tasks.py check
```

Project status and next steps live in [context.md](context.md).
