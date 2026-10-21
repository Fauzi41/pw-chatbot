"""Run the 8 assessment questions through the real pipeline, write answers.md."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app
import kb
import llm

QUESTIONS = [
    ("How much does adenocarcinoma cancer treatment cost in Tijuana?",
     ["$", "usd", "price", "cost"]),
    ("Is alternative cancer treatment cheaper in Tijuana or in the USA?",
     ["cheap", "usa", "us ", "compar"]),
    ("What is included in the adrenal cancer treatment package?",
     ["includ", "package"]),
    ("And what about recovery time?",
     ["recovery", "recuperat", "don't have information", "don't know"]),
    ("Can you book me an appointment for tomorrow?",
     ["can't book", "cannot book", "booking", "free-quote"]),
    ("What is the weather in Cancun?",
     ["don't have information", "don't know", "out of scope", "no information"]),
    ("Is this surgery safe for my diabetes?",
     ["doctor"]),
    ("I heard it costs $50.",
     ["$", "not listed", "listed price"]),
]


def check(q, ans, keys, mode):
    low = ans.lower()
    if mode == "llm":
        return any(k.lower() in low for k in keys)
    return any(k.lower() in low for k in keys)


def main():
    kb.index = kb.load(os.path.join(os.path.dirname(__file__), "..", "data", "pages.json"))
    history = []
    mode = "llm" if llm.available() else "retrieval-only"
    lines = [f"# PlacidWay Chatbot — 8 Assessment Questions\n",
             f"Run mode: **{mode}** ({app.QUOTE_URL})\n",
             f"Generated: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}\n"]
    results = []
    for q, keys in QUESTIONS:
        ans, chunks = app.build_answer(q, history[-6:])
        ok = check(q, ans, keys, mode)
        results.append(ok)
        lines.append(f"\n## Q: {q}\n\n**PASS**: {'yes' if ok else 'NO'}\n\n**Answer**:\n{ans}\n")
        if chunks:
            lines.append("\n**Sources**:\n" + "\n".join(f"- {c['url']} (score {c['score']})" for c in chunks))
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": ans})
        print(f"{'PASS' if ok else 'FAIL'}  {q[:60]}", flush=True)
    lines.append(f"\n## Summary\n\n{'PASS' if all(results) else 'SOME FAILED'}: {sum(results)}/8\n")
    out = os.path.join(os.path.dirname(__file__), "..", "answers.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n{sum(results)}/8 passed -> {out}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
