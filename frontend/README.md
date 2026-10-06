# Frontend

Vite + React + TypeScript over the FastAPI app in `src/statnav/api` (v6, the LangGraph agent).

- **Ask the Act**: a question streams its agent steps, the answer and its citation chips. A
  citation opens the provision as printed: the section heading as a marginal note, the clause
  hierarchy, words changed by the Finance Act, 2026 marked, a *Now / Before* toggle and the
  endnotes.
- **How well it answers**: the eval ladder (`results/*/dev_mini`, `results/*/dev`) as charts and
  a table.

```
python -m statnav.api            # from the repo root: the API on :8000 (needs Postgres)
cd frontend
npm install
npm run dev                      # http://localhost:5173, /api is proxied to :8000
npm run build && npx vite preview
npm run test:e2e                 # Playwright smoke test (API mocked with e2e/fixtures; no keys)
npm run shots -- <dir>           # screenshots of the main flows (needs the API + vite preview)
```

The e2e fixtures were captured from the real API. Re-capture them when the API's response shapes
change, e.g. `curl -s "localhost:8000/provisions/s99(2)" > e2e/fixtures/provision-s99-2.json`.
