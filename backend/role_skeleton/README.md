# Role Hard-Constraint Skeleton Layer

One-line positioning: give every agent a role skeleton that is **stored separately, injected read-only, and
strictly validated**, upgrading problems such as "the character goes out of character at any moment, secrets
leak, the logic falls apart" from "hope the system prompt behaves" into an **engine-level constraint loop**.

Use cases go well beyond murder mystery: business negotiation sandboxes, project simulation, multi-party
interest games, teaching simulations.

## 1. How this differs from MetaGPT / AgentScope

| Capability | MetaGPT | AgentScope | This skeleton layer |
| --- | --- | --- | --- |
| Inter-agent messaging | Yes (SOP orchestration) | Yes (message bus) | Not responsible for messaging, only for constraints |
| Character consistency | Relies on the prompt | Relies on the prompt | Skeleton registry + frozen objects + output audit |
| Secrets / knowledge bounds | No dedicated mechanism | No dedicated mechanism | `secrets` + `knowledge.unknown` corpora never enter the prompt |
| OOC interception | No | No | Meta-info regex + anchors + guided retry + deterministic fallback |
| Skeleton can be rewritten | Unconstrained | Unconstrained | Pydantic frozen + tuple containers; not even code can write |
| Observable audit | No | No | Per-round `RoundRecord` (which round, which rule hit) |

Bottom line: mainstream frameworks only solve "how an agent speaks and how messages travel"; this layer solves
"what an agent **must not say, must not pretend to know, and where its red lines are**", and guarantees it in
code rather than in wording.

## 2. Architecture

Every agent is split into two parts:

1. **Static skeleton layer (this directory)**: secrets, timeline, red lines, forbidden output list, and
   knowledge bounds, configured by hand or produced by engine rules.
2. **Dynamic conversation layer (the caller)**: only handles expression, reading the rendered skeleton text as
   the highest-priority background.

```text
role skeleton (frozen object)
   |  render_skeleton_block() read-only render
   v
System Prompt = skeleton block + dynamic conversation instructions
   |  call the LLM to produce one line
   v
LeakGuard.audit() --clean--> pass
   +--violation--> build_steering() categorized correction guidance --> regenerate (up to max_retry times)
                      +--still violating--> deterministic fallback reply; violating text is never passed
```

## 3. Three layers of tamper resistance

1. **Frozen data structures**: `RoleSkeleton` and all nested models are `frozen`, and every container is a
   `tuple` (lists are converted automatically at construction). Read-only for both the LLM and business code.
2. **The LLM never receives the object**: the skeleton is rendered into a plain string by
   `render_skeleton_block()` and spliced into the prompt; there is no tool or parameter that can rewrite the
   skeleton.
3. **Sealed at registration**: the game assembles skeletons once at `start_game` and only reuses them read-only
   afterwards; the engine exposes no update entry point (upgrading this to a
   `RoleSkeletonRegistry.seal()` semantic is on the roadmap).

## 4. What the detector (LeakGuard) intercepts

| Source | Description | Example |
| --- | --- | --- |
| `forbidden_phrase` | Literal forbidden list, normalized substring match | "我就是凶手" ("I am the murderer"), "预算上限是120万" ("the budget cap is 1.2M") |
| `forbidden_pattern` | Regex forbidden list, matches numbers and variants | synonymous rewrites around "预算…120万" ("budget ... 1.2M") |
| `meta_leak` | Out-of-character phrasing | "作为AI我只能说……" ("as an AI I can only say ...") |
| `secret` | The character's own classified content being repeated (long-string anchor match) | the murderer retelling the crime as their own "story" |
| `unknown_fact` | Stating a fact outside the knowledge bounds | a suspect "knowing" a detail only the murderer knows |

Note: the `forbidden_*` and `unknown` corpora **exist only inside the detector** and are never rendered into the
prompt, so the model is not taught how to get around them. The Chinese strings above are the real literals the
detector matches, so they are kept verbatim (see `examples/negotiation_sandbox_roles.json`).

## 5. Files and integration points

| File | Responsibility |
| --- | --- |
| `schema.py` | Data structures: `RoleSkeleton` / `Secret` / `KnowledgeBoundary` / `TimelineEvent` / `SkeletonPolicy` |
| `prompt.py` | `render_skeleton_block()` read-only rendering |
| `guard.py` | `LeakGuard` deterministic detection + `build_steering()` correction guidance |
| `runner.py` | `constrained_answer()` generate -> audit -> retry -> fallback loop |
| `murder_factory.py` | Murder-mystery adaptation: characters + case -> skeleton (deterministic, no LLM involved) |
| `examples/negotiation_sandbox_roles.json` | Generic business negotiation sandbox example (the JSON goes straight into `RoleSkeleton.model_validate`) |
| `selfcheck.py` | 24 offline self-checks (no API key needed) |

### Murder-mystery integration (already wired into the web conversation in `main.py`)

- After `start_game`: `session_state["_skeletons"] = build_murder_skeletons(characters, story_details)`.
  Skeletons live in the **session layer rather than the game state**, so they can never leak to the frontend
  through WebSocket serialization.
- `_answer_as_character(..., skeleton)`: injects the skeleton block into the system prompt, then runs
  `constrained_answer(skeleton, generate, fallback=..., max_retry=2)`.
- Every violation retry or fallback is logged: character, round, and which rule source was hit.

Automatic skeleton assembly rules (`murder_factory.py`):

- **Murderer**: `secrets` carry the real crime process (self-consistent, able to sustain lies); paired with a
  confession regex plus a literal forbidden list; red lines = never admit it personally, never describe the
  real method.
- **Suspect**: `knowledge.unknown` stores detection corpora such as "who the real murderer is" and "the real
  sequence of events" (they never enter the prompt); paired with a regex against fabricated eyewitness
  accounts; red lines = do not confess, do not pose as a witness.
- **Victim**: no conversational skeleton is generated.

### General usage (negotiation / simulation / teaching)

```python
import json
from role_skeleton.schema import RoleSkeleton
from role_skeleton.guard import LeakGuard

roles = [RoleSkeleton.model_validate(r) for r in json.load(open("negotiation_sandbox_roles.json"))["roles"]]
guard = LeakGuard(roles[0])          # the procurement side
print(guard.audit("我们预算上限是120万，不能再高了。").clean)  # False - the leak is blocked
```

The audited string is Chinese because the example role data defines its forbidden phrases in Chinese.

## 6. Running the self-check

```powershell
cd backend
venv\Scripts\python.exe -m role_skeleton.selfcheck
```

Current expectation: `24 passed, 0 failed` (offline; no model is called).

## 7. Known limits and roadmap

- Anchor matching has limited ability to catch **paraphrased** leaks; for stronger coverage, add a semantic
  judge (a second LLM or vector recall) as a pluggable `LeakGuard` validator (the interface is not built in
  yet; this is stated in the docs).
- Classified content is still shown to the role player themselves (the murderer must know the truth to sustain
  lies); this layer's defense is on **outbound output**, not on making the model ignorant.
- The CLI / LangGraph conversation nodes in `game_nodes.py` do not apply the skeleton yet (the real-time web
  conversation is wired up); aligning them is the next step.
- Roadmap: a sealed registry `RoleSkeletonRegistry`, dynamic release driven by `Secret.reveal_condition`,
  per-round audit persistence, timeline conflict self-check, and frontend cards that show only the "public
  dossier".
