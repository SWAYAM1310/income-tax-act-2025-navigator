-- Statute navigator schema. Idempotent: safe to run on every load.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS provisions (
    id          TEXT PRIMARY KEY,          -- "s2(5)(b)", "sch:III:tbl1", "ch:XIX:C"
    kind        TEXT NOT NULL,             -- section | sub-section | clause | ... | table
    number      TEXT NOT NULL,             -- citation path, e.g. "2(5)(b)"
    label       TEXT,
    heading     TEXT,
    text        TEXT NOT NULL,             -- own text only (children are separate rows)
    parent_id   TEXT,
    chapter     TEXT,
    part        TEXT,
    schedule    TEXT,
    page_start  INTEGER NOT NULL,
    page_end    INTEGER NOT NULL,
    is_amended  BOOLEAN NOT NULL DEFAULT FALSE,
    ord         INTEGER NOT NULL           -- document order
);
CREATE INDEX IF NOT EXISTS provisions_parent ON provisions (parent_id);
-- `text` with each amended bracket tagged by its endnote: "{{fn:11}}[sub-section (1)(a)(ii) or (b)]".
-- Only set for amended provisions; drives the before/after view (repo.before_after).
ALTER TABLE provisions ADD COLUMN IF NOT EXISTS text_marked TEXT;

CREATE TABLE IF NOT EXISTS tables (
    table_id    TEXT PRIMARY KEY,          -- provision id of the table node, "s393:tbl1"
    title       TEXT,
    headers     JSONB NOT NULL,
    notes       JSONB NOT NULL,
    page_start  INTEGER NOT NULL,
    page_end    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS table_rows (
    row_id      TEXT PRIMARY KEY,          -- "s393:tbl1#1(i)"
    table_id    TEXT NOT NULL REFERENCES tables (table_id),
    sl_no       TEXT NOT NULL,
    subrow      TEXT,
    row_heading TEXT,
    cells       JSONB NOT NULL,            -- {column heading: cell text}
    rate        TEXT,
    threshold   TEXT,
    page_start  INTEGER NOT NULL,
    page_end    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS table_rows_table ON table_rows (table_id, sl_no);

CREATE TABLE IF NOT EXISTS amendments (
    key            TEXT PRIMARY KEY,       -- "<label>@<line index>"
    label          TEXT NOT NULL,
    type           TEXT NOT NULL,          -- substituted | inserted | omitted | renumbered
    amending_act   TEXT,
    effective_date TEXT,
    header         TEXT NOT NULL,
    prior_text     TEXT,
    target_desc    TEXT,
    page           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS amendment_links (
    key          TEXT NOT NULL REFERENCES amendments (key),
    provision_id TEXT NOT NULL,            -- a provision id or a table id
    PRIMARY KEY (key, provision_id)
);

CREATE TABLE IF NOT EXISTS cross_refs (
    from_id    TEXT NOT NULL,
    raw        TEXT NOT NULL,
    ref_type   TEXT NOT NULL,
    to_id      TEXT,                       -- NULL when unresolved or external
    resolution TEXT NOT NULL               -- exact | inferred | partial | unresolved | external
);
CREATE INDEX IF NOT EXISTS cross_refs_from ON cross_refs (from_id);
CREATE INDEX IF NOT EXISTS cross_refs_to ON cross_refs (to_id);

-- Retrieval units. One row per (version, chunk); each ladder version has its own chunking.
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,          -- "<version>:<n>"
    version     TEXT NOT NULL,
    provision_id TEXT,                     -- anchor provision (v2+); NULL for page windows
    text        TEXT NOT NULL,             -- what the LLM sees
    embed_text  TEXT NOT NULL,             -- what was embedded (may carry a breadcrumb)
    tokens      INTEGER NOT NULL,
    page_start  INTEGER NOT NULL,
    page_end    INTEGER NOT NULL,
    meta        JSONB NOT NULL,            -- {"provisions": [...covered ids...], ...}
    model       TEXT NOT NULL,             -- embedding model that produced `embedding`
    embedding   vector(1024) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_version ON chunks (version);
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (tsv);
