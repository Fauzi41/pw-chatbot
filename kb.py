"""Knowledge base: chunking + pure-stdlib TF-IDF retrieval over scraped pages."""
import json
import math
import re
from collections import Counter

DATA_PATH = "data/pages.json"
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "will", "with", "the", "you", "your", "we", "our", "not", "no", "if",
    "but", "so", "can", "do", "does", "did", "about", "what", "how", "much", "many",
}

MIN_SCORE = 0.05  # below this, retrieval is treated as "not found"
PRICE_RE = re.compile(r"[$€£]\s?\d")
PRICE_BOOST = 3.0  # added when a cost question hits a chunk containing a price
PRICE_INTENT_RE = re.compile(r"(cost|price|pricing|how much|cheap)")


def tokenize(text):
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def load_pages(path=DATA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["pages"]


def split_text(text, target=1000):
    """Chunk by paragraphs, merging to ~target chars; oversized paragraphs are
    split on sentences. Returns list of chunks (no overlap in output; retrieval
    covers overlap via top-k)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paragraphs:
        while len(p) > target:
            # split long paragraph on sentence boundaries, keep prefix
            cut = max(p.rfind(". ", 0, target), p.rfind("! ", 0, target), p.rfind("? ", 0, target), int(target * 0.8))
            piece, p = p[: cut + 1], p[cut + 1 :].strip()
            if piece.strip():
                chunks.append(piece.strip())
        candidate = f"{buf} {p}".strip() if buf else p
        if len(candidate) <= target:
            buf = candidate
        else:
            if len(buf) >= 200:
                chunks.append(buf)
                buf = p if len(p) <= target else ""
            else:
                chunks.append(candidate)
                buf = ""
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if len(c) >= 100]


def build_index(pages):
    """pages: [{'url', 'text', ...}]. Returns {'chunks', 'vectors', 'idf', 'n', 'avgdl'}."""
    chunks = [{"text": c, "url": p["url"]} for p in pages for c in split_text(p["text"])]
    df = Counter()
    docs = []
    lengths = []
    for ch in chunks:
        doc = Counter(tokenize(ch["text"]))
        docs.append(doc)
        lengths.append(sum(doc.values()))
        for t in doc:
            df[t] += 1
    n = len(chunks)
    idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1) for t, d in df.items()}
    avgdl = sum(lengths) / n if n else 1.0
    return {"chunks": chunks, "vectors": docs, "idf": idf, "n": n, "avgdl": avgdl}


K1, B = 1.5, 0.75  # BM25 params


def bm25(qv, doc, idf, avgdl, dl):
    score = 0.0
    for t, qtf in qv.items():
        tf = doc.get(t, 0)
        if tf:
            score += idf.get(t, 0.0) * (tf * (K1 + 1)) / (tf + K1 * (1 - B + B * dl / avgdl)) * qtf
    return score


def retrieve(query, index, k=4):
    """Return top-k [{url, text, score}] sorted desc, filtered to score >= MIN_SCORE."""
    if not index or index["n"] == 0:
        return []
    qt = Counter(tokenize(query))
    if not qt:
        return []
    scored = [
        (
            bm25(qt, doc, index["idf"], index["avgdl"], sum(doc.values()))
            + (PRICE_BOOST if PRICE_INTENT_RE.search(query) and PRICE_RE.search(ch["text"]) else 0.0),
            ch,
        )
        for doc, ch in zip(index["vectors"], index["chunks"])
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [{"url": ch["url"], "text": ch["text"], "score": round(s, 4)} for s, ch in scored[:k] if s >= MIN_SCORE]
    return out


def load(path=DATA_PATH):
    return build_index(load_pages(path))
