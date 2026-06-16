# Auto-Answer Mode — Design Spec (PROPOSAL)

**Date:** 2026-06-16
**Status:** APPROVED — decisions confirmed by the user 2026-06-16. Building now.

## Confirmed decisions (override the proposals below where they differ)

- **Providers: Claude AND Gemini**, with a model picker listing the **top 3 each**:
  - Claude (stable IDs): `claude-haiku-4-5-20251001` (fast — **default**), `claude-sonnet-4-6` (balanced), `claude-opus-4-8` (most capable).
  - Gemini: **fetch the live model list from Google's ListModels API at runtime** to populate the dropdown (IDs churn — Gemini 2.0 was shut down 2026-06-01). Static fallback list if the fetch fails: `Gemini 3.5 Flash` (fast — default), `Gemini 2.5 Pro`, `Gemini 3.1 Flash-Lite`.
- **Question detection:** local heuristic over **finalized `Them` utterances only** (`is_final and speaker == "Them"`) — text ends with `?` OR begins with an interrogative lead (what/why/how/when/where/who/which/can/could/would/should/do/does/did/is/are/tell me/explain/walk me through). Never on the user's own (`You`) speech.
- **Concurrency:** fire after finalize; **one** auto-answer in flight; a new detected question **cancels + replaces** the previous (`asyncio.Task`); **~2s min-interval**.
- **Output:** stream the answer; render it prefixed literally as **`AI:<response>`**; latency-critical → default to the fast model of the chosen provider.
- **Config (persisted in `preferences.json`):** `auto_answer_enabled: bool = False`, `auto_answer_prompt: str` (first-person starter default), `auto_answer_provider: str = "claude"`, `auto_answer_model: str`.
- **Keys:** Gemini uses its **own** key in Windows Credential Manager (keytar account `gemini-api-key`), read by Electron main like the Claude key. Never hardcoded or logged.
- **Privacy:** selecting Gemini sends transcript text to Google — the README privacy section is updated to state outbound calls go to the Claude API **and** (when Gemini is selected) the Gemini API.
- **UI:** a dedicated **Suggested Answer** panel (question + streaming `AI:` answer) + a quick **TopBar toggle** + the prompt/provider/model/enable controls in **Settings**.

## Goal

A "LockedinAI"-style **auto-answer mode**: the user defines a custom prompt (a persona + instructions), and whenever a **question** appears in the live transcript from the other party, the app automatically asks Claude using that prompt and streams the answer for the user to read in real time — no manual "Ask" click. Use case: live interviews / sales calls where you read AI-suggested answers while the other person is still talking. Pairs with overlay mode (read the suggested answer while floating over the call).

## How it fits the existing app

- Transcription already emits finalized utterances per speaker (`You` / `Them`) over WebSocket (after the dual-stream + utterance-assembler work, `Them` = the other party's loopback audio).
- `backend/claude_client.py` already streams Claude answers token-by-token; `backend/main.py` already broadcasts `ai-token` / `ai-done` events and holds the API key in memory.
- So auto-answer mode is mostly: **detect a question in finalized `Them` utterances → fire the existing Claude streaming path with the custom prompt → stream to a UI surface**, plus settings + a toggle.

## Proposed architecture & data flow

```
finalized Them utterance (is_final, speaker="Them")
  -> [if auto_answer_enabled] question detector (heuristic)
      -> looks like a question? 
          -> cancel any in-flight auto-answer
          -> claude_client.ask(system=auto_answer_prompt, question=utterance, context=recent transcript, key=in-memory)
              -> stream tokens over WS  (auto_answer_start / auto_answer_token / auto_answer_done)
                  -> renderer shows the detected question + streaming answer in a dedicated "Suggested Answer" surface
```

- Runs on the sidecar event loop (the in-flight stream is an `asyncio.Task`; a new question cancels the previous task — latest question wins).
- Auto-answers are a **separate WS message channel** from the manual chat so the two never tangle.

## Open decisions (need your confirmation) — with proposed defaults

1. **Question detection** — *Proposed default: local heuristic.* Trigger on a finalized `Them` utterance that ends with `?` OR begins with an interrogative lead (what/why/how/when/where/who/which/can/could/would/should/do/does/did/is/are/tell me/explain/walk me through). Cheap, fully local, no extra Claude call.
   - Alternative: a lightweight Claude classifier ("is this a question directed at me?") per `Them` utterance — better precision, but a small API call each time. *Recommend heuristic for v1, classifier as a later toggle.*
2. **Whose speech triggers it** — *Proposed default: only `Them`.* Never auto-answer your own (`You`) speech.
3. **Concurrency / cadence** — *Proposed default: one auto-answer in flight; a new detected question cancels and replaces it.* Plus a small min-interval (~2s) so rapid-fire fragments don't thrash.
4. **The custom prompt** — *Proposed default: one global prompt* configured in **Settings** (a textarea), persisted in `preferences.json` as `auto_answer_prompt: str`, with a starter default (e.g. "You are the user in this conversation. Answer the other person's question concisely and in the first person, using the meeting context."). `auto_answer_enabled: bool` toggles the mode.
5. **UI surface** — *Proposed default: a dedicated "Suggested Answer" panel* (separate from the manual AI chat) showing the detected question + the streaming answer, so it reads cleanly in overlay mode. *Lighter alternative:* stream auto Q/A into the existing `AIChatPanel`, tagged "auto" (less new UI, but mixes with manual chat). *Recommend the dedicated panel; flag if you'd rather reuse the chat to ship smaller.*
6. **Toggle placement** — *Proposed default: a quick toggle in the TopBar* (on/off mid-call) plus the prompt + enable in Settings.
7. **Cost guardrails** — *Proposed default:* only `Them` + question filter + cancel-in-flight + min-interval; no hard daily cap in v1 (each answer is one streamed Claude call).

## Proposed component changes (subject to the decisions above)

- `backend/storage.py` / `backend/main.py` — add `auto_answer_enabled: bool = False`, `auto_answer_prompt: str = "<starter>"` to `UserPreferences` / `PrefsUpdate`.
- `backend/auto_answer.py` (NEW) — a small orchestrator: `maybe_answer(segment, prefs, api_key, broadcast)` that runs the question heuristic, manages the in-flight `asyncio.Task` (cancel-and-replace + min-interval), and drives `claude_client.ask(...)`, broadcasting `auto_answer_*` WS events. Pure-ish and unit-testable (inject a fake ask/broadcast + a clock).
- `backend/main.py` — in `_on_transcript_segment`, when `seg.is_final and seg.speaker == "Them"` and auto mode is on, hand the segment to the orchestrator on the event loop.
- `backend/claude_client.py` — reuse `ask()`; allow passing the custom system prompt (small extension if it doesn't already accept one).
- Renderer — a `Suggested Answer` panel + a Zustand store fed by `auto_answer_*` IPC events; Settings prompt textarea + enable; TopBar quick toggle.

## Testing approach (once approved)

- Unit-test the question heuristic (positive/negative cases) and the orchestrator's cancel-and-replace + min-interval logic with injected fakes (no real Claude).
- Manual: enable auto mode with a prompt, play a spoken question through the speakers, confirm a streamed answer appears within a second or two and updates live; confirm your own speech never triggers it.

## Out of scope (v1)

- LLM-based question classification (heuristic first).
- Per-session / multiple prompts.
- Auto-sending answers anywhere (read-only suggestions).
- Global hotkey toggle.

---

**Next step:** review the Open decisions, confirm or adjust, then the assistant writes the implementation plan and builds it via the subagent workflow.
