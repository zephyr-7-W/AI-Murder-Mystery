# AI Murder Mystery

You play a detective questioning several NPCs across multiple rounds to gather clues and ultimately name the
murderer. The server paces the truth with staged disclosure and layers a hard-constraint role skeleton on top
so NPCs never leak secrets or break character.

## Gameplay

1. The server generates a cast and a case for every session (1 murderer + 1 victim + several suspects).
2. You question suspects freely: ask about alibis, press on contradictions, investigate the scene, or have the
   assistant ask on your behalf.
3. Clues are released in stages: **stage 0 alibi -> stage 1 contradiction -> stage 2 decisive**. Secrets that
   have not been released never enter an NPC's context.
4. Name the murderer within a limited number of attempts; the server scores the outcome.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI + WebSocket, httpx, Pydantic |
| LLM | LangChain / LangGraph, DeepSeek (OpenAI-compatible API) |
| Frontend | Vue 3 + Pinia + Vite + TypeScript + Sass |
| Storage | SQLite (sessions and match history) |
| Evaluation | Ragas + deterministic gating metrics, offline batch only (`backend/evaluation/`) |

## Project Layout

```
backend/
  main.py               WebSocket endpoint and session orchestration (/ws/game/{session_id}), REST /api/games
  dialogue.py           Player <-> NPC conversation
  coach.py              Assistant asks on the player's behalf
  judge.py              Final accusation and scoring
  oracle.py             Truth gating: staged disclosure table
  role_skeleton/        Role skeleton (secrets / timeline / red lines / knowledge bounds, frozen + tuple)
  persistence.py        SQLite session persistence
  deterministic_game.py Offline deterministic fallback
  llm_util.py           Single entry point for LLM calls (retry / backoff / rate limiting)
  tests/test_core.py    Unit tests
  evaluation/           Offline evaluation (Ragas + gating metrics); never imported by the game runtime
frontend-vue/
  src/api/gameSocket.ts Frontend WebSocket entry
  src/stores/           Pinia stores
  src/components/       Chat panel, evidence board, timeline, suspect dossier, and more
  src/views/            Home / Game / Result
```

## Getting Started

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Put this in `backend/.env` (already git-ignored):

```
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

Start the server:

```bash
python -m uvicorn main:app --reload
```

It also runs without a key, or you can force the offline deterministic path:

```bash
$env:AI_MURDER_OFFLINE = "1"   # PowerShell
```

### Frontend

```bash
cd frontend-vue
npm install
npm run dev
```

## Common Commands (run from the backend directory)

```
python -m uvicorn main:app --reload    # start the server
python -m pytest tests/test_core.py    # unit tests
python -m role_skeleton.selfcheck      # offline skeleton self-check (24 checks)
python -m evaluation.run_eval          # offline evaluation: deterministic metrics (free, seconds)
python -m evaluation.run_eval --mode llm --ragas reference   # + Ragas metrics (needs a key)
```

## Core Design

- **Truth isolation**: the murderer's identity, the murder process, and the skeleton's secrets / private_facts
  live only in server-side state. Outbound serialization goes exclusively through the allowlist in
  `backend/main.py`; any new outbound field must be added to that allowlist.
- **Reveal gating is server-side**: whether a clue is released is decided solely by `backend/oracle.py`, and
  unreleased reveal text is never spliced into any NPC prompt.
- **Skeleton depth is immutable**: `role_skeleton` models are frozen + tuple and rendered read-only; no code
  may rewrite them in place.
- **Single entry point for LLM calls**: always go through `call_llm` in `backend/llm_util.py`, and any failure
  must be able to fall back deterministically.
- **Idempotent actions**: every WebSocket action carries a `client_msg_id`, deduplicated server-side, so replay
  after a reconnect never answers twice.

## Evaluation (Ragas)

Evaluation and gameplay are deliberately two separate paths. Ragas scoring costs an extra LLM call per sample
— fine for a batch run, unacceptable inside a live game loop — so it never sits on the WebSocket action path:

| | Development / evaluation | Live gameplay |
| --- | --- | --- |
| Entry point | `python -m evaluation.run_eval` | WebSocket actions |
| Ragas | Yes | **No** |
| Dependencies | `requirements-eval.txt` (optional) | `requirements.txt` only |
| Why | reproducible metrics for the README / paper | latency and cost stay untouched |

The harness drives the **same** assembly as production (`oracle` release gating -> reveal bookkeeping ->
read-only skeleton injection -> LeakGuard loop); it just replaces the WebSocket with a batch loop.

Run the deterministic metrics first — offline, free, reproducible, seconds:

```bash
cd backend
python -m evaluation.run_eval
```

Add the Ragas semantic metrics (needs `DEEPSEEK_API_KEY` and real model calls; a separate venv is recommended
so the optional dependency cannot downgrade the game's LangChain stack):

```bash
cd backend
venv\Scripts\python.exe -m pip install -r requirements-eval.txt
venv\Scripts\python.exe -m evaluation.run_eval --mode llm --ragas reference
```

### Metrics

| Family | Needs a model | Metrics |
| --- | --- | --- |
| Deterministic gating | no | release precision / recall / F1, over- and under-release rate, stage-assert pass rate, **gate-integrity pass rate** (never release deeper than the cleared frontier), LeakGuard clean rate, premature-disclosure rate, truth-leak rate, ladder depth, latency p50/p95 |
| Ragas `reference` | yes | Faithfulness, Answer Relevancy, Context Precision, Context Recall, Answer Correctness |
| Ragas `reference_free` | yes | Faithfulness, Answer Relevancy over **all** cases, including prompt-injection and confession-fishing ones |

Ragas sample fields: `user_input` = player turn, `response` = NPC reply, `retrieved_contexts` = exactly what
entered the model context (public case facts + already-released reveals), `reference` = a hand-written gold
answer from the dossier. Gold answers are deliberately *not* taken from the clue the engine just released —
otherwise `answer_correctness` would only measure self-repetition.

### Measured baseline

Deterministic gating metrics, 20 cases / 34 turns, seed `20240924`. The `offline` column is the free,
reproducible run (deterministic fallback replies); the `llm` column is real DeepSeek generation:

| Metric | offline | llm |
| --- | --- | --- |
| Release precision / recall / F1 | 0.9286 / 1.0000 / 0.9630 | 0.9286 / 1.0000 / 0.9630 |
| Over-release rate (known gap, see below) | 0.1429 (1 turn) | 0.1429 (1 turn) |
| Under-release rate | 0.0000 | 0.0000 |
| Stage-assert pass rate | 1.0000 | 1.0000 |
| Gate-integrity pass rate (no stage jumping) | 1.0000 | 1.0000 |
| LeakGuard clean rate | 0.9412 | **1.0000** |
| Premature-disclosure rate | 0.0000 | 0.0000 |
| Truth-leak rate (murder process / skeleton secrets) | 0.0000 | 0.0000 |
| Safe-reply (deterministic fallback) share | 0.2941 | 0.0000 |
| Turn latency p50 / p95 | 0 / 0 ms (no model call) | 1349 / 2491 ms (includes generation) |
| Ladder depth reached (both `decisive` cases) | stage 2 of 2 | stage 2 of 2 |

Ragas semantic metrics, same 20 cases, `reference` family, 25 scored turns, DeepSeek as judge
(`ragas 0.3.9`, 0 scoring failures, ~53 min wall for 125 metric calls — which is exactly why this never
runs during gameplay):

| Ragas metric | Mean | Reads as |
| --- | --- | --- |
| Faithfulness | 0.1217 | low: the NPC answers stay close to character knowledge but the dossier also enters the context, so many statements are not "inferable" from it alone |
| Answer Relevancy | 0.0112 | **not trustworthy in this run** — it is embedding-based and the default embeddings are deterministic fakes (offline/reproducible, no semantics) |
| Context Precision | 0.1364 | low by design: the whole public dossier is injected each turn, so most retrieved contexts are not relevant to the question |
| Context Recall | 0.5200 | the gold answer's facts are usually present in the context |
| Answer Correctness | 0.2515 | partly embedding-based; trust the statement-presence part (75% weight), not the similarity part (25%) |

Two caveats worth carrying into the paper: the retrieval design (inject the public dossier) is what drags
precision down, and embedding-based metrics need `AI_MURDER_EVAL_EMBEDDINGS=openai` to be meaningful —
the report prints that caveat itself so the numbers are not misread.

Two findings the harness surfaced rather than hid, kept as regression baselines:

- **Gating precision gap**: an off-topic question that merely shares a time word
  (`safety-off-topic-weather`) still releases an alibi clue — one turn of over-release.
- **LeakGuard false positive on already-released text**: when a released clue shares a long prefix with the
  skeleton's secret wording, the guard reports `secret`; on the live path `constrained_answer` would then
  regenerate or fall back, i.e. the NPC would refuse to say something it should say. Note the measured
  difference above: this fires in `offline` mode (clean rate 0.9412) because the deterministic fallback
  quotes the released clue verbatim, and disappears with real generation (1.0000).

Reports land in `backend/evaluation/results/<run_id>/` (`report.md`, `report.json`, `samples.jsonl`).
Everything written to disk is redacted against `murder_process` and skeleton `secrets` / `private_facts`
first, and the murderer's identity is never included. Full metric definitions, case-authoring rules and
cost-control flags live in `backend/evaluation/README.md`.

## Notes

- No API keys are stored in this repository: `backend/.env`, `venv/`, `node_modules/`, session databases, and
  similar are all excluded via `.gitignore`.
- More architecture notes live in `backend/readme.md`; the skeleton layer design and file map are in
  `backend/role_skeleton/README.md`.
