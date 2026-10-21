import json
import requests

hist = []


def ask(q):
    r = requests.post('http://localhost:8000/chat', json={'message': q, 'history': hist[-6:]}, timeout=120).json()
    hist.append({'role': 'user', 'content': q})
    hist.append({'role': 'assistant', 'content': r['answer']})
    print('Q:', q)
    print('A:', r['answer'][:280].replace('\n', ' '))
    print('SRC:', [s['url'].split('.com/')[-1][:40] for s in r.get('sources', [])] or 'none')
    print()


ask('How much does breast cancer surgery cost in India?')
ask('what about in mexico?')
ask('in Tijuana')
ask('How much does adenocarcinoma cancer treatment cost in Tijuana?')
