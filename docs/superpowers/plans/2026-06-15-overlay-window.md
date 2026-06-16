# Transparent Always-On-Top Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user float the window over other apps and fade it (whole-window opacity) so they can watch a video call while reading the transcript and typing, with the overlay state persisted across restarts.

**Architecture:** A thin Electron window-property feature. TopBar controls drive `BrowserWindow.setAlwaysOnTop()` / `setOpacity()` over IPC for instant effect, and persist `always_on_top` + `window_opacity` through the existing `preferences.json` store; the saved values are re-applied on startup.

**Tech Stack:** Electron 30 (main + preload IPC), React 18 + TypeScript renderer, Python FastAPI prefs store (pytest for the backend round-trip test).

**Spec:** `docs/superpowers/specs/2026-06-15-overlay-window-design.md`

**Branch note:** this branch is based on `main`, which has no `tests/` directory or pytest yet — Task 0 adds them. If the branch already has pytest installed and a `tests/` package, skip Task 0.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `requirements.txt` | add pytest | Modify |
| `tests/__init__.py`, `tests/test_smoke.py` | test scaffold | **Create** |
| `backend/storage.py` | `UserPreferences` gains `always_on_top`, `window_opacity` | Modify |
| `backend/main.py` | `PrefsUpdate` gains the two fields | Modify |
| `tests/test_storage.py` | prefs round-trip test for the new fields | **Create** |
| `electron/main.ts` | `set-always-on-top` + `set-opacity` IPC handlers (opacity clamped) | Modify |
| `electron/preload.ts` | expose `setAlwaysOnTop`, `setOpacity` | Modify |
| `src/types/electron.d.ts` | add the two API methods + two `UserPreferences` fields | Modify |
| `src/components/TopBar.tsx` | pin toggle + opacity popover, wired to IPC + persistence | Modify |
| `src/App.tsx` | apply saved overlay prefs to the window on startup | Modify |

---

### Task 0: Test infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest==8.2.0
```

- [ ] **Step 2: Install it**

Run: `.venv/Scripts/python.exe -m pip install pytest==8.2.0`
Expected: `Successfully installed pytest-8.2.0` (or already satisfied).

- [ ] **Step 3: Create the test package + smoke test**

Create `tests/__init__.py` (empty). Create `tests/test_smoke.py`:

```python
def test_smoke():
    assert True
```

- [ ] **Step 4: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_smoke.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py tests/test_smoke.py
git commit -m "test: add pytest infrastructure"
```

---

### Task 1: Persist overlay preferences (backend)

Add `always_on_top` and `window_opacity` to the preferences store and the update model.

**Files:**
- Modify: `backend/storage.py` (`UserPreferences`, lines ~24-34)
- Modify: `backend/main.py` (`PrefsUpdate`, the `class PrefsUpdate(BaseModel)` block)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_storage.py`:

```python
import importlib
from dataclasses import asdict


def test_new_overlay_fields_default(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)  # rebind PREFS_DIR/PREFS_FILE under the temp APPDATA

    prefs = storage.UserPreferences()
    assert prefs.always_on_top is False
    assert prefs.window_opacity == 1.0


def test_overlay_fields_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    prefs = storage.UserPreferences(always_on_top=True, window_opacity=0.55)
    storage.save_preferences(prefs)
    loaded = storage.load_preferences()
    assert loaded.always_on_top is True
    assert loaded.window_opacity == 0.55


def test_unknown_keys_ignored_old_files_still_load(tmp_path, monkeypatch):
    # An older preferences.json without the new keys must still load with defaults.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import backend.storage as storage
    importlib.reload(storage)

    storage.PREFS_DIR.mkdir(parents=True, exist_ok=True)
    storage.PREFS_FILE.write_text('{"theme": "dark", "font_size": 14}', encoding="utf-8")
    loaded = storage.load_preferences()
    assert loaded.always_on_top is False
    assert loaded.window_opacity == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_storage.py -v`
Expected: FAIL — `AttributeError`/`TypeError` because `UserPreferences` has no `always_on_top` / `window_opacity`.

- [ ] **Step 3: Add the fields to `UserPreferences`**

In `backend/storage.py`, in the `UserPreferences` dataclass, add these two lines immediately after `onboarding_completed: bool = False`:

```python
    always_on_top: bool = False
    window_opacity: float = 1.0
```

- [ ] **Step 4: Add the fields to `PrefsUpdate`**

In `backend/main.py`, in `class PrefsUpdate(BaseModel)`, add immediately after `onboarding_completed: bool | None = None`:

```python
    always_on_top: bool | None = None
    window_opacity: float | None = None
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_storage.py -v`
Expected: `3 passed`.
Also confirm the sidecar still imports: `.venv/Scripts/python.exe -c "import backend.main; print('ok')"` → `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/storage.py backend/main.py tests/test_storage.py
git commit -m "feat: persist always_on_top and window_opacity preferences"
```

---

### Task 2: Window-property IPC handlers (main process)

**Files:**
- Modify: `electron/main.ts`

- [ ] **Step 1: Add a clamp helper + two IPC handlers**

In `electron/main.ts`, find the block of `ipcMain.handle(...)` registrations (the line `ipcMain.handle('get-preferences', () => apiRequest('GET', '/api/preferences'));`). Immediately AFTER the `set-preferences` handler (the block starting `ipcMain.handle('set-preferences', ...)`), add:

```typescript
// ── Overlay window controls ─────────────────────────────────────────────────
const MIN_OPACITY = 0.3;

ipcMain.handle('set-always-on-top', (_e, value: boolean) => {
  mainWindow?.setAlwaysOnTop(Boolean(value));
  return Boolean(value);
});

ipcMain.handle('set-opacity', (_e, value: number) => {
  const clamped = Math.min(1, Math.max(MIN_OPACITY, Number(value)));
  mainWindow?.setOpacity(clamped);
  return clamped;
});
```

Notes: `setOpacity` and `setAlwaysOnTop` are valid Electron `BrowserWindow` methods on Windows. The 0.3 floor stops the window fading into an unclickable ghost. Handlers return the applied value so the renderer can reflect any clamping.

- [ ] **Step 2: Verify the renderer/main build compiles**

Run: `npx tsc --noEmit -p tsconfig.electron.json`
Expected: no errors. (If `tsconfig.electron.json` does not exist, run `npx tsc --noEmit -p tsconfig.json` instead.)

- [ ] **Step 3: Commit**

```bash
git add electron/main.ts
git commit -m "feat: add set-always-on-top and set-opacity IPC handlers"
```

---

### Task 3: Expose the overlay API (preload + types)

**Files:**
- Modify: `electron/preload.ts`
- Modify: `src/types/electron.d.ts`

- [ ] **Step 1: Expose the two methods in the preload bridge**

In `electron/preload.ts`, inside the `contextBridge.exposeInMainWorld('electronAPI', { ... })` object, add these entries (place them right after the `hasApiKey` entry):

```typescript
  // Overlay window controls
  setAlwaysOnTop: (value: boolean) => ipcRenderer.invoke('set-always-on-top', value),
  setOpacity: (value: number) => ipcRenderer.invoke('set-opacity', value),
```

- [ ] **Step 2: Add the methods and prefs fields to the type declaration**

In `src/types/electron.d.ts`:

(a) In `interface UserPreferences`, add after `onboarding_completed: boolean;`:

```typescript
  always_on_top: boolean;
  window_opacity: number;
```

(b) In `interface ElectronAPI`, add after `hasApiKey(): Promise<boolean>;`:

```typescript
  setAlwaysOnTop(value: boolean): Promise<boolean>;
  setOpacity(value: number): Promise<number>;
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add electron/preload.ts src/types/electron.d.ts
git commit -m "feat: expose setAlwaysOnTop and setOpacity on the context bridge"
```

---

### Task 4: TopBar overlay controls

Add a pin (always-on-top) toggle and an opacity popover to the TopBar, wired to IPC for instant effect and to `setPreferences` for persistence, initialized from `getPreferences`.

**Files:**
- Modify: `src/components/TopBar.tsx`

- [ ] **Step 1: Add overlay state + initialization**

In `src/components/TopBar.tsx`, inside the `TopBar` component, after the existing `const [hasKey, setHasKey] = useState(false);` line, add:

```tsx
  const [alwaysOnTop, setAlwaysOnTop] = useState(false);
  const [opacity, setOpacityState] = useState(1);
  const [opacityOpen, setOpacityOpen] = useState(false);
```

Then, after the existing `useEffect(() => { window.electronAPI.hasApiKey()... }, []);`, add a second effect that loads the saved overlay prefs and reflects them locally (the window itself is applied at app startup in Task 5):

```tsx
  useEffect(() => {
    window.electronAPI.getPreferences().then((prefs) => {
      setAlwaysOnTop(Boolean(prefs.always_on_top));
      setOpacityState(prefs.window_opacity ?? 1);
    }).catch(() => { /* keep defaults */ });
  }, []);
```

- [ ] **Step 2: Add the toggle + opacity handlers**

Still inside the component, after `handleToggle`, add:

```tsx
  const toggleAlwaysOnTop = async () => {
    const next = !alwaysOnTop;
    setAlwaysOnTop(next);
    await window.electronAPI.setAlwaysOnTop(next);
    await window.electronAPI.setPreferences({ always_on_top: next });
  };

  const changeOpacity = async (value: number) => {
    setOpacityState(value);
    const applied = await window.electronAPI.setOpacity(value);
    await window.electronAPI.setPreferences({ window_opacity: applied });
  };
```

- [ ] **Step 3: Render the controls in the right-side group**

In the JSX, locate the right-side controls container (the `<div className="flex items-center gap-3">` that holds the API-key status and the Settings button). Insert these two controls as the FIRST children of that div (before the API key status block):

```tsx
        {/* Always-on-top pin */}
        <button
          onClick={toggleAlwaysOnTop}
          title={alwaysOnTop ? 'Unpin (allow other windows on top)' : 'Pin on top of all windows'}
          className={`p-1.5 rounded transition-colors ${
            alwaysOnTop ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-700'
          }`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5l14 14M9 5h6l-1 5 3 3v2H7v-2l3-3-1-5z" />
          </svg>
        </button>

        {/* Opacity control */}
        <div className="relative">
          <button
            onClick={() => setOpacityOpen((v) => !v)}
            title="Window transparency"
            className="px-2 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
          >
            {Math.round(opacity * 100)}%
          </button>
          {opacityOpen && (
            <div className="absolute right-0 top-8 z-20 bg-gray-800 border border-gray-600 rounded-lg p-3 shadow-lg w-44">
              <label className="text-xs text-gray-400 block mb-2">Transparency</label>
              <input
                type="range"
                min={30}
                max={100}
                step={5}
                value={Math.round(opacity * 100)}
                onChange={(e) => changeOpacity(Number(e.target.value) / 100)}
                className="w-full accent-blue-500"
              />
              <div className="text-xs text-gray-500 mt-1 text-right">{Math.round(opacity * 100)}%</div>
            </div>
          )}
        </div>
```

- [ ] **Step 4: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/TopBar.tsx
git commit -m "feat: TopBar always-on-top pin and opacity control"
```

---

### Task 5: Apply saved overlay state on startup

So the pinned/opacity state is restored when the app launches.

**Files:**
- Modify: `src/App.tsx`

- [ ] **Step 1: Apply overlay prefs in the startup effect**

In `src/App.tsx`, inside the `MainLayout` component there is a `useEffect` that calls `window.electronAPI.getPreferences().then((prefs) => { ... })` to apply theme/font. Extend that same `.then` callback to also apply the overlay prefs. After the existing lines that set theme/font (e.g. `document.documentElement.style.setProperty('--transcript-font-size', ...)`), add:

```tsx
      const overlay = prefs as unknown as { always_on_top?: boolean; window_opacity?: number };
      window.electronAPI.setAlwaysOnTop(Boolean(overlay.always_on_top));
      window.electronAPI.setOpacity(overlay.window_opacity ?? 1);
```

If that effect's callback types `prefs` narrowly, the `as unknown as { ... }` cast above keeps it compiling without widening the existing type.

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/App.tsx
git commit -m "feat: restore overlay (always-on-top + opacity) on startup"
```

---

### Task 6: Live verification + README + push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Launch the app**

Ensure nothing is on port 8001 (kill any stray `python` listening there). From a shell with `.venv` active:
Run: `npm run dev`
Expected: the window opens; the TopBar shows the new pin button and an `100%` opacity button.

- [ ] **Step 2: Verify always-on-top**

Click the pin button (it highlights blue). Open another app (e.g. a browser) and click it. The MeetingPal window stays visible above it. Click the pin again — it unhighlights and the window no longer floats.

- [ ] **Step 3: Verify opacity**

Click the `100%` button, drag the slider down to ~50%. The whole window fades so the app behind shows through, and the slider never goes below 30%. Set it back up.

- [ ] **Step 4: Verify persistence**

Set pin ON and opacity ~60%, then fully quit the app and run `npm run dev` again. The window comes back pinned and at ~60% opacity.

- [ ] **Step 5: Update README**

In `README.md`, under the feature description / Status area, add a short bullet noting the overlay: "Overlay mode: pin the window always-on-top and adjust whole-window transparency (TopBar controls) to float over a call while reading the transcript."

- [ ] **Step 6: Commit + push**

```bash
git add README.md
git commit -m "docs: document overlay (always-on-top + transparency) mode"
git push origin feat/overlay-window
```

---

## Self-Review

**Spec coverage:**
- Always-on-top toggle → Task 2 (handler), Task 4 (pin button), Task 5 (restore). ✓
- Adjustable whole-window opacity → Task 2 (handler + 0.3 clamp), Task 4 (slider), Task 5 (restore). ✓
- Controls in TopBar → Task 4. ✓
- Persist + re-apply on launch → Task 1 (store), Task 4 (persist on change), Task 5 (apply on startup). ✓
- Backend round-trip test → Task 1. ✓
- 30–100% range, default 100%, default not-pinned → Task 1 defaults + Task 4 slider min/max. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows the exact code. Task 5's cast is concrete. The one judgement step (Task 4 Step 3 "locate the right-side controls container") references the specific existing `<div className="flex items-center gap-3">` and gives the exact JSX to insert.

**Type consistency:** `setAlwaysOnTop(value: boolean): Promise<boolean>` and `setOpacity(value: number): Promise<number>` match across preload (Task 3), the type decl (Task 3), and all call sites (Tasks 4, 5). Pref keys `always_on_top` / `window_opacity` are identical across `UserPreferences` (Task 1), `PrefsUpdate` (Task 1), the TS `UserPreferences` (Task 3), and all reads/writes (Tasks 4, 5).
