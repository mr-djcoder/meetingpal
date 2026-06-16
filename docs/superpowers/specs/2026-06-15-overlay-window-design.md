# Transparent Always-On-Top Overlay — Design Spec

**Date:** 2026-06-15
**Status:** Approved (pre-implementation)
**Goal:** Let the user float the MeetingPal window over other apps (e.g. a video call) and see through it, so they can watch who they're talking to while still reading the transcript and typing.

## Requirements

1. **Always-on-top toggle** — keep the window above all other windows; toggleable at runtime.
2. **Window transparency** — an adjustable slider sets whole-window opacity so apps behind show through.
3. Controls live in the **TopBar** (always visible, reachable mid-call).
4. Both settings **persist** across app restarts and re-apply on launch.

## Chosen approach

Whole-window opacity via Electron's `BrowserWindow.setOpacity()` plus `setAlwaysOnTop()`. Both are runtime-mutable, need no window recreation, and work on Windows.

Rejected: **background-only transparency** (`transparent: true` + CSS alpha) — keeps text fully crisp but forces a frameless window (custom title bar, drag, resize) and `transparent` is immutable after window creation. Too large for the need; revisit later if whole-window fade proves insufficient.

## Architecture & data flow

A thin Electron-window-property feature. The renderer drives window properties over IPC for instant effect, and persists the values through the existing preferences store so they survive restarts.

```
TopBar control (pin toggle / opacity slider)
  -> window.electronAPI.setAlwaysOnTop(bool)   -> main: mainWindow.setAlwaysOnTop(bool)      [instant]
  -> window.electronAPI.setOpacity(num)        -> main: mainWindow.setOpacity(clamp .3-1)    [instant]
  -> window.electronAPI.setPreferences({ always_on_top, window_opacity })                    [persist]

App startup:
  getPreferences() -> apply saved always_on_top + window_opacity to the window via the same IPC
```

## Components & per-file changes

- **`electron/main.ts`** — register two IPC handlers:
  - `set-always-on-top` (boolean) -> `mainWindow?.setAlwaysOnTop(value)`
  - `set-opacity` (number) -> `mainWindow?.setOpacity(clamp(value, 0.3, 1.0))`
  - The **0.3 floor** prevents fading the window into an unclickable ghost.
- **`electron/preload.ts`** — expose on the context bridge: `setAlwaysOnTop: (v: boolean) => ipcRenderer.invoke('set-always-on-top', v)` and `setOpacity: (v: number) => ipcRenderer.invoke('set-opacity', v)`.
- **`src/types/electron.d.ts`** — add `setAlwaysOnTop(value: boolean): Promise<void>` and `setOpacity(value: number): Promise<void>` to the `electronAPI` interface.
- **`backend/storage.py`** (`UserPreferences` dataclass) — add `always_on_top: bool = False` and `window_opacity: float = 1.0`, persisted to `preferences.json` exactly like `theme` / `font_size`.
- **`backend/main.py`** (`PrefsUpdate` pydantic model) — add `always_on_top: bool | None = None` and `window_opacity: float | None = None` so they round-trip through `PUT /api/preferences`.
- **`src/components/TopBar.tsx`** — add to the right-side controls:
  - a **pin button** (📌) that toggles always-on-top; visually highlighted when active.
  - a compact **opacity control**: a button showing the current % that opens a small popover with a range slider (30–100%, step 5).
  - On any change: call the corresponding IPC immediately, then persist via `setPreferences`. Initialize both from `getPreferences()` on mount.
- **`src/App.tsx`** — on startup (after `getPreferences`), apply the saved `always_on_top` and `window_opacity` to the window via IPC, so the overlay state is restored on launch.

## Behavior notes

- Whole-window opacity fades text too; the 30% floor keeps it legible and clickable. Pin + low opacity is the classic "float over my call and still read/type" overlay.
- Opacity slider range 30–100%, default 100%. Always-on-top default off.
- No window recreation or frameless rebuild — both toggles apply live.

## Testing

- **Backend (pytest):** a `storage.py` round-trip test asserting the two new preference fields default correctly and survive `save_preferences` -> `load_preferences`.
- **Frontend / main (manual):** pin toggle floats the window above another app; the slider fades the window live; quitting and relaunching restores both the pinned state and the opacity level. (No JS test runner in this repo, consistent with prior UI work.)

## Out of scope (future)

- Background-only transparency with crisp text (frameless window rebuild).
- Per-monitor / click-through ("ghost") modes.
- Global hotkeys to toggle overlay without focusing the window.
