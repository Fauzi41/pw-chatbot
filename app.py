"""Flask chat UI + JSON API for the PlacidWay knowledge chatbot."""
import json
import hmac
import os
import re
import threading
import time
from collections import OrderedDict

from flask import Flask, jsonify, redirect, render_template, request

import db
import kb
import llm

app = Flask(__name__)

QUOTE_URL = "https://www.placidway.com/profile/5/Alternative-Cancer-Treatment-by-ITC-Immunity-Therapy-Center"
BOOKING_WORDS = ("book", "booking", "appointment", "schedule", "reserve", "reservation")
MEDICAL_WORDS = ("safe for", "diabetes", "diagnos", "should i take", "is it safe", "recommend for me", "my condition")
DISCLAIMER_RE = re.compile(
    r"^\s*disclaimer\b|medical disclaimer|not medical advice|can't provide medical advice"
    r"|saran medis|nasihat medis|consejo m[ée]dico|avis m[ée]dical|medizinische beratung",
    re.I,
)

HISTORY_LIMIT = 6  # keep last ~6 turns for follow-ups
CACHE_MAX = 256  # question -> answer LRU; cleared on /refresh
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
_cache = OrderedDict()
kb.index = None  # set on startup / /refresh


def cached_key(question, history):
    """Same question + same preceding user turn = same context -> same answer.
    Normalized: case, whitespace, trailing punctuation ignored."""
    norm = lambda s: re.sub(r"[?!.]+$", "", re.sub(r"\s+", " ", (s or "")).strip()).lower()
    last = ""
    if history:
        for m in reversed(history):
            if m.get("role") == "user":
                last = norm(m.get("content"))
                break
    return (norm(question), last)


def clear_cache():
    _cache.clear()


def split_disclaimer(text):
    """Pull a trailing disclaimer line out so the UI can style it apart from the answer."""
    lines = text.rstrip().split("\n")
    if lines and DISCLAIMER_RE.search(lines[-1]):
        disc = re.sub(r"[*_]", "", lines[-1]).strip()
        disc = re.sub(r"^\s*disclaimer\s*:?\s*", "Note: ", disc, flags=re.I)
        disc = re.sub(r"^\s*medical\s+disclaimer\s*:?\s*", "Note: ", disc, flags=re.I)
        return "\n".join(lines[:-1]).strip(), disc
    return text, None


def refusal_for(message):
    m = message.lower()
    if any(w in m for w in BOOKING_WORDS) and any(w in m for w in ("can", "could", "please", "me", "tomorrow", "today")) or ("book me" in m):
        return (
            "I can't book appointments for you — I'm a knowledge assistant only. "
            f"To book or schedule, use the PlacidWay contact / free-quote form: {QUOTE_URL}"
        )
    if any(w in m for w in MEDICAL_WORDS):
        return (
            "I can't give medical advice or assess whether a treatment is safe for "
            "your condition — that requires a doctor's evaluation. Please consult a "
            "qualified physician with your medical history."
        )
    return None


def log_unanswered(question):
    try:
        os.makedirs("data", exist_ok=True)
        with open("data/unanswered.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{question.replace(chr(10), ' ')}\n")
    except OSError:
        pass


def sig_of(chunks):
    """Retrieval signature: same top chunks (any order) -> same grounded answer."""
    return tuple(sorted((c["url"], hash(c["text"])) for c in chunks))


def build_answer(question, history=None):
    """Full grounded pipeline. Returns (answer_text, disclaimer_or_None, sources).
    Same retrieved context + same previous user turn served from cache (no LLM call)."""
    if not kb.index:
        kb.index = kb.load()
    ref = refusal_for(question)
    if ref:
        return ref, None, []
    chunks = kb.retrieve(question, kb.index)
    if not chunks and history:  # follow-up: retry with up to 3 previous user turns
        prevs = [m["content"] for m in history if m["role"] == "user"][-3:]
        if prevs:
            chunks = kb.retrieve(" ".join(prevs + [question]), kb.index)
    key = (sig_of(chunks), cached_key(question, history)[1])
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    result = _answer(question, history, chunks)
    _cache[key] = result
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return result


def _answer(question, history, chunks):
    if not chunks:
        log_unanswered(question)
        return (
            "I don't have information about that in the PlacidWay source pages I can access — "
            "I'd rather not guess. For a free quote: "
            f"contact PlacidWay at {QUOTE_URL}"
        ), None, []
    ans = llm.chat(question, history or [], chunks)
    if ans is None:  # LLM unavailable -> deterministic retrieval-only answer
        bullets = "\n".join(f"- {c['text'][:600]}\n  Source: {c['url']}" for c in chunks)
        ans = (
            "Based on the retrieved PlacidWay pages:\n"
            f"{bullets}\n\n"
            f"Note: I'm answering from retrieved text only (LLM not configured/available). "
            f"Confirm details on the page or via a free quote: {QUOTE_URL}"
        )
        return ans, None, chunks
    ans, disc = split_disclaimer(ans)
    return ans, disc, chunks


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "chunks": (len(kb.index["chunks"]) if kb.index else 0), "llm": llm.available()})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400
    history = (data.get("history") or [])[-HISTORY_LIMIT:]
    session = (data.get("session") or "anon")[:64]
    t0 = time.time()
    answer, disclaimer, chunks = build_answer(message, history)
    ms = int((time.time() - t0) * 1000)
    src = [{"url": c["url"], "score": c["score"]} for c in chunks]
    unanswered = not chunks and not refusal_for(message)
    if db.available():
        try:
            db.save_message(session, message, answer, src, disclaimer, ms, unanswered)
        except Exception as e:
            print("[db] save_message failed:", e, flush=True)
    return jsonify({"answer": answer, "disclaimer": disclaimer, "sources": src, "ms": ms})


@app.route("/refresh", methods=["POST"])
def refresh():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    expected = os.environ.get("REFRESH_TOKEN", "")
    if not expected or token != expected:
        return jsonify({"error": "forbidden"}), 403
    import ingest

    rc = ingest.main()
    kb.index = kb.load()
    clear_cache()
    return jsonify({"ok": rc == 0, "chunks": len(kb.index["chunks"])})


# ---------------- admin ----------------

def admin_ok():
    tok = request.cookies.get("admin_token", "")
    return bool(ADMIN_TOKEN) and hmac.compare_digest(tok, ADMIN_TOKEN)


@app.route("/admin")
def admin():
    if not admin_ok():
        return render_template("admin.html", view="login", error=request.args.get("e"))
    if not db.available():
        return render_template("admin.html", view="login", error="DATABASE_URL not configured")
    totals, days = db.totals()
    return render_template(
        "admin.html",
        view="dashboard",
        totals=totals,
        days=days,
        sources=db.list_sources(),
        messages=db.recent_messages(60),
        unanswered=db.unanswered_messages(60),
        chunks=len(kb.index["chunks"]) if kb.index else 0,
        msg=request.args.get("m"),
    )


@app.route("/admin/login", methods=["POST"])
def admin_login():
    if hmac.compare_digest(request.form.get("token", ""), ADMIN_TOKEN or "\x00"):
        resp = redirect("/admin")
        resp.set_cookie("admin_token", ADMIN_TOKEN, httponly=True, samesite="Lax")
        return resp
    return redirect("/admin?e=Wrong+token")


@app.route("/admin/logout")
def admin_logout():
    resp = redirect("/admin")
    resp.delete_cookie("admin_token")
    return resp


@app.route("/admin/sources", methods=["POST"])
def admin_add_source():
    if not admin_ok() or not db.available():
        return redirect("/admin")
    import ingest

    url = (request.form.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return redirect("/admin?m=Invalid+URL")
    try:
        srcs = ingest.load_sources()
        url, title, text = ingest.fetch_one(url, srcs["user_agent"])
        db.upsert_source(url, title, text)
        kb.index = kb.load()
        clear_cache()
        return redirect(f"/admin?m=Added+{len(text)}+chars")
    except Exception as e:
        return redirect(f"/admin?m=Fetch+failed:+{str(e)[:80]}")


@app.route("/admin/sources/<int:source_id>/toggle", methods=["POST"])
def admin_toggle_source(source_id):
    if not admin_ok() or not db.available():
        return redirect("/admin")
    db.set_source_active(source_id, request.form.get("active") == "1")
    kb.index = kb.load()
    clear_cache()
    return redirect("/admin?m=Source+updated")


@app.route("/admin/refresh", methods=["POST"])
def admin_refresh():
    if not admin_ok() or not db.available():
        return redirect("/admin")
    import ingest

    ingest.main()
    kb.index = kb.load()
    clear_cache()
    return redirect(f"/admin?m=Refreshed+{len(kb.index['chunks'])}+chunks")


def _initial_ingest():
    import ingest

    ingest.main()
    kb.index = kb.load()
    clear_cache()


def _bootstrap():
    """Create tables; seed source URLs from sources.json; fetch content once in background."""
    db.init()
    if not db.available():
        return
    try:
        if not db.list_sources():
            import ingest

            db.seed_from_file(ingest.load_sources())
            threading.Thread(target=_initial_ingest, daemon=True).start()
    except Exception as e:
        print("[db] bootstrap:", e, flush=True)


_bootstrap()

if __name__ == "__main__":
    kb.index = kb.load()
    app.run(host="0.0.0.0", port=8000, debug=False)
