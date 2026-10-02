# Instructions for Claude

1. **Before doing any work, read `context.md`.** It holds the project summary, the user's decisions, current status, how to run things and the ordered next steps. Continue from its "Next steps" unless the user asks for something else.
2. **Before ending a session, or when a phase finishes, update `context.md`:** the date, Status (with the numbers from that phase's exit check), Next steps, and Known issues. Keep it short and factual.
3. Ask before any paid API call or any Jina run estimated above 1M tokens (`python -m statnav.index.build --dry-run` prints the estimate). Ask before committing to git.
4. After code changes run `python -m uv run python tasks.py check` (lint, DB load, offline tests).
