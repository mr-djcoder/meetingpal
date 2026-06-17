import { CSSProperties } from 'react';

// `-webkit-app-region` lets the bar drag the frameless window; buttons opt out.
const dragStyle: CSSProperties = { WebkitAppRegion: 'drag' } as CSSProperties;
const noDragStyle: CSSProperties = { WebkitAppRegion: 'no-drag' } as CSSProperties;

/**
 * In-app title bar shown only when the window is frameless (custom_titlebar on).
 * Draggable; provides minimize / maximize / close. The window stays resizable
 * from its edges natively.
 */
export function CustomTitleBar() {
  const api = window.electronAPI;
  return (
    <div
      style={dragStyle}
      className="flex items-center justify-between h-8 bg-gray-950 border-b border-gray-800 select-none pl-3"
    >
      <div className="flex items-center gap-2">
        <div className="w-4 h-4 bg-blue-500 rounded flex items-center justify-center text-white font-bold text-[10px]">
          M
        </div>
        <span className="text-xs font-semibold text-gray-300">MeetingPal</span>
      </div>
      <div style={noDragStyle} className="flex items-center">
        <button
          onClick={() => api.windowMinimize()}
          title="Minimize"
          className="w-11 h-8 flex items-center justify-center text-gray-400 hover:bg-gray-700 hover:text-white transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 12 12">
            <rect x="2" y="5.5" width="8" height="1" fill="currentColor" />
          </svg>
        </button>
        <button
          onClick={() => api.windowMaximize()}
          title="Maximize"
          className="w-11 h-8 flex items-center justify-center text-gray-400 hover:bg-gray-700 hover:text-white transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none" stroke="currentColor">
            <rect x="2.5" y="2.5" width="7" height="7" strokeWidth="1" />
          </svg>
        </button>
        <button
          onClick={() => api.windowClose()}
          title="Close"
          className="w-11 h-8 flex items-center justify-center text-gray-400 hover:bg-red-600 hover:text-white transition-colors"
        >
          <svg className="w-3 h-3" viewBox="0 0 12 12" stroke="currentColor" fill="none">
            <path d="M3 3l6 6M9 3l-6 6" strokeWidth="1.2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
