"""LLM client: OpenAI-compatible chat completions via plain requests. No openai package."""
import os

import requests

SYSTEM = """You are a customer-support assistant for a medical-tourism knowledge base covering PlacidWay pages about ITC Immunity Therapy Center (alternative cancer treatment, Tijuana, Mexico).

STRICT RULES:
1. Answer ONLY using the CONTEXT passages supplied below. Every passage is labelled with its source URL. Never invent prices, clinics, treatments, or medical facts.
2. When you use information, cite the source URL(s) at the end of the relevant sentence like this: [source: <full URL>]. Prefer answering with exact wording for prices, keeping currency and context words such as "starting from" or "includes" as written in the source.
3. If the CONTEXT does not contain the answer, say you don't know (in the user's language) and suggest contacting PlacidWay for a free quote (https://www.placidway.com/profile/5/Alternative-Cancer-Treatment-by-ITC-Immunity-Therapy-Center). Never guess. Do NOT attach any [source:] citation to a "not listed / don't know" statement — nothing in the CONTEXT supports it.
4. Out-of-scope questions (not about the clinics/packages/services in the CONTEXT) are politely declined in one sentence.
5. Never give medical advice. For questions about diagnosis, safety for a specific condition, or whether a treatment is right for someone: do NOT give a diagnosis or any guidance on the condition — say you can't give medical advice and recommend they consult a qualified doctor.
6. You cannot book appointments. If asked to book/schedule, say you can't book, and point to the PlacidWay contact/free-quote form at https://www.placidway.com/profile/5/Alternative-Cancer-Treatment-by-ITC-Immunity-Therapy-Center.
7. If the user asserts a price that contradicts the CONTEXT, do NOT agree with them. Restate the listed price from the CONTEXT with its source, or say it is not listed.
8. Detect the user's language and reply ENTIRELY in it — never mix two languages in one sentence. Never produce hybrids like "Untuk obtain a quote"; translate the whole sentence (e.g. Indonesian: "Untuk penawaran gratis, hubungi PlacidWay"). Keep proper nouns (clinic/program names) and prices with currency exactly as written in the source. Keep answers short. Include a one-line medical disclaimer ONLY when the question is health/treatment related, written fluently and grammatically in the same language as the answer.
"""


PROVIDERS = {
    # OpenAI-compatible endpoints; model is the free-tier default (override with LLM_MODEL)
    "groq": {"base": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.0-flash"},
    "openrouter": {
        "base": "https://openrouter.ai/api/v1",
        "model": "minimax/minimax-m3.1-flash:free",
        "headers": {"HTTP-Referer": "https://github.com/Fauzi41/pw-chatbot", "X-Title": "PlacidWay KB Chatbot"},
    },
}


def config():
    provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    p = PROVIDERS.get(provider, {})
    return {
        "base": os.environ.get("LLM_BASE_URL") or p.get("base"),
        "key": os.environ.get("LLM_API_KEY"),
        "model": os.environ.get("LLM_MODEL") or p.get("model"),
        "headers": p.get("headers", {}),
    }


def available():
    c = config()
    return bool(c["base"] and c["key"] and c["model"])


def chat(question, history, chunks, max_attempts=2, timeout=(10, 60)):
    """Returns answer text, or None if unconfigured / all attempts failed.
    Hard-bounded: max_attempts tries, connect timeout 10s, read 60s."""
    c = config()
    if not available():
        return None
    if c["base"]:
        base = c["base"]
        key = c["key"]
        model = c["model"]
    context = "\n\n".join(
        f"PASSAGE {i}:\n{c['text'][:1200]}\n(source: {c['url']})" for i, c in enumerate(chunks, 1)
    )
    hist = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:500]}" for m in history
    ) or "(none)"
    user_msg = (
        f"CONTEXT:\n{context}\n\n"
        f"CONVERSATION HISTORY:\n{hist}\n\n"
        f"QUESTION: {question}\n\n"
        "Answer per the STRICT RULES. If the answer is not in the CONTEXT, say so."
    )
    url = base.rstrip("/") + "/chat/completions"
    last_err = None
    for _ in range(max_attempts):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", **c["headers"]},
                json={"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_msg}], "temperature": 0.2},
                timeout=timeout,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (401, 402, 403):  # auth/quota errors: do not retry
                break
        except requests.RequestException as e:
            last_err = str(e)
    print(f"[llm] unavailable ({last_err}); falling back to retrieval-only", flush=True)
    return None
