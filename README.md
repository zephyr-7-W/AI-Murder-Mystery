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

## Notes

- No API keys are stored in this repository: `backend/.env`, `venv/`, `node_modules/`, session databases, and
  similar are all excluded via `.gitignore`.
- More architecture notes live in `backend/readme.md`; the skeleton layer design and file map are in
  `backend/role_skeleton/README.md`.
