import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kb
from llm import chat  # noqa: F401
import app


PAGES = [
    {
        "url": "https://www.placidway.com/package/7903/Adenocarcinoma",
        "text": "The alternative adenocarcinoma cancer treatment package in Tijuana, Mexico. "
        "It is a 7 day program. The package cost starts from US $14,500 and includes accommodation, "
        "consultation, and the treatment protocol. The package includes 21 sessions of immunotherapy. "
        "Patients stay at the clinic for the duration. Transportation from San Diego airport is included."
        " The next paragraph describes followup care after the program ends. The clinic nurse keeps track of recovery."
        " Conclusion of the package description page and contact details for a free quote.",
    },
    {
        "url": "https://www.placidway.com/price-list/5/PriceList",
        "text": "Price list for alternative medicine procedures at ITC Immunity Therapy Center in Tijuana, Mexico. "
        "The price of cancer treatment packages is considerably cheaper than comparable treatment in the USA. "
        "The price list shows costs in US dollars for many procedures. Departments include dentistry and wellness too.",
    },
    {
        "url": "https://www.placidway.com/package/7902/Adrenal",
        "text": "The alternative adrenal cancer treatment package in Tijuana, Mexico. "
        "A 14 day program. The package includes laboratory studies, medication, and hotel accommodation. "
        "The treatment is administered by specialists at ITC Immunity Therapy Center.",
    },
]


def test_chunking_coverage_and_size():
    pages = kb.build_index(PAGES)
    texts = [c["text"] for c in pages["chunks"]]
    assert len(texts) >= 3
    assert all(len(t) <= 1250 for t in texts), "chunk too long"
    joined = " ".join(texts)
    assert "adenocarcinoma" in joined and "adrenal" in joined, "content lost in chunking"


def test_retrieval_topk_relevance():
    pages = kb.build_index(PAGES)
    res = kb.retrieve("how much does adenocarcinoma treatment cost", pages, k=3)
    assert res, "no chunks retrieved"
    assert res[0]["url"] == "https://www.placidway.com/package/7903/Adenocarcinoma", "wrong top hit"
    assert res[0]["score"] >= res[-1]["score"] >= kb.MIN_SCORE


def test_not_in_content_path_with_llm_mocked(monkeypatch):
    def fake_chat(*a, **kw):
        return None  # simulate LLM unavailable -> retrieval-only path

    monkeypatch.setattr(app.llm, "chat", fake_chat)
    pages = kb.build_index([{"url": "https://x", "text": "the weather in cancun is described nowhere here"}])
    kb.index = pages
    ans, disc, sources = app.build_answer("what is the weather in cancun")
    assert sources == []
    assert "don't have information" in ans and "free quote" in ans


def test_medical_refusal():
    kb.index = kb.build_index(PAGES)
    ans, disc, sources = app.build_answer("is this surgery safe for my diabetes")
    assert "doctor" in ans and sources == []


def test_cache_serves_identical_question_once(monkeypatch):
    app.clear_cache()
    calls = []

    def fake_chat(*a, **kw):
        calls.append(1)
        return "grounded answer"

    monkeypatch.setattr(app.llm, "chat", fake_chat)
    kb.index = kb.build_index(PAGES)
    r1 = app.build_answer("how much does adenocarcinoma treatment cost")
    r2 = app.build_answer("How much does adenocarcinoma treatment cost?")
    assert r1 == r2 and len(calls) == 1


def test_cache_serves_paraphrase_once(monkeypatch):
    app.clear_cache()
    calls = []

    def fake_chat(*a, **kw):
        calls.append(1)
        return "grounded answer"

    monkeypatch.setattr(app.llm, "chat", fake_chat)
    kb.index = kb.build_index(PAGES)
    r1 = app.build_answer("how much cost treatment for adenocarcinoma in tijuana")
    r2 = app.build_answer("cost of adenocarcinoma treatment tijuana")
    assert r1 == r2 and len(calls) == 1
