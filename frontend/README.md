# Frontend

Vite + React + TypeScript + Tailwind CSS v4 over the FastAPI app in `src/statnav/api` (v8, the
LangGraph agent). Black, with one green accent; turmeric marks only words the Finance Act, 2026
changed.

- **Welcome** (first visit, or the logo): a recorded answer plays over a map of the Act, one mark
  per section (1-536). It needs no server.
- **Chat**: answers stream in as the model writes them, after the agent's steps. Each answer
  shows:
  - citation chips;
  - a strip showing where its passages sit among the 536 sections;
  - the passages it was written from;
  - a Copy button.

  A citation opens the provision as printed:
  - the section heading as a marginal note;
  - the clause hierarchy;
  - words changed by the Finance Act, 2026 marked;
  - a *Now / Before* toggle;
  - the endnotes.

  Each question is answered on its own; the API never sees earlier turns.
- **Sidebar**: chats grouped by day, with search, rename, export as Markdown and delete. History
  lives in this browser's `localStorage` (`statnav.chats.v1`) and nowhere else.
- **Settings**: green shade (Jade, Mint, Forest), text size, and reduced motion (stored as
  `statnav.prefs`).
- **How well it answers**: the eval ladder (`results/*/dev_mini`, `results/*/dev`) as charts and
  a table.
- Keys: Ctrl/⌘+K starts a new chat, `/` focuses the question box, and Esc closes the provision
  or the chat list.

Streaming: Groq cannot stream in JSON mode, so the chat path calls the model without it, using
the same prompt, and pulls the `"answer"` text out of the JSON as it arrives
(`statnav.answer.AnswerTextStream`). That reply is cached apart from the measured one, so a
chat answer can differ slightly from the one the eval ladder scored. The evals never stream.

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
`query-s99-2.sse` has its answer split into word-sized `token` events. `query-cut-off.sse` is
the same stream stopped after eight tokens, with no `answer` event.
