"""Flask chat UI + JSON API for the PlacidWay knowledge chatbot."""
import json
import os
import time

from flask import Flask, jsonify, render_template, request

import kb
import llm

app = Flask(__name__)

QUOTE_URL = "https://www.placidway.com/profile/5/Alternative-Cancer-Treatment-by-ITC-Immunity-Therapy-Center"
BOOKING_WORDS = ("book", "booking", "appointment", "schedule", "reserve", "reservation")
MEDICAL_WORDS = ("safe for", "diabetes", "diagnos", "should i take", "is it safe", "recommend for me", "my condition")

HISTORY_LIMIT = 6  # keep last ~6 turns for follow-ups
kb.index = None  # set on startup / /refresh


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


def build_answer(question, history=None):
    """Full grounded pipeline. Returns (answer_text, sources)."""
    if not kb.index:
        kb.index = kb.load()
    ref = refusal_for(question)
    if ref:
        return ref, []
    chunks = kb.retrieve(question, kb.index)
    if not chunks and history:  # follow-up: retry with up to 3 previous user turns
        prevs = [m["content"] for m in history if m["role"] == "user"][-3:]
        if prevs:
            chunks = kb.retrieve(" ".join(prevs + [question]), kb.index)
    if not chunks:
        log_unanswered(question)
        return (
            "I don't have information about that in the PlacidWay source pages I can access — "
            "I'd rather not guess. For a free quote: "
            f"contact PlacidWay at {QUOTE_URL}"
        ), []
    ans = llm.chat(question, history or [], chunks)
    if ans is None:  # LLM unavailable -> deterministic retrieval-only answer
        bullets = "\n".join(f"- {c['text'][:600]}\n  Source: {c['url']}" for c in chunks)
        ans = (
            "Based on the retrieved PlacidWay pages:\n"
            f"{bullets}\n\n"
            f"Note: I'm answering from retrieved text only (LLM not configured/available). "
            f"Confirm details on the page or via a free quote: {QUOTE_URL}"
        )
    else:
        return ans, chunks
    return ans, chunks


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
    answer, chunks = build_answer(message, history)
    return jsonify({"answer": answer, "sources": [{"url": c["url"], "score": c["score"]} for c in chunks]})


@app.route("/refresh", methods=["POST"])
def refresh():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    expected = os.environ.get("REFRESH_TOKEN", "")
    if not expected or token != expected:
        return jsonify({"error": "forbidden"}), 403
    import ingest

    rc = ingest.main()
    kb.index = kb.load()
    return jsonify({"ok": rc == 0, "chunks": len(kb.index["chunks"])})


if __name__ == "__main__":
    kb.index = kb.load()
    app.run(host="0.0.0.0", port=8000, debug=False)
