"""Compare ladder versions: markdown table + chart for the README.

    python -m evals.report --split dev            # writes results/report_<split>.md and .png

Reads results/<version>/<split>/metrics.json for every version that has run on the split.
"""

from __future__ import annotations

import argparse
import json

from evals.common import RESULTS_DIR
from statnav.config import CONFIG_DIR, load_yaml

ORDER = ["v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "oracle"]
COLUMNS = [
    ("recall@5", "Recall@5"), ("mrr", "MRR"), ("fact_recall", "Fact recall"),
    ("citation_precision", "Cite prec."), ("table_exact", "Table exact"),
    ("amendment_type", "Amend. type"), ("refusal_recall", "Refusal rec."),
    ("latency_p50_s", "p50 s"), ("llm_tokens_mean", "LLM tok/q"),
]


def collect(split: str) -> list[tuple[str, dict, dict]]:
    out = []
    for v in ORDER:
        f = RESULTS_DIR / v / split / "metrics.json"
        if f.exists():
            meta_f = f.with_name("run_meta.json")
            meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
            out.append((v, json.loads(f.read_text()), meta))
    return out


def markdown(rows: list[tuple[str, dict, dict]]) -> str:
    head = "| Version | What changed | n | " + " | ".join(c[1] for c in COLUMNS) + " |"
    sep = "|" + "---|" * (len(COLUMNS) + 3)
    lines = [head, sep]
    for v, m, meta in rows:
        desc = load_yaml(CONFIG_DIR / "versions" / f"{v}.yaml").get("description", "")
        mode = " (retrieval only)" if meta.get("retrieval_only") else ""
        if meta.get("incomplete"):
            mode += (f" **(incomplete: {meta.get('n_completed')}/{meta.get('n_questions')};"
                     " not comparable)**")
        cells = []
        for key, _ in COLUMNS:
            val = m.get(key)
            cells.append("—" if val is None else (f"{val:.3f}" if isinstance(val, float)
                                                   else str(val)))
        lines.append(f"| {v} | {desc}{mode} | {m['n']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def chart(rows: list[tuple[str, dict, dict]], path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keys = [("recall@5", "Retrieval recall@5"), ("fact_recall", "Answer fact recall"),
            ("citation_precision", "Citation precision")]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    xs = [v for v, _, _ in rows]
    for key, label in keys:
        ys = [m.get(key) for _, m, _ in rows]
        if any(y is not None for y in ys):
            ax.plot(xs, [y if y is not None else float("nan") for y in ys], marker="o",
                    label=label, linewidth=2)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("score")
    ax.set_title("Income-tax Act 2025 navigator: eval ladder")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    a = ap.parse_args()
    rows = collect(a.split)
    if not rows:
        raise SystemExit(f"no results for split {a.split}")
    md = markdown(rows)
    (RESULTS_DIR / f"report_{a.split}.md").write_text(md + "\n", encoding="utf-8")
    chart(rows, RESULTS_DIR / f"report_{a.split}.png")
    print(md)


if __name__ == "__main__":
    main()
