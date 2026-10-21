"""Neon/PostgreSQL storage: sources + chat messages. No ORM, psycopg3 only."""
import json
import os

import psycopg
from psycopg.rows import dict_row

DDL = """
CREATE TABLE IF NOT EXISTS sources (
  id serial PRIMARY KEY,
  url text UNIQUE NOT NULL,
  title text DEFAULT '',
  content text DEFAULT '',
  page_type text DEFAULT '',
  active boolean DEFAULT true,
  added_at timestamptz DEFAULT now(),
  last_scraped_at timestamptz
);
CREATE TABLE IF NOT EXISTS messages (
  id bigserial PRIMARY KEY,
  session varchar(64) NOT NULL,
  question text NOT NULL,
  answer text,
  sources jsonb,
  disclaimer text,
  ms int,
  unanswered boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_unanswered ON messages(unanswered);
"""


def available():
    return bool(os.environ.get("DATABASE_URL"))


def get_conn():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)


def init():
    if not available():
        print("[db] DATABASE_URL not set — file fallback mode", flush=True)
        return
    with get_conn() as conn:
        conn.execute(DDL)
    print("[db] schema ready", flush=True)


# ---- sources ----

def list_sources():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, url, title, page_type, active, added_at, last_scraped_at, "
            "length(content) AS chars FROM sources ORDER BY id"
        ).fetchall()


def get_pages():
    with get_conn() as conn:
        rows = conn.execute("SELECT url, title, content AS text FROM sources WHERE active").fetchall()
    return rows


def upsert_source(url, title, text):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sources (url, title, content, last_scraped_at)
               VALUES (%s, %s, %s, now())
               ON CONFLICT (url) DO UPDATE
               SET title = EXCLUDED.title, content = EXCLUDED.content,
                   last_scraped_at = now(), active = true""",
            (url, title, text),
        )


def set_source_active(source_id, active):
    with get_conn() as conn:
        conn.execute("UPDATE sources SET active = %s WHERE id = %s", (active, source_id))


def seed_from_file(sources):
    """Insert sources.json entries that are not in the table yet (no content)."""
    with get_conn() as conn:
        for url in sources["urls"]:
            conn.execute(
                "INSERT INTO sources (url, page_type) VALUES (%s, 'seed') ON CONFLICT (url) DO NOTHING",
                (url,),
            )


# ---- messages ----

def save_message(session, question, answer, sources, disclaimer, ms, unanswered):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO messages (session, question, answer, sources, disclaimer, ms, unanswered)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (session, question, answer, json.dumps(sources), disclaimer, ms, unanswered),
        )


def all_sources():
    with get_conn() as conn:
        return conn.execute("SELECT id, url FROM sources WHERE active").fetchall()


def recent_messages(limit=100):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM messages ORDER BY created_at DESC, id DESC LIMIT %s", (limit,)
        ).fetchall()


def unanswered_messages(limit=100):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM messages WHERE unanswered ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        ).fetchall()


def totals():
    with get_conn() as conn:
        row = conn.execute(
            """SELECT count(*) AS total,
                      coalesce(avg(ms), 0)::int AS avg_ms,
                      count(*) FILTER (WHERE unanswered) AS unanswered,
                      count(*) FILTER (WHERE created_at::date = current_date) AS today
               FROM messages"""
        ).fetchone()
        days = conn.execute(
            """SELECT created_at::date AS d, count(*) AS n FROM messages
               WHERE created_at > now() - interval '7 days'
               GROUP BY 1 ORDER BY 1"""
        ).fetchall()
    return row, days
