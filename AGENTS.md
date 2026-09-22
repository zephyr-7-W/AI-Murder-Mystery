# AGENTS.md

## Project
AI murder mystery game: the player talks with NPCs over multiple rounds to collect clues and finally names the
murderer. Backend is FastAPI + WebSocket; frontend is Vue 3 + Pinia.

## Hard constraints (read before changing code)
1. **Truth isolation must never be broken**: the murderer's identity, `murder_process`, and the `secrets` /
   `private_facts` of `role_skeleton` may only live in server-side internal state. Outbound serialization goes
   exclusively through the `_serialize_state` allowlist in `backend/main.py`; any new outbound field must be
   added to that allowlist at the same time.
2. **Reveal gating is server-side**: clue release is decided solely by `backend/oracle.py` (stage 0 alibi ->
   1 contradiction -> 2 decisive). Unreleased reveal text must never be spliced into any NPC prompt.
3. **Skeleton depth is immutable**: `role_skeleton` models are frozen + tuple and are rendered read-only via
   `prompt.render_skeleton_block`; no code may rewrite a skeleton in place.
4. **Single entry point for LLM calls**: always go through `call_llm` in `backend/llm_util.py`; do not call
   `llm.invoke` directly from business code. Failures must be able to fall back deterministically (see
   `backend/deterministic_game.py`).
5. **Idempotent actions**: every WebSocket action carries a `client_msg_id`; new actions must be added to
   `main._IDEMPOTENT_ACTIONS` and deduplicated through `_remember_action`, so replay after a reconnect never
   answers twice.

## Directory map
- `backend/main.py` — WebSocket endpoint and session orchestration (`/ws/game/{session_id}`, `/api/games`)
- `backend/dialogue.py` / `coach.py` / `judge.py` — conversation, assistant questions, scoring
- `backend/oracle.py` / `backend/role_skeleton/` — truth gating and the role skeleton layer
- `backend/persistence.py` — SQLite session persistence
- `frontend-vue/src/api/gameSocket.ts` — frontend WebSocket entry

## Common commands (run from the backend directory)
- Start the server: `python -m uvicorn main:app --reload`
- Unit tests: `python -m pytest tests/test_core.py`
- Offline skeleton self-check (24 checks): `python -m role_skeleton.selfcheck`
- Offline mode: set `AI_MURDER_OFFLINE=1` to use the deterministic path

## Friday memory collaboration (self-hosted locally, http://127.0.0.1:8080)
- Call `get_context` at the start of a session; run `memory_search` before developing a new feature or
  answering architecture questions.

### Decision record protocol (default action after finishing a module)
After finishing a module and having its tests pass, **by default** record one `add_memory`
(`project="ai-murder-mystery"`). Four sections; write "none" for any section with no content:

```
[module name] Change: <what was done>
Reason: <why it had to change / what the triggering problem was>
Tradeoff: <what was given up, and at what cost>
Blast radius: <which contracts, allowlists, or other modules are involved; what to watch for later>
```

- Triggers: adding or refactoring a module, changing WebSocket actions or outbound contracts, changing the
  `_serialize_state` allowlist, changing oracle release rules, changing skeleton structure, fixing a pitfall
  that is expensive to hit again.
- Do not record: formatting, renames, typo fixes, pure styling changes, one-off debugging changes.
- One record per change; merge repeated small edits to the same module into one record instead of flooding.
- Rules / constants / thresholds that must be preserved verbatim always go through `add_fact`, never into
  memory (where they get rewritten).

### Never write to Friday
The murderer's identity, `murder_process`, skeleton `secrets` / `private_facts`, unreleased oracle reveal
text, or player match data. Friday's `/add` sends this content out to Mem0 cloud and DeepSeek.

### Search caveat
`memory_search` returns Mem0's English-rewritten digest, not the original text; only `add_fact` preserves
content verbatim and is versioned.
