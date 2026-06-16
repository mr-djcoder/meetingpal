# Auto-Answer Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** When a question from the other party (`Them`) is finalized in the transcript, automatically ask the chosen LLM (Claude or Gemini) using a user-defined prompt and stream the answer, rendered as `AI:<response>`. Fast (default to each provider's fast model), with a Settings config + TopBar toggle + a dedicated Suggested-Answer panel.

**Architecture:** A backend question-heuristic + an `AutoAnswerOrchestrator` (cancel-and-replace one in-flight `asyncio.Task`, ~2s min-interval) that dispatches to a provider client (`ClaudeClient` or new `GeminiClient`) and broadcasts `auto_answer_*` WS events. Keys come from the Electron main process (Credential Manager): the existing Claude key and a new `gemini-api-key`. The renderer shows a Suggested-Answer panel fed by IPC.

**Spec:** `docs/superpowers/specs/2026-06-16-auto-answer-mode-design.md` (confirmed decisions at top).

**Branch:** `feat/auto-answer-mode` (off main; has the design doc). No `tests/` yet — Task 0 adds pytest.

---

### Task 0 — pytest infra
- Add `pytest==8.2.0` to requirements.txt; `tests/__init__.py` + `tests/test_smoke.py` (`def test_smoke(): assert True`). Run, commit `test: add pytest infrastructure`.

### Task 1 — auto-answer preferences
- `backend/storage.py` `UserPreferences`: add `auto_answer_enabled: bool = False`, `auto_answer_prompt: str = "You are me in this conversation. Answer the other person's question concisely, in the first person, using the meeting context."`, `auto_answer_provider: str = "claude"`, `auto_answer_model: str = "claude-haiku-4-5-20251001"`.
- `backend/main.py` `PrefsUpdate`: same four as `... | None = None`.
- `src/types/electron.d.ts` `UserPreferences`: add the four fields (`auto_answer_enabled: boolean`, `auto_answer_prompt: string`, `auto_answer_provider: string`, `auto_answer_model: string`).
- Test `tests/test_storage.py`: defaults + round-trip + old-file backward-compat (mirror the pattern used elsewhere; use `monkeypatch.setenv("APPDATA", tmp_path)` + `importlib.reload`).
- Commit `feat: persist auto-answer preferences`.

### Task 2 — question heuristic (pure, no deps)
- `backend/auto_answer.py` (NEW), module-level `def is_question(text: str) -> bool`: strip; lowercased; return True if it ends with `?` OR the first word is in the interrogative set {what, why, how, when, where, who, which, can, could, would, should, do, does, did, is, are} OR it starts with "tell me" / "explain" / "walk me through". Empty → False.
- `tests/test_auto_answer.py`: positives ("What's your experience?", "How would you scale this?", "Tell me about yourself", "Is that correct?") and negatives ("I think we should ship.", "", "Okay sounds good.").
- Commit `feat: add question-detection heuristic`.

### Task 3 — GeminiClient (mirror ClaudeClient)
- `backend/gemini_client.py` (NEW). `class GeminiClient` with `async def ask(self, question, segments, history, api_key, model) -> AsyncGenerator[dict, None]` yielding the SAME event dict shape as `ClaudeClient.ask` (`{"type": "content_delta", "text": ...}` for tokens, a terminal `{"type": "message_stop", ...}` — match claude_client.py's exact event types after reading it). Build the system prompt from the transcript like ClaudeClient. Use the `google-genai` SDK streaming API; read the key from the `api_key` arg. Wrap network/SDK errors and yield an `{"type": "error", "message": ...}` event instead of raising.
- `requirements.txt`: add a pinned `google-genai` (latest stable). If it cannot be installed in this environment, still write the client and note it.
- No unit test for live calls; add an import smoke (`import backend.gemini_client`) — but keep heavy imports inside `ask` if needed so the module imports without the SDK present.
- Commit `feat: add streaming Gemini client`.

### Task 4 — AutoAnswerOrchestrator
- In `backend/auto_answer.py` add `class AutoAnswerOrchestrator`. Constructor takes injected `broadcast(event: dict)` (async or sync — define one), a `now_fn=time.monotonic` (injectable for tests), and a `min_interval_s=2.0`. Holds the current in-flight `asyncio.Task | None` and `last_fire_monotonic`.
- `async def maybe_answer(self, segment, prefs, claude_key, gemini_key, segments, history)`: return early unless `prefs.auto_answer_enabled and segment.is_final and segment.speaker == "Them" and is_question(segment.text)` and `now - last_fire >= min_interval_s`. Cancel any in-flight task. Pick the provider client + key (claude → ClaudeClient + claude_key; gemini → GeminiClient + gemini_key); if the needed key is missing, broadcast an `auto_answer_error` and return. Start a new task that: broadcasts `{"type":"auto_answer_start","question":text}`, streams `client.ask(...)`, for each `content_delta` broadcasts `{"type":"auto_answer_token","text":...}`, then `{"type":"auto_answer_done"}`.
- Test `tests/test_auto_answer.py` with INJECTED fakes (a fake client whose `ask` yields a couple of `content_delta`s, a recording `broadcast`, a controllable `now_fn`): asserts a `Them` question fires start/token/done; a `You` line does NOT fire; a non-question does NOT fire; a second question within `min_interval` is skipped; a second question after the interval cancels+replaces (the first task is cancelled). Use `pytest.mark.asyncio` or `asyncio.run` helpers — keep the module importable without torch (do NOT import transcriber/whisper).
- Commit `feat: add auto-answer orchestrator with cancel-replace + min-interval`.

### Task 5 — wire into the sidecar (main.py)
- `backend/main.py`: hold a module `_gemini_key_memory: str | None`; add `POST /api/key/gemini` (mirror `/api/key`). Add `GET /api/gemini/models` that lists Gemini models via the SDK using `_gemini_key_memory` (fallback to the static list from the spec on failure). Create one `AutoAnswerOrchestrator` (broadcast = the existing `_broadcast`). In `_on_transcript_segment`, after the upsert, if `prefs.auto_answer_enabled`, schedule `orchestrator.maybe_answer(...)` on `event_loop` (it's called from the worker thread — use `call_soon_threadsafe` + `ensure_future`), passing the active session's segments/history and the in-memory keys.
- Confirm import + suite. Commit `feat: wire auto-answer into the sidecar`.

### Task 6 — Electron main + preload + types
- `electron/main.ts`: forward WS `auto_answer_start|auto_answer_token|auto_answer_done|auto_answer_error` to the renderer (`auto-answer-*`). Add IPC `set-gemini-key` (keytar account `gemini-api-key`, store + POST to `/api/key/gemini`), `has-gemini-key`, and `get-gemini-models` (GET `/api/gemini/models`). On startup, if a `gemini-api-key` exists in keytar, POST it to the sidecar like the Claude key is handled.
- `electron/preload.ts` + `src/types/electron.d.ts`: expose `onAutoAnswerStart/Token/Done/Error`, `setGeminiKey`, `hasGeminiKey`, `getGeminiModels`.
- tsc. Commit `feat: expose auto-answer IPC + Gemini key/model bridge`.

### Task 7 — renderer store + Suggested-Answer panel
- `src/store/autoAnswerStore.ts` (Zustand): `{ enabled, question, answer, streaming }` + actions fed by the IPC events (start sets question + clears answer + streaming=true; token appends; done sets streaming=false).
- `src/components/SuggestedAnswerPanel.tsx`: shows the detected question and the streaming answer rendered as `AI: {answer}` with a cursor while streaming; empty state "Auto-answers will appear here." Subscribe to the IPC events in a hook/effect (in App or the panel).
- Commit `feat: suggested-answer panel + store`.

### Task 8 — Settings + TopBar + layout
- `src/components/Settings.tsx`: an "Auto-answer" section — enable toggle, prompt `<textarea>`, provider `<select>` (Claude/Gemini), model `<select>` (Claude → the 3 static IDs; Gemini → `getGeminiModels()` with the static fallback), and a Gemini API-key input (calls `setGeminiKey`). Persist via `setPreferences`.
- `src/components/TopBar.tsx`: a quick auto-answer on/off toggle (calls `setPreferences({auto_answer_enabled})`).
- `src/App.tsx`: render `SuggestedAnswerPanel` (e.g. above the AI chat panel, or as a band) when `auto_answer_enabled`.
- tsc. Commit `feat: auto-answer settings, toggle, and panel wiring`.

### Task 9 — verify + README + PR
- Live-test the **Claude** path (the Claude key is already in Credential Manager): enable auto-answer, play a spoken question through the speakers, confirm an `AI:` answer streams within ~1–2s and that your own speech never triggers it. (Gemini path needs the user's new key — leave for them.)
- README: privacy section — outbound calls go to the Claude API and (when Gemini is selected) the Gemini API; mention auto-answer mode.
- Run the full pytest suite. Push `feat/auto-answer-mode`; open a PR into main "Auto-answer mode (Claude + Gemini)" with the decisions, test output, and a "pending manual verify (Gemini live, full UI)" list.

---

## Self-Review
- Spec coverage: providers+models (T1,T3,T6,T8), heuristic (T2), orchestrator cancel/replace+min-interval (T4), `AI:` output (T7), prefs (T1), keys via keytar (T6), privacy (T9), UI panel+settings+toggle (T7,T8). ✓
- Keep `backend/auto_answer.py` free of torch/whisper imports so its tests run without the ML stack. ✓
- Provider event-dict shape must match `claude_client.py` exactly — implementers read it first. ✓
