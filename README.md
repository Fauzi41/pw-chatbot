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
- `POST /chat` — `{"message", "history", "session"}` → `{"answer", "disclaimer", "sources", "ms"}`; every exchange is stored
- `GET /health` — `{"ok", "chunks", "llm"}`
- `POST /refresh` — re-scrape + rebuild index, requires `Authorization: Bearer $REFRESH_TOKEN`
- `GET /admin` — admin panel (`ADMIN_TOKEN`): analytics, chat history, unanswered log, add source by URL, enable/disable + re-scrape

## Storage (Neon Postgres)

`DATABASE_URL` switches everything to Postgres; without it the bot falls back to
`data/pages.json`. Tables are created on startup (`sources`, `messages`) — the
source list is seeded from `sources.json` and fetched in the background on first
boot. All chat turns (question, answer, sources, disclaimer, latency, unanswered
flag) and the admin log live in `messages`; analytics are SQL aggregates.

## Tests

```bash
pytest tests/ -q              # chunking, retrieval relevance, IDK path, medical refusal
python scripts/run_tests.py   # runs the 8 assessment questions end-to-end -> answers.md
```

## Deployment (GCP VM + Docker)

First-time setup on the VPS: copy `scripts/deploy.sh` (or curl it from the repo
once pushed), then:

```bash
REPO_URL=https://github.com/<you>/pw-chatbot.git bash deploy.sh
```

It clones into `/opt/pw-chatbot`, creates `.env` there (fill `LLM_API_KEY` +
`REFRESH_TOKEN`, rerun), builds the image (KB baked at build time), and runs the
container with `--restart unless-stopped` on port 8000. `data/` is a volume, so
the unanswered log survives redeploys. Optional TLS via Caddy is in the script.

Manual redeploy (same as CI does):

```bash
cd /opt/pw-chatbot && git pull --ff-only
docker build -t pw-chatbot .
docker rm -f pw-chatbot || true
docker run -d --restart unless-stopped --name pw-chatbot \
  --env-file .env -p 8000:8000 -v /opt/pw-chatbot/data:/app/data pw-chatbot
```

## CI/CD (GitHub Actions)

`.github/workflows/deploy.yml`: push to `main` → `pytest` → SSH to the VPS →
pull, rebuild, restart. Setup:

1. On the VPS, authorize the deploy key: add the public key of your Actions
   secret to `~/.ssh/authorized_keys`.
2. Repo → Settings → Secrets and variables → Actions, add:
   - `VPS_HOST` — server IP/domain
   - `VPS_USER` — SSH user (e.g. root)
   - `VPS_SSH_KEY` — private key (OpenSSH format, single line)
3. Push to `main`.

Secrets live on the VPS in `/opt/pw-chatbot/.env` (never in the repo); the
GitHub key is the only CI-side credential.

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
