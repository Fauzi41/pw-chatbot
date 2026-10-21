# PlacidWay Knowledge Chatbot (AI Automation Assessment)

Grounded Q&A bot over 7 PlacidWay pages (ITC Immunity Therapy Center, Tijuana).
Answers only from ingested content, cites source URLs, says "I don't know" honestly.

Live: https://<domain> (see Deployment)

## Stack & why

- **Python 3.12 + Flask** — single file web layer, JSON chat API, tiny static UI.
- **Retrieval: BM25 (stdlib, hand-rolled)** — pages are small (7 documents, ~100 chunks), so a vector DB / embeddings would add cost and moving parts without better results. BM25 with a price-intent boost reliably surfaces price and package chunks. Pure stdlib `collections`/`math`, no deps.
- **Ingestion: `requests` + `BeautifulSoup`** — respects `Crawl-delay: 10` from `sources.json` (10 s between requests, sleep even on failure), identifies itself with a custom User-Agent, strips nav/footer/script boilerplate, keeps only 7 whitelisted URLs (no crawling beyond them).
- **LLM: pluggable OpenAI-compatible providers** — `LLM_PROVIDER=groq|gemini|openrouter` (free tiers; defaults in `llm.py`), or any custom `LLM_BASE_URL`. If no key is set the bot falls back to deterministic retrieval-only answers, so the app never crashes on a missing LLM.
- **Honesty over coverage** — hard refusal paths in the prompt AND code: no booking, no medical advice, out-of-scope decline, disagree-with-wrong-price rule, "I don't know + free quote" fallback. Unanswered questions logged to `data/unanswered.log`.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
uv pip install -r requirements.txt               # or pip install -r requirements.txt

python ingest.py              # scrape the 7 source URLs -> data/pages.json (~1 min)
python app.py                 # http://localhost:8000
```

LLM (optional, falls back gracefully):

```bash
export LLM_PROVIDER=groq               # or gemini / openrouter
export LLM_API_KEY=your_key
export LLM_MODEL=                      # optional override
```

## API

- `GET /` — chat UI
- `POST /chat` — `{"message": "...", "history": [{role, content}, ...]}` → `{"answer", "sources": [{url, score}]}`
- `GET /health` — `{"ok", "chunks", "llm"}`
- `POST /refresh` — re-scrape + rebuild index, requires `Authorization: Bearer $REFRESH_TOKEN`

## Tests

```bash
pytest tests/ -q              # chunking, retrieval relevance, IDK path, medical refusal
python scripts/run_tests.py   # runs the 8 assessment questions end-to-end -> answers.md
```

## Deployment (GCP VM + Docker)

```bash
docker build -t pw-chatbot .
docker run -d --restart unless-stopped -p 8000:8000 \
  -e LLM_PROVIDER=groq -e LLM_API_KEY=... -e REFRESH_TOKEN=... \
  --name pw-chatbot pw-chatbot
```

Reverse-proxy with nginx/Caddy + TLS in front of port 8000. Knowledge base is baked
at image build time; refresh either by rebuilding the image or `POST /refresh`.

## Project layout

```
app.py          Flask routes, refusals, grounded-answer pipeline
ingest.py       scrape the whitelisted URLs -> data/pages.json
kb.py           BM25 index, chunking, retrieval (+price boost)
llm.py          pluggable OpenAI-compatible LLM client + system prompt
sources.json    source URLs, crawl delay, crawler User-Agent
scripts/run_tests.py   the 8 assessment questions, end to end
tests/test_kb.py       unit tests
static/ templates/     minimal chat UI
```

## Write-up: limitations & next week

Known limitations:
- BM25 is lexical — synonyms/phrasings that share no words with the source (
  "how pricey is it") can miss. Embedding/hybrid retrieval is the upgrade path.
- Package prices float on the page as "starting from $18,995"; the bot repeats
  exact page wording with currency, but no structured price-table extraction.
- Single-process gunicorn (1 worker) — fine for review traffic; scale-out
  needs a shared KV cache or stateless retrieval.

With another week: hybrid BM25+embeddings (e.g. `all-MiniLM` local model, still
free), a price-extraction sanity test in CI comparing page prices against the
last ingest, streaming answers, and a small SQLite store for the unanswered-questions
log with a review UI for finding content gaps.

## Honesty policy (enforced)

- Never invent prices, clinics, or facts. No context → "I don't have that on
  the source pages" + free-quote link.
- Never agree with a wrong price asserted by the user; restate the listed one.
- No booking, no diagnosis/medical advice; point to PlacidWay contact instead.
