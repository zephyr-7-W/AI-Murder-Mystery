# Core Knowledge Used in This Project

> **Architecture note (updated 2026-09)**: most of what follows is an early LangGraph teaching walkthrough. The
> current web version (the `/ws/game/{session_id}` endpoint in backend/main.py) no longer runs the main graph
> and subgraph node by node. Its main path is now **WebSocket action driven + in-memory sessions + SQLite
> persistence**:
> - Every action (player_message / auto_ask / investigate / ask_hint / confront / make_guess ...) carries a
>   `client_msg_id`; the server processes each session serially under a lock and deduplicates by message id, so
>   replay after a reconnect never answers the same line twice;
> - the truth oracle (backend/oracle.py) releases clues through a **staged disclosure table**
>   (alibi -> contradiction -> decisive). Unreleased secrets never enter an NPC's context, and it adds soft
>   proximity feedback so that players neither "chat a lot without lighting up a single clue" nor get the whole
>   truth spoiled immediately;
> - conversation, assistant questions, investigation, hints, and scoring are split across
>   backend/dialogue.py, backend/coach.py, and backend/judge.py; all LLM calls are wrapped in
>   backend/llm_util.py (retry / backoff / rate limiting); scoring can be unit tested by injecting a fake LLM;
> - match list REST: GET /api/games, GET/DELETE /api/games/{session_id} (history survives a device switch).
> Unit tests for new or refactored modules live in backend/tests/test_core.py; the offline self-check is
> `role_skeleton/selfcheck`.

## 1. LangGraph
State graph: a directed graph orchestrates the business flow; nodes, edges, and conditional branches drive game
state transitions.
Typed state (Pydantic):
-- GenerateGameState: global game state for the main graph (characters, case, remaining attempts, selected
   character id, global messages)
-- ConversationState: an isolated subgraph state for a single-NPC conversation session
Subgraph: one conversation subgraph embedded in the main graph, handling multi-round loops between the player
and each individual NPC.
Conditional edges: branch on the return value (leaving a conversation returns to the main flow; a wrong guess
returns to investigation).
Recursion limit: prevents an unbounded conversation loop.

## 2. LLM application engineering
System prompt engineering: complex structured prompts constrain the model's output; normal conversation prompts
are separated from JSON-forced-output prompts.
Structured output tolerance: LLM output is unstable, so strip JSON code-fence markers, convert odd lists to
strings, and retry up to 3 times.
Pydantic model validation: Character / NPC / StoryDetails / ConversationState validate data and block dirty LLM
output.
Prompt-level truth isolation: only the internal side sees the murderer's truth, while the output side is
strictly forbidden from revealing the murderer, which is what makes misleading-clue generation possible.

## 3. Core Python engineering
Object-oriented Pydantic models with strongly typed data encapsulation.
JSON cleaning, exception handling, retry logic.
The rich terminal UI library: panels, tables, interactive command-line input/output (the prototype console UI).
Randomization: the character list is shuffled so the murderer's position is never fixed.

## 4. Web layer

## 5. Business design

# Full workflow: main graph + conversation subgraph
## Main graph GenerateGameState (7 nodes)
create_characters: the first step of game initialization. Takes the environment and the max character count;
calls the LLM to generate the whole cast; enforces exactly 1 murderer and 1 victim with the rest as suspects;
retries on JSON errors; returns the character list into state.

create_story: generates the full case. Based on the already-generated characters, the LLM produces every
detail of the murder: time of death, location, weapon, scene, witnesses, clues, relationship summary, and the
murder truth `murder_process`; cleans and repairs malformed LLM output; returns the story_details case object.

narrartor: generates the opening case narration, renders the game prologue, and stores the opening message in
state's messages.

sherlock: the character selection node: shows the full character list, reads player input, and returns
selected_character_id.

conversation: the subgraph entry dispatch node: takes the selected character id, dynamically builds a
conversation subgraph instance and invokes it, runs the full multi-round conversation between the player and
that NPC, then merges all subgraph conversation messages back into the main graph state.

guesser: the final accusation node. Shows the suspect list, reads the player's chosen number, and compares it
against the real murderer. Correct: game over. Wrong: lose an attempt. Attempts remain: return to sherlock to
keep investigating. Attempts exhausted: fail and end. Returns `result` for the conditional edge to branch on.

START
  |
create_characters -> create_story -> narrartor -> sherlock (pick a character)
  |-- selected character id present -> conversation (run the conversation subgraph) -> back to sherlock
  |-- selected_character_id=None -> guesser (enter accusation)
        |-- result="sherlock" -> return to sherlock, keep investigating
        |-- result="end" -> END, game over

## Conversation subgraph ConversationState (5 nodes, handles multi-round chat with one NPC)
character_introduction: NPC self-introduction: based on the character persona and the case background, the LLM
generates an opening line.

ask_question: obtains the player's question: interactively asks whether to enable the AI detective assistant;
on "y" it calls get_question so the LLM generates a sharp question; on "n" it reads the player's manual input;
wraps the question as a HumanMessage.

get_question: the AI detective assistant: based on conversation history and case details, generates one
follow-up question. (Called internally by ask_question.)

answer_question: the core of the role-played NPC answers: receives the full persona, the case, and the
conversation history; the LLM answers in character and may lie or withhold; outputs an AIMessage into the
subgraph messages.

where_to_go: a conditional routing function, not a real node: checks whether the player's input contains EXIT.
continue: keep looping questions and answers; end: leave the subgraph and return to the main flow.

START -> character_introduction -> ask_question
  |-- where_to_go: continue -> answer_question -> ask_question (loop)
  |-- where_to_go: end -> END (leave the subgraph, back to the main graph)

# 6. Role hard-constraint skeleton layer (role_skeleton)

On top of the existing LangGraph orchestration, this adds a **reusable "role hard-constraint skeleton"**:
every agent = a static skeleton (secrets / timeline / red lines / forbidden output list / knowledge bounds,
stored separately and immutable) + a dynamic conversation layer that only handles expression.

- Shipped: the real-time web conversation (`_answer_as_character` in main.py) injects the skeleton and runs the
  full generate -> anti-leak audit -> corrective retry -> deterministic fallback loop;
- the detector does not depend on a second LLM: literal phrases + regex + out-of-character phrasing +
  long-string anchor matching for secrets and knowledge bounds;
- supports sandboxes beyond murder mystery (business negotiation, project simulation, etc.; see the examples
  JSON);
- 24 offline self-checks: run from the backend directory
  `venv\Scripts\python.exe -m role_skeleton.selfcheck`

Design details and the file map are in role_skeleton/README.md.
