"""Draft golden-dataset candidates from the parsed Act. Every candidate is human-reviewed
(evals/review.py) before it can enter a split.

    python -m evals.build.generate                # templated types only (no LLM)
    python -m evals.build.generate --llm          # + LLM-drafted lookup and multi-hop questions

Sources and gold labels:
  lookup     section 2 definitions (template) + numeric facts in provisions (LLM-drafted)
  table      section 393 TDS rows (rate + threshold) and other rate/amount tables (template)
  amendment  Finance Act 2026 endnotes linked to provisions (template; gold type + prior text)
  multi_hop  provision -> cross-referenced provision pairs (LLM-drafted, both are gold)
  refusal    hand-written out-of-scope questions (Rules, forms, case law, personal advice...)

Facts (`gold_facts`) are short strings that must appear in a correct answer; every fact is
checked to occur verbatim in the gold provision text, otherwise the candidate is dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re

from evals.common import (
    CANDIDATES,
    artefacts,
    cite,
    contains,
    read_jsonl,
    subtree_text,
    write_jsonl,
)

SEED = 2026
# an answer-worthy amount: a percentage, a rupee amount, an "N lakh/crore" phrase, nil, or
# "rates in force"; bare small integers ("Note 3") are not facts
NUM_RE = re.compile(
    r"\d+(?:\.\d+)?\s?%|Rs\.\s*\d[\d,]*(?:\.\d+)?|\b(?:\w+|\d+)\s+(?:lakh|crore)\s+rupees\b"
    r"|\bnil\b|\brates in force\b", re.I)


def _id(kind: str, key: str) -> str:
    return f"{kind}-{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def candidate(kind: str, key: str, question: str, gold_answer: str, facts: list[str],
              provisions: list[str], *, rows: list[str] | None = None,
              amendment: dict | None = None, refuse: bool = False, source: str = "template",
              note: str = "") -> dict:
    return {
        "id": _id(kind, key), "type": kind, "question": question, "gold_answer": gold_answer,
        "gold_facts": facts, "gold_provisions": provisions, "gold_table_rows": rows or [],
        "gold_amendment": amendment, "should_refuse": refuse, "source": source,
        "note": note, "status": "unverified",
    }


# -- lookup: definitions -------------------------------------------------------------------
DEF_TEMPLATES = [
    'How does the Income-tax Act, 2025 define "{term}"?',
    'What is the meaning of "{term}" under the Income-tax Act, 2025?',
    'Under section 2 of the Act, what does "{term}" mean?',
]


def lookup_definitions(n: int, rng: random.Random) -> list[dict]:
    a = artefacts()
    prov = a["provisions"]
    pool = []
    for cid in prov["s2"]["children"]:
        p = prov[cid]
        m = re.match(r'^\[?\s*"([^"]+)"(?:[^"]*?"[^"]+")*\s+(means|includes)\b\s*[—-]?\s*(.*)',
                     p["text"])
        if not m:
            continue
        body = subtree_text(cid)
        after = m.group(3).strip(" —-")
        words = (after or "").split()
        if len(words) < 4:  # "means—" followed by a list: take the first item instead
            first = next((prov[c]["text"] for c in p["children"] if prov[c]["text"]), "")
            words = first.split()
        if len(words) < 4:
            continue
        fact = " ".join(words[:7]).rstrip(";,.")
        if not contains(body, fact):
            continue
        pool.append((cid, m.group(1), fact, body))
    rng.shuffle(pool)
    out = []
    for k, (cid, term, fact, body) in enumerate(pool[:n]):
        q = DEF_TEMPLATES[k % len(DEF_TEMPLATES)].format(term=term)
        out.append(candidate("lookup", cid, q, body[:700], [fact], [cid],
                             note="definition (template)"))
    return out


# -- table -----------------------------------------------------------------------------------
def _desc(row: dict) -> str:
    nature = next((v for k, v in row["cells"].items() if k.lower().startswith("nature")), "")
    nature = re.sub(r"^\([ivx]+\)\s*", "", nature)
    nature = re.sub(r"\s+", " ", nature).strip().rstrip(".")
    words = nature.split()
    short = " ".join(words[:16]) + ("..." if len(words) > 16 else "")
    head = row["row_heading"]
    return f"{head.lower()}: {short}" if head and head.lower() not in short.lower() else short


def _facts(*cells: str) -> list[str]:
    out = []
    for c in cells:
        for m in NUM_RE.findall(c or ""):
            m = m.strip()
            if m and m not in out:
                out.append(m)
    return out


def table_questions(n: int, rng: random.Random) -> list[dict]:
    a = artefacts()
    out = []
    for rid, r in a["rows"].items():
        tid = r["table_id"]
        payer = r["cells"].get("Payer", "")
        if tid in ("s393:tbl1", "s393:tbl3") and r.get("rate") and r.get("threshold"):
            who = "a resident" if tid == "s393:tbl1" else "any person"
            payer_clean = re.sub(r"\s*\[[^\]]*\]", "", payer).rstrip(".").lower()
            payer_s = f" when paid by {payer_clean}" if payer_clean else ""
            q = (f"Under section 393, what are the TDS rate and the threshold limit for "
                 f"{_desc(r)}{payer_s}, where the payee is {who}?")
            facts = _facts(r["rate"], r["threshold"])
            if not facts:
                continue
            ans = f"Rate: {r['rate']} Threshold limit: {r['threshold']}"
            out.append(candidate("table", rid, q, ans, facts[:3], [tid], rows=[rid],
                                 note="section 393 rate/threshold (template)"))
        elif tid == "s393:tbl2" and r["cells"].get("Rate"):
            facts = _facts(r["cells"]["Rate"])
            if not facts:
                continue
            q = (f"Under section 393, at what rate is tax deducted on {_desc(r)} paid to a "
                 f"non-resident?")
            out.append(candidate("table", rid, q, f"Rate: {r['cells']['Rate']}", facts[:3],
                                 [tid], rows=[rid], note="section 393(2) non-resident rate"))
        elif tid.startswith("s394") and any("rate" in k.lower() for k in r["cells"]):
            col = next(k for k in r["cells"] if "rate" in k.lower())
            facts = _facts(r["cells"][col])
            nature = next((v for k, v in r["cells"].items() if k.lower().startswith("nature")),
                          "")
            if not facts or not nature:
                continue
            q = (f"What is the rate of tax collection at source under section 394 on "
                 f"{nature.rstrip('.').lower()[:120]}?")
            out.append(candidate("table", rid, q, f"{col}: {r['cells'][col]}", facts[:3], [tid],
                                 rows=[rid], note="section 394 TCS rate"))
    rng.shuffle(out)
    return out[:n]


# -- amendments ------------------------------------------------------------------------------
VERB = {"substituted": "substituted", "inserted": "inserted", "omitted": "omitted",
        "renumbered": "renumbered"}


def amendment_questions(n: int, rng: random.Random) -> list[dict]:
    a = artefacts()
    prov = a["provisions"]
    out = []
    seen_targets = set()
    for fn in a["amendments"]:
        if not fn["linked_nodes"] or fn["type"] not in VERB:
            continue
        target = fn["linked_nodes"][0]
        if target not in prov or ":tbl" in target or target in seen_targets:
            continue
        seen_targets.add(target)
        where = cite(target)
        facts = [VERB[fn["type"]]]
        amendment = {"type": fn["type"], "prior_text": fn["prior_text"],
                     "effective_date": fn["effective_date"], "footnote": fn["key"]}
        if fn["prior_text"]:
            q = (f"What change did the Finance Act, 2026 make to {where}, and what did the "
                 f"provision say before the amendment?")
            prior = re.sub(r"^[\s'\"\u201c\u2018]*(?:\(\w+\)\s*)+", "", fn["prior_text"])
            prior_words = prior.split()
            facts.append(" ".join(prior_words[:6]).rstrip(",;"))
            ans = f"{fn['header']} Earlier text: {fn['prior_text'][:500]}"
        else:
            q = f"How was {where} amended by the Finance Act, 2026?"
            quoted = re.findall(r'"([^"]+)"', fn["header"])
            facts += quoted[:1]
            ans = fn["header"]
        out.append(candidate("amendment", fn["key"], q, ans, facts, [target],
                             amendment=amendment, note=f"endnote {fn['label']} p{fn['page']}"))
    rng.shuffle(out)
    return out[:n]


# -- refusals --------------------------------------------------------------------------------
REFUSALS = [
    ("What does Rule 114 of the Income-tax Rules say about PAN applications?", "Rules"),
    ("Which ITR form should a salaried individual use for the 2026-27 tax year?", "forms"),
    ("What did CBDT Circular No. 1 of 2026 clarify about TDS on salaries?", "circular"),
    ("How did the Supreme Court decide the Vodafone indirect transfer case?", "case law"),
    ("What is the due date to e-file my return on the income tax portal this year?", "procedure"),
    ("I earn Rs. 18 lakh a year from salary; how much tax will I pay?", "personal computation"),
    ("Should I choose the new tax regime or the old one for my family?", "advice"),
    ("What is the GST rate on restaurant services?", "other law: GST"),
    ("Under the Income-tax Act, 1961, what did section 80C allow?", "repealed Act"),
    ("How do I link my Aadhaar with my PAN online?", "procedure"),
    ("What is the current cost inflation index notified for 2026-27?", "notification"),
    ("How do I respond to a notice I received on the e-filing portal?", "procedure"),
    ("What is the tax treaty rate on dividends between India and the USA?", "treaty"),
    ("Can you calculate the advance tax instalments for my freelance income of Rs. 9 lakh?",
     "personal computation"),
    ("What are the stamp duty rates in Maharashtra for property transfers?", "other law"),
    ("What does the Companies Act, 2013 require for CSR spending?", "other Act"),
    ("Which CBDT instruction governs faceless assessment timelines?", "instruction"),
    ("How do I claim a refund that is stuck on the portal?", "procedure"),
    ("What is the interest rate on PPF deposits this quarter?", "outside the Act"),
    ("What did the Delhi High Court rule on reassessment notices in 2024?", "case law"),
    ("How much tax should I deduct from my maid's salary?", "personal computation"),
    ("Is cryptocurrency legal tender in India?", "outside the Act"),
    ("What is the corporate tax rate in Singapore?", "foreign law"),
    ("Which form is used to apply for a lower TDS certificate, and how do I fill it?", "forms"),
    ("Who is the current Chairman of the CBDT?", "outside the Act"),
    ("What is the penalty under the Black Money Act for undisclosed foreign assets?",
     "other Act"),
    ("Give me a strategy to minimise my capital gains tax on selling my flat.", "advice"),
    ("What does the Finance Bill, 2027 propose?", "future law"),
    ("What are the e-way bill requirements for inter-state transport?", "other law: GST"),
    ("How many taxpayers filed returns last year?", "statistics"),
]


def refusal_questions() -> list[dict]:
    return [candidate("refusal", q, q, "Out of scope: the Act does not contain this. (" + why
                      + ")", [], [], refuse=True, source="hand-written", note=why)
            for q, why in REFUSALS]


# -- LLM-drafted: numeric lookups and multi-hop ---------------------------------------------
LOOKUP_PROMPT = """You write evaluation questions for a question-answering system over the
Income-tax Act, 2025 (India). Using ONLY the provision below, write one specific question a tax
professional might ask whose answer is stated in this provision. Do not mention the provision
number unless needed for disambiguation; do not ask yes/no questions.
Then list 1-3 short facts (each 1-8 words, copied VERBATIM from the provision text) that a
correct answer must contain, such as a number, period, rate or condition.
Return JSON: {{"question": "...", "answer": "<1-2 sentence answer>", "facts": ["..."]}}

Provision ({where}):
{text}"""

MULTIHOP_PROMPT = """You write evaluation questions that require following a cross-reference
in the Income-tax Act, 2025 (India). Provision A refers to provision B. Write one natural
question whose correct answer needs information from BOTH A and B (the question should be
about A's subject, but the key detail lives in B). Do not quote the provision numbers of B.
Then list 1-3 short facts (each 1-8 words) copied VERBATIM from B's text that a correct
answer must contain.
Return JSON: {{"question": "...", "answer": "<1-3 sentence answer>", "facts": ["..."]}}

Provision A ({a_where}):
{a_text}

Provision B ({b_where}):
{b_text}"""


def _llm_json(llm, prompt: str) -> dict | None:
    from statnav.llm.client import LLMError

    try:
        return llm.chat([{"role": "user", "content": prompt}], json_mode=True).json()
    except (LLMError, ValueError):
        return None


def llm_lookups(n: int, rng: random.Random, llm) -> list[dict]:
    a = artefacts()
    prov = a["provisions"]
    pool = [p for p in prov.values()
            if p["kind"] in ("sub-section", "clause") and not p["id"].startswith("s2(")
            and 180 < len(subtree_text(p["id"])) < 1500
            and re.search(r"\d+ (?:days|months|years)|\d+%|Rs\.", subtree_text(p["id"]))]
    rng.shuffle(pool)
    out = []
    for p in pool:
        if len(out) >= n:
            break
        text = subtree_text(p["id"])
        res = _llm_json(llm, LOOKUP_PROMPT.format(where=cite(p["id"]), text=text))
        if not res or not res.get("question"):
            continue
        facts = [f for f in res.get("facts", []) if isinstance(f, str) and contains(text, f)]
        if not facts:
            continue
        out.append(candidate("lookup", p["id"], res["question"], res.get("answer", ""),
                             facts[:3], [p["id"]], source="llm:" + llm.model,
                             note="numeric fact (LLM-drafted)"))
    return out


def llm_multihop(n: int, rng: random.Random, llm) -> list[dict]:
    a = artefacts()
    prov, rows = a["provisions"], a["rows"]

    def section(pid: str) -> str:
        return re.match(r"^(s\d+|sch:[IVX]+)", pid).group(1) if re.match(
            r"^(s\d+|sch:[IVX]+)", pid) else pid

    pairs = []
    for x in a["xrefs"]:
        src, dst = x["from_id"], x["to_id"]
        if x["resolution"] != "exact" or not dst or src not in prov:
            continue
        if section(src) == section(dst):
            continue  # same-section references are too easy
        dst_text = subtree_text(dst)
        src_text = subtree_text(src)
        if not (80 < len(dst_text) < 1600 and 60 < len(src_text) < 1500):
            continue
        if dst in rows or prov.get(dst, {}).get("kind") not in ("section", "paragraph", None):
            pairs.append((src, dst, src_text, dst_text))
    rng.shuffle(pairs)
    out, used = [], set()
    for src, dst, src_text, dst_text in pairs:
        if len(out) >= n:
            break
        if dst in used or src in used:
            continue
        res = _llm_json(llm, MULTIHOP_PROMPT.format(a_where=cite(src), a_text=src_text,
                                                    b_where=cite(dst), b_text=dst_text))
        if not res or not res.get("question"):
            continue
        facts = [f for f in res.get("facts", []) if isinstance(f, str) and contains(dst_text, f)]
        if not facts:
            continue
        used.update((src, dst))
        gold_rows = [dst] if dst in rows else []
        gold_prov = [src] + ([] if gold_rows else [dst])
        out.append(candidate("multi_hop", f"{src}->{dst}", res["question"],
                             res.get("answer", ""), facts[:3], gold_prov, rows=gold_rows,
                             source="llm:" + llm.model, note=f"{cite(src)} -> {cite(dst)}"))
    return out


TARGETS = {"lookup_def": 32, "lookup_llm": 22, "table": 45, "amendment": 48, "multi_hop": 45}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="also draft lookup/multi-hop with Groq")
    args = ap.parse_args()
    rng = random.Random(SEED)
    existing = {c["id"]: c for c in read_jsonl(CANDIDATES)}
    new = (lookup_definitions(TARGETS["lookup_def"], rng)
           + table_questions(TARGETS["table"], rng)
           + amendment_questions(TARGETS["amendment"], rng)
           + refusal_questions())
    if args.llm:
        from statnav.llm.client import ChatClient

        llm = ChatClient.for_role("classify")  # gpt-oss-20b: keeps the answer model's quota
        new += llm_lookups(TARGETS["lookup_llm"], rng, llm)
        new += llm_multihop(TARGETS["multi_hop"], rng, llm)
    added = 0
    for c in new:
        if c["id"] not in existing:  # never overwrite reviewed candidates
            existing[c["id"]] = c
            added += 1
    write_jsonl(CANDIDATES, list(existing.values()))
    by_type: dict[str, int] = {}
    for c in existing.values():
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    print(f"added {added}; candidates by type: {by_type} -> {CANDIDATES}")


if __name__ == "__main__":
    main()
