## 2026-10-29: the reply guard replayed on the labelled reply set (CANDIDATE-OUT PR 1; deterministic code, two runs of the same replay, no model call, no lab run, fingerprint unchanged)

The reminder question engine stops reading `natural.candidate`; the code guard `turn_gate.new_request` (one verdict passed as `new=`) tells a reply that starts a request of its own from the answer to the open question. The set is `runtime/tests/reply_guard_lines.jsonl` (sha256 `a4ffa083639859648bc44cd0001c8fb6d85c6398d1a77c33f56c48d0ae09325b`, 1432 pairs, frozen in commit 58c09a5b before any product edit), labelled by a blind labeller who saw only the question sentence and the line, with the old outcome of `natural.complete` recorded on 83c06da3.

### Two measurements, side by side

**1. The raw first measurement: B1 NOT MET.** 3 of 298 test pairs with gold `answer` and an old `answer`/`retry` became a new request. B2 met (35 against the old engine's 50 of 461). Agreement: 1296 of 1379 (0.94, Wilson 95% [0.926, 0.951]) on every labelled pair; 787 of 843 (0.934, Wilson 95% [0.915, 0.948]) on the test split. The three pairs, all answers to the kind question:
- en / kind: "a reminder is fine" (gold answer, old retry)
- pt-BR / kind: "um lembrete mesmo" (gold answer, old retry)
- pt-BR / kind: "só lembrete" (gold answer, old retry)

Cause: the kind question exempts the verdict in `natural.complete`, but a reply the engine does not recognise goes on to `_retry` and `short_answer`, which read the verdict, and step (d) of the guard (a reminder noun in a line of at most 6 words) says `form`, so the line was dropped as a new request where the old engine, whose `candidate` named nothing, asked once more.

**2. The fixed measurement: B1 MET.** The one change: for the kind need, `_retry` ignores the verdict `form` (runtime/natural.py). 0 of 298 test pairs violate B1. B2 met (35 against the old engine's 50 of 461). Agreement: 1299 of 1379 (0.942, Wilson 95% [0.928, 0.953]) on every labelled pair; 790 of 843 (0.937, Wilson 95% [0.919, 0.952]) on the test split.

**The fix was guided by the test split, and the test split is therefore spent for any later claim.** The three pairs were found on test rows (the dev split had none), the maintainer ruled on 2026-10-29 to fix and publish both, and the fix was made after seeing them. The fixed run's B1 = 0 shows that the change repairs those three pairs and breaks no other pair of the set; it is not an unbiased estimate of the guard's rate on new lines, and no later claim may use these test rows as held out. A new set is needed for one.

**B2 pairs the fixed engine takes as an answer (gold `new`), test split:**
- en / text: "mark emails 1 to 3" (old answer, new answer)
- en / text: "pause the weekly routine" (old answer, new answer)
- en / text: "save attachment 4" (old answer, new answer)
- en / text: "approved" (old answer, new answer)
- en / text: "store this in the file ideas.md" (old answer, new answer)
- en / text: "what are my appointments on friday?" (old answer, new answer)
- en / text: "append this to the file diary.md" (old answer, new answer)
- en / text: "pause the daily digest" (old answer, new answer)
- en / text: "store this document" (old answer, new answer)
- en / text: "do I have a meeting today?" (old answer, new answer)
- en / text: "mark emails 3 via outlook" (old answer, new answer)
- en / text: "deny 4" (old answer, new answer)
- en / text: "archive emails inbox#2 via outlook" (old answer, new answer)
- en / text: "i approve 1" (old answer, new answer)
- pt-BR / text: "salva essa nota como ata-reuniao.md" (old answer, new answer)
- pt-BR / text: "move os e-mails do banco para a pasta contas" (old answer, new answer)
- pt-BR / text: "lê meus emails novos" (old answer, new answer)
- pt-BR / text: "marca como lido o email do banco" (old answer, new answer)
- pt-BR / text: "nega o 3" (old answer, new answer)
- pt-BR / text: "aprovo o 1" (old answer, new answer)
- pt-BR / text: "cria um arquivo notas.txt com a lista de compras" (old answer, new answer)
- pt-BR / text: "substitui o conteúdo de plano.md pelo rascunho" (old answer, new answer)
- pt-BR / text: "salva uma nota chamada ideias.txt dizendo rascunho da lista de convidados" (old answer, new answer)
- pt-BR / text: "aprova tudo" (old answer, new answer)
- pt-BR / text: "rascunha um e-mail pelo gmail pra Bia dizendo que chego às 9" (old answer, new answer)
- pt-BR / text: "pausa a rotina semanal" (old answer, new answer)
- pt-BR / text: "move os e-mails sobre a viagem para a pasta viagens" (old answer, new answer)
- pt-BR / text: "quais são meus compromissos de sexta?" (old answer, new answer)
- pt-BR / text: "recusa o card 4" (old answer, new answer)
- pt-BR / text: "responde o e-mail da Bia sobre a fatura pelo outlook" (old answer, new answer)
- pt-BR / text: "tenho reunião hoje?" (old answer, new answer)
- pt-BR / text: "guarda esse documento" (old answer, new answer)
- pt-BR / text: "para tudo" (old answer, new answer)
- pt-BR / text: "estou livre quinta à tarde?" (old answer, new answer)
- pt-BR / text: "pausa o resumo diário" (old answer, new answer)

**Gold `new` pairs asked once more by the fixed engine (old count: 65):**
- en / confirm: "deny 4" (old retry, new retry)
- en / confirm: "save attachment 4" (old retry, new retry)
- en / confirm: "store this document" (old retry, new retry)
- en / confirm: "cancel task 3" (old retry, new retry)
- en / confirm: "i approve 1" (old retry, new retry)
- en / confirm: "stop routine 2" (old retry, new retry)
- en / text: "stop routine 2" (old retry, new retry)
- en / text: "cancel task 3" (old retry, new retry)
- en / time: "deny 4" (old retry, new retry)
- en / time: "cancel task 3" (old retry, new retry)
- en / time: "save attachment 4" (old retry, new retry)
- en / time: "i approve 1" (old retry, new retry)
- en / time: "store this document" (old retry, new retry)
- en / time: "approved" (old retry, new retry)
- en / time: "stop routine 2" (old retry, new retry)
- pt-BR / confirm: "aprovo o 1" (old retry, new retry)
- pt-BR / confirm: "para tudo" (old retry, new retry)
- pt-BR / confirm: "guarda esse documento" (old retry, new retry)
- pt-BR / confirm: "aprova tudo" (old retry, new retry)
- pt-BR / confirm: "nega o 3" (old retry, new retry)
- pt-BR / text: "ok aprovado" (old retry, new retry)
- pt-BR / time: "nega o 3" (old retry, new retry)
- pt-BR / time: "29" (old retry, new retry)
- pt-BR / time: "aprova tudo" (old retry, new retry)
- pt-BR / time: "guarda esse documento" (old retry, new retry)
- pt-BR / time: "desfaz" (old new, new retry)
- pt-BR / time: "aprovo o 1" (old retry, new retry)
- pt-BR / time: "ok aprovado" (old retry, new retry)
- pt-BR / time: "para tudo" (old retry, new retry)

**Labeller's rulings on ambiguity (verbatim summary):** a full reminder request that gives the asked slot is an answer (after a confirm question only when it matches the shown reminder); a bare undo ("undo", "desfaz") is unclear; a cancel by name that may be the pending reminder is unclear; "e outro as 20h" and single words such as "reminder" or "agenda" after a question that is not the kind question are unclear; calendar-shaped content after the question of what to remind is new; "/pending" is new. Unclear pairs (53, 30 of them in the test split) are excluded from both bars.

**Provenance (principle 10):** deterministic code, no model and no network; checkable by running `python3 runtime/tests/reply_guard_measure.py --print`, and by `runtime/tests/test_reply_guard.py`, which recomputes the fixed figures (first block) and fails when it differs. The first measurement (second block) was run on the same set before the fix and is kept as published; it is reproduced by reverting the `_retry` change. Engine: `turn_gate.complete_reminder` at the pinned clock 2026-10-18T14:00 America/Sao_Paulo.

The fixed figures (the test compares this block):

```json
{
 "agreement": {
  "all": {
   "n": 1379,
   "rate": 0.942,
   "same": 1299,
   "wilson95": [
    0.928,
    0.953
   ]
  },
  "by_lang": {
   "en": {
    "n": 716,
    "rate": 0.934,
    "same": 669,
    "wilson95": [
     0.914,
     0.95
    ]
   },
   "pt-BR": {
    "n": 663,
    "rate": 0.95,
    "same": 630,
    "wilson95": [
     0.931,
     0.964
    ]
   }
  },
  "by_need": {
   "again": {
    "n": 28,
    "rate": 1.0,
    "same": 28,
    "wilson95": [
     0.879,
     1.0
    ]
   },
   "confirm": {
    "n": 418,
    "rate": 0.945,
    "same": 395,
    "wilson95": [
     0.919,
     0.963
    ]
   },
   "forget": {
    "n": 28,
    "rate": 1.0,
    "same": 28,
    "wilson95": [
     0.879,
     1.0
    ]
   },
   "kind": {
    "n": 50,
    "rate": 1.0,
    "same": 50,
    "wilson95": [
     0.929,
     1.0
    ]
   },
   "reading": {
    "n": 30,
    "rate": 1.0,
    "same": 30,
    "wilson95": [
     0.886,
     1.0
    ]
   },
   "text": {
    "n": 392,
    "rate": 0.916,
    "same": 359,
    "wilson95": [
     0.884,
     0.939
    ]
   },
   "time": {
    "n": 403,
    "rate": 0.94,
    "same": 379,
    "wilson95": [
     0.913,
     0.96
    ]
   },
   "weekday": {
    "n": 30,
    "rate": 1.0,
    "same": 30,
    "wilson95": [
     0.886,
     1.0
    ]
   }
  },
  "test": {
   "n": 843,
   "rate": 0.937,
   "same": 790,
   "wilson95": [
    0.919,
    0.952
   ]
  },
  "transitions": {
   "answer->answer": 429,
   "answer->new": 27,
   "new->new": 709,
   "new->retry": 1,
   "retry->new": 52,
   "retry->retry": 161
  }
 },
 "b1": {
  "ids": [],
  "pairs_at_risk": 298,
  "violations": 0
 },
 "b2": {
  "gold_new_pairs": 461,
  "new_asked_once_more": [
   {
    "id": "rg-1ac2a076",
    "lang": "en",
    "line": "deny 4",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-353e5c9b",
    "lang": "en",
    "line": "save attachment 4",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-6426a674",
    "lang": "en",
    "line": "store this document",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-cb2e52d5",
    "lang": "en",
    "line": "cancel task 3",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-df8e58c9",
    "lang": "en",
    "line": "i approve 1",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-ffa1ebb9",
    "lang": "en",
    "line": "stop routine 2",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-91ef9a48",
    "lang": "en",
    "line": "stop routine 2",
    "need": "text",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-d30f2496",
    "lang": "en",
    "line": "cancel task 3",
    "need": "text",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-4cee108e",
    "lang": "en",
    "line": "deny 4",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-51f24ccb",
    "lang": "en",
    "line": "cancel task 3",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-888c1720",
    "lang": "en",
    "line": "save attachment 4",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-c31caa68",
    "lang": "en",
    "line": "i approve 1",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-c3fb32be",
    "lang": "en",
    "line": "store this document",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-c7b0da2c",
    "lang": "en",
    "line": "approved",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-ca08704c",
    "lang": "en",
    "line": "stop routine 2",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-379f741a",
    "lang": "pt-BR",
    "line": "aprovo o 1",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-5fe0c4af",
    "lang": "pt-BR",
    "line": "para tudo",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-62675c05",
    "lang": "pt-BR",
    "line": "guarda esse documento",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-74ba2f50",
    "lang": "pt-BR",
    "line": "aprova tudo",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-f4193ab2",
    "lang": "pt-BR",
    "line": "nega o 3",
    "need": "confirm",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-0bc9c880",
    "lang": "pt-BR",
    "line": "ok aprovado",
    "need": "text",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-27ad89e5",
    "lang": "pt-BR",
    "line": "nega o 3",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-347c34af",
    "lang": "pt-BR",
    "line": "29",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-5592f211",
    "lang": "pt-BR",
    "line": "aprova tudo",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-8ecbcf0b",
    "lang": "pt-BR",
    "line": "guarda esse documento",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-9d5f9f7e",
    "lang": "pt-BR",
    "line": "desfaz",
    "need": "time",
    "new": "retry",
    "old": "new"
   },
   {
    "id": "rg-ac628014",
    "lang": "pt-BR",
    "line": "aprovo o 1",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-b1b55d15",
    "lang": "pt-BR",
    "line": "ok aprovado",
    "need": "time",
    "new": "retry",
    "old": "retry"
   },
   {
    "id": "rg-eb68982f",
    "lang": "pt-BR",
    "line": "para tudo",
    "need": "time",
    "new": "retry",
    "old": "retry"
   }
  ],
  "new_listed": [
   {
    "id": "rg-04d6edcb",
    "lang": "en",
    "line": "mark emails 1 to 3",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-054eef89",
    "lang": "en",
    "line": "pause the weekly routine",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-25cff728",
    "lang": "en",
    "line": "save attachment 4",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-2f838f5f",
    "lang": "en",
    "line": "approved",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-4eea6ac5",
    "lang": "en",
    "line": "store this in the file ideas.md",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-5854ed8f",
    "lang": "en",
    "line": "what are my appointments on friday?",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-69fd4e05",
    "lang": "en",
    "line": "append this to the file diary.md",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-73e25bad",
    "lang": "en",
    "line": "pause the daily digest",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-83cbef3f",
    "lang": "en",
    "line": "store this document",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-e5f32822",
    "lang": "en",
    "line": "do I have a meeting today?",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-e7261f54",
    "lang": "en",
    "line": "mark emails 3 via outlook",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-e8e482ef",
    "lang": "en",
    "line": "deny 4",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-ebedba78",
    "lang": "en",
    "line": "archive emails inbox#2 via outlook",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-f6fb25bb",
    "lang": "en",
    "line": "i approve 1",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-0b939cfe",
    "lang": "pt-BR",
    "line": "salva essa nota como ata-reuniao.md",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-14d1132d",
    "lang": "pt-BR",
    "line": "move os e-mails do banco para a pasta contas",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-1cd2c225",
    "lang": "pt-BR",
    "line": "lê meus emails novos",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-470964cd",
    "lang": "pt-BR",
    "line": "marca como lido o email do banco",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-4a838f83",
    "lang": "pt-BR",
    "line": "nega o 3",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-5b259162",
    "lang": "pt-BR",
    "line": "aprovo o 1",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-62859203",
    "lang": "pt-BR",
    "line": "cria um arquivo notas.txt com a lista de compras",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-66674dd9",
    "lang": "pt-BR",
    "line": "substitui o conteúdo de plano.md pelo rascunho",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-688bd906",
    "lang": "pt-BR",
    "line": "salva uma nota chamada ideias.txt dizendo rascunho da lista de convidados",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-867d0174",
    "lang": "pt-BR",
    "line": "aprova tudo",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-8e28f451",
    "lang": "pt-BR",
    "line": "rascunha um e-mail pelo gmail pra Bia dizendo que chego às 9",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-95f7d93c",
    "lang": "pt-BR",
    "line": "pausa a rotina semanal",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-b25e9919",
    "lang": "pt-BR",
    "line": "move os e-mails sobre a viagem para a pasta viagens",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-b33bd873",
    "lang": "pt-BR",
    "line": "quais são meus compromissos de sexta?",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-bbc64e40",
    "lang": "pt-BR",
    "line": "recusa o card 4",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-c13c5045",
    "lang": "pt-BR",
    "line": "responde o e-mail da Bia sobre a fatura pelo outlook",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-c6d1cd16",
    "lang": "pt-BR",
    "line": "tenho reunião hoje?",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-daab621f",
    "lang": "pt-BR",
    "line": "guarda esse documento",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-f4f609bb",
    "lang": "pt-BR",
    "line": "para tudo",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-fae8506b",
    "lang": "pt-BR",
    "line": "estou livre quinta à tarde?",
    "need": "text",
    "new": "answer",
    "old": "answer"
   },
   {
    "id": "rg-fbd4cdca",
    "lang": "pt-BR",
    "line": "pausa o resumo diário",
    "need": "text",
    "new": "answer",
    "old": "answer"
   }
  ],
  "new_takes_new_as_answer": 35,
  "old_asked_once_more_count": 65,
  "old_takes_new_as_answer": 50,
  "passes": true
 },
 "gold_vs_new_on_test": {
  "answer_kept": 298,
  "answer_total": 382,
  "new_dropped": 397,
  "new_total": 461
 },
 "labelled": {
  "all": 1379,
  "dev": 536,
  "test": 843
 },
 "pairs": 1432,
 "set_sha256": "a4ffa083639859648bc44cd0001c8fb6d85c6398d1a77c33f56c48d0ae09325b",
 "unclear": {
  "all": 53,
  "test": 30
 }
}
```

The first measurement, before the fix (history, not recomputed):

```json
{
 "agreement_all": {
  "n": 1379,
  "rate": 0.94,
  "same": 1296,
  "wilson95": [
   0.926,
   0.951
  ]
 },
 "agreement_test": {
  "n": 843,
  "rate": 0.934,
  "same": 787,
  "wilson95": [
   0.915,
   0.948
  ]
 },
 "b1": {
  "ids": [
   "rg-03e83769",
   "rg-07cdc3d5",
   "rg-327250d3"
  ],
  "pairs_at_risk": 298,
  "violations": 3
 },
 "b2": {
  "gold_new_pairs": 461,
  "new_takes_new_as_answer": 35,
  "old_takes_new_as_answer": 50,
  "passes": true
 },
 "transitions": {
  "answer->answer": 429,
  "answer->new": 27,
  "new->new": 709,
  "new->retry": 1,
  "retry->new": 55,
  "retry->retry": 158
 }
}
```
