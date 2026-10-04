"""Ask the Act a question from the command line.

    python -m statnav.chat                                  # interactive
    python -m statnav.chat "how is agricultural income defined"
    python -m statnav.chat --version v0 "..."               # compare a ladder version
    python -m statnav.chat --evidence "..."                 # also print the passages used

Answers come from the same prompt and retrieval the eval ladder measures, so quality here
matches `results/report_dev_mini.md`. Every answer is grounded in retrieved passages: the
citations name the provisions and pages it relied on. Replies are cached, so repeating a
question costs no tokens.

In interactive mode: /evidence, /k <n>, /version <v>, /tokens, /help, /quit.
"""

from __future__ import annotations

import argparse
import logging
import textwrap

from statnav.answer import Answer, Answerer
from statnav.obs.logging import configure

WRAP = 96


def _fmt(res: Answer, show_evidence: bool) -> str:
    out = []
    # an error (rate limit, provider failure) is not an answer and must not read like one
    tag = "UNAVAILABLE" if res.error else ("REFUSED" if res.refused else "ANSWER")
    out.append(f"\n{tag}")
    out.append(textwrap.fill(res.answer or "(empty)", WRAP,
                             initial_indent="  ", subsequent_indent="  "))
    if res.cited:
        out.append("\nCITED")
        for h in res.cited:
            provs = ", ".join(h.get("provisions") or []) or "-"
            pages = (f"pp. {h['page_start']}-{h['page_end']}"
                     if h.get("page_start") else "no page")
            out.append(f"  {h['chunk_id']}  {pages}  covers: {provs}")
    elif not res.refused and not res.error:
        out.append("\nCITED\n  (none - the model named no passage; treat the answer as "
                   "ungrounded)")
    if show_evidence:
        out.append("\nEVIDENCE SENT")
        for n, h in enumerate(res.evidence, 1):
            used = "*" if h in res.cited else " "
            out.append(f" {used}[C{n}] {h['chunk_id']}  {h['tokens']} tok  "
                       f"score {h.get('score')}")
            out.append(textwrap.indent(textwrap.shorten(h["text"], 220), "      "))
    cost = "cached (0 new tokens)" if res.cached else f"{res.llm_tokens} LLM tokens"
    out.append(f"\n  [{len(res.evidence)} passages, {res.evidence_tokens} evidence tokens; "
               f"{cost}; {res.latency_s}s]")
    if res.error:
        out.append(f"  [error: {res.error}]")
    return "\n".join(out)


HELP = """commands:
  /evidence        toggle printing the passages sent to the model
  /k <n>           retrieve n passages (default: the version's k)
  /version <v>     switch ladder version (v0, v1, v2)
  /tokens          Groq tokens spent today
  /quit            exit"""


def repl(bot: Answerer, show_evidence: bool) -> None:
    print(f"Income-tax Act, 2025 navigator - version {bot.version} "
          f"(chunks {bot.chunks}, k={bot.k}, {bot.budget}-token evidence budget)")
    print("Ask a question, or /help for commands. Ctrl-C to quit.")
    k: int | None = None
    while True:
        try:
            line = input("\nask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line[1:].partition(" ")
            cmd, arg = cmd.lower(), arg.strip()
            if cmd in {"quit", "exit", "q"}:
                return
            if cmd == "help":
                print(HELP)
            elif cmd == "evidence":
                show_evidence = not show_evidence
                print(f"evidence printing {'on' if show_evidence else 'off'}")
            elif cmd == "k":
                k = int(arg) if arg.isdigit() else None
                print(f"k = {k or bot.k}")
            elif cmd == "version":
                if arg in {"v0", "v1", "v2"}:
                    bot.close()
                    bot = Answerer.for_version(arg)
                    print(f"version {arg} (chunks {bot.chunks}, k={bot.k})")
                else:
                    print("version must be v0, v1 or v2")
            elif cmd == "tokens":
                print(f"{bot.llm.model}: {bot.llm.spent_today():,} tokens spent today")
            else:
                print(f"unknown command /{cmd}; try /help")
            continue
        print(_fmt(bot.ask(line, k), show_evidence))


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the Income-tax Act, 2025 a question.")
    ap.add_argument("question", nargs="*", help="omit for an interactive session")
    ap.add_argument("--version", default="v2", help="ladder version (default: v2, the best)")
    ap.add_argument("-k", type=int, default=None, help="passages to retrieve")
    ap.add_argument("--evidence", action="store_true", help="print the passages sent")
    ap.add_argument("--verbose", action="store_true", help="show the JSON pipeline logs")
    a = ap.parse_args()
    # the per-call JSON logs are noise in a conversation; keep them behind --verbose
    configure(logging.INFO if a.verbose else logging.WARNING)
    with Answerer.for_version(a.version) as bot:
        if a.question:
            print(_fmt(bot.ask(" ".join(a.question), a.k), a.evidence))
        else:
            repl(bot, a.evidence)


if __name__ == "__main__":
    main()
