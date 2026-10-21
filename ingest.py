"""Scrape PlacidWay pages into data/pages.json. Obey sources.json crawl delay + custom UA."""
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))


def load_sources():
    with open(os.path.join(HERE, "sources.json"), encoding="utf-8") as f:
        return json.load(f)


def clean_html(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "form", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.body or soup
    text = main.get_text(separator="\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_all(sources, delay_s):
    pages, failed = [], []
    for i, url in enumerate(sources["urls"]):
        if i > 0:
            time.sleep(delay_s)  # robots.txt: Crawl-delay: 10
        try:
            r = requests.get(
                url,
                headers={"User-Agent": sources["user_agent"], "Accept": "text/html,application/xhtml+xml"},
                timeout=(15, 60),
            )
            r.raise_for_status()
            text = clean_html(r.text)
            pages.append({"url": url, "title": (BeautifulSoup(r.text, "html.parser").title.string if BeautifulSoup(r.text, "html.parser").title else "").strip(), "text": text})
            print(f"OK  [{len(text):6d} chars] {url}", flush=True)
        except Exception as e:
            failed.append({"url": url, "error": str(e)})
            print(f"FAIL {url}: {e}", flush=True)
    return pages, failed


def main():
    sources = load_sources()
    pages, failed = fetch_all(sources, sources.get("crawl_delay_s", 10))
    out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source_urls": sources["urls"], "pages": pages, "failed": failed}
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    path = os.path.join(HERE, "data", "pages.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n{sys.executable}: wrote {len(pages)} pages, {len(failed)} failed -> {path}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
