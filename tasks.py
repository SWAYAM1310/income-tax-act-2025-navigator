"""Cross-platform task runner (stands in for a Makefile; Windows has no `make`).

Usage: python -m uv run python tasks.py <task>
  check   lint + offline tests + DB health (+ Jina ping when JINA_API_KEY is set)
  lint    ruff check
  test    pytest, excluding tests that call the Jina API
  db      docker compose up -d db, health check, load structured artefacts
  jina    embed two strings to check the Jina key, model and dimensions
  index   build the v2 vector index (Jina embeddings -> pgvector)
"""

from __future__ import annotations

import os
import subprocess
import sys


def run(*cmd: str) -> None:
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode not in (0, 5):  # pytest exits 5 when no tests are collected
        sys.exit(result.returncode)


def lint() -> None:
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "evals", "tasks.py")


def test() -> None:
    run(sys.executable, "-m", "pytest", "-q", "-m", "not jina")


def db() -> None:
    run("docker", "compose", "up", "-d", "--wait", "db")
    run(sys.executable, "-m", "statnav.store.health")
    run(sys.executable, "-m", "statnav.index.load")


def jina() -> None:
    run(sys.executable, "-m", "statnav.embed.jina")


def index() -> None:
    run(sys.executable, "-m", "statnav.index.build", "--version", "v2")


def check() -> None:
    lint()
    db()
    test()
    from dotenv import load_dotenv

    load_dotenv()
    if os.environ.get("JINA_API_KEY"):
        jina()
    else:
        print("JINA_API_KEY not set: skipping the Jina ping")


TASKS = {"check": check, "lint": lint, "test": test, "db": db, "jina": jina, "index": index}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    TASKS[sys.argv[1]]()
