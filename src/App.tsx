import { useEffect, useRef, useState } from 'react';
import { AIChatPanel } from './components/AIChatPanel';
import { CustomTitleBar } from './components/CustomTitleBar';
import { Settings } from './components/Settings';
import { SuggestedAnswerPanel } from './components/SuggestedAnswerPanel';
import { TopBar } from './components/TopBar';
import { TranscriptPanel } from './components/TranscriptPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { useAutoAnswerStore } from './store/autoAnswerStore';
import { OnboardingWizard } from './onboarding/OnboardingWizard';

interface SidecarError {
  type: 'error';
  code: string;
  message: string;
  recoverable: boolean;
}

function MainLayout() {
  useWebSocket(); // sets up transcript + auto-answer IPC subscriptions
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [autoAnswerOn, setAutoAnswerOn] = useState(false);
  const [chatVisible, setChatVisible] = useState(true);
  const [suggestedVisible, setSuggestedVisible] = useState(true);
  const [compact, setCompact] = useState(false);
  const [transcriptVisible, setTranscriptVisible] = useState(true);
  // Separate from transcriptVisible: only hides the header bar (Transcript + Copy/Export),
  // not the transcript content.
  const [transcriptBarVisible, setTranscriptBarVisible] = useState(true);
  const [customTitlebar, setCustomTitlebar] = useState(false);
  const [splitPct, setSplitPct] = useState(60);
  const [opacityPct, setOpacityPct] = useState(100);
  const panelsRef = useRef<HTMLDivElement>(null);
  const splitRef = useRef(60); // latest divider position, readable from drag handlers
  const [errorBanner, setErrorBanner] = useState<SidecarError | null>(null);
  const [errorModal, setErrorModal] = useState<SidecarError | null>(null);

  useEffect(() => {
    const offError = window.electronAPI.onError((err) => {
      const e = err as SidecarError;
      if (e.recoverable) {
        setErrorBanner(e);
        setTimeout(() => setErrorBanner(null), 5000);
      } else {
        setErrorModal(e);
      }
    });

    return () => {
      offError();
    };
  }, []);

  // Theme / font-size reactivity from preferences
  useEffect(() => {
    window.electronAPI.getPreferences().then((p) => {
      document.documentElement.classList.toggle('dark', p.theme === 'dark');
      document.documentElement.classList.toggle('light', p.theme === 'light');
      document.documentElement.style.setProperty('--transcript-font-size', `${p.font_size}px`);
      setAutoAnswerOn(Boolean(p.auto_answer_enabled));
      const showBox = p.suggested_answer_visible !== false;
      setSuggestedVisible(showBox);
      useAutoAnswerStore.getState().setPanelVisible(showBox);
      setChatVisible(p.chat_panel_visible ?? true);
      setTranscriptVisible(p.transcript_visible !== false);
      setCustomTitlebar(Boolean(p.custom_titlebar));
      splitRef.current = p.transcript_split ?? 60;
      setSplitPct(splitRef.current);
      setOpacityPct(Math.round((p.window_opacity ?? 1) * 100));
      window.electronAPI.setOpacity(p.window_opacity ?? 1);
    });
  }, [settingsOpen]); // re-apply after settings close

  const changeOpacity = (pct: number) => {
    setOpacityPct(pct);
    const frac = pct / 100;
    window.electronAPI.setOpacity(frac);
    window.electronAPI.setPreferences({ window_opacity: frac });
  };

  const toggleChat = () => {
    const next = !chatVisible;
    setChatVisible(next);
    window.electronAPI.setPreferences({ chat_panel_visible: next });
    // Make room when the AI panel opens; closing it leaves the user's width alone.
    if (next) window.electronAPI.setWindowWidth(750);
  };

  const toggleTranscriptBar = () => {
    setTranscriptBarVisible((v) => !v);
  };

  const toggleSuggested = () => {
    const next = !suggestedVisible;
    setSuggestedVisible(next);
    useAutoAnswerStore.getState().setPanelVisible(next);
    window.electronAPI.setPreferences({ suggested_answer_visible: next });
  };

  const toggleCompact = () => {
    const next = !compact;
    setCompact(next);
    window.electronAPI.setCompact(next);
  };

  const toggleAutoAnswer = () => {
    const next = !autoAnswerOn;
    setAutoAnswerOn(next);
    window.electronAPI.setPreferences({ auto_answer_enabled: next });
  };

  const startDividerDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    const onMove = (ev: MouseEvent) => {
      const rect = panelsRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return;
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      splitRef.current = Math.min(80, Math.max(20, pct));
      setSplitPct(splitRef.current);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.electronAPI.setPreferences({ transcript_split: splitRef.current });
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-900 text-gray-100 overflow-hidden">
      {customTitlebar && <CustomTitleBar hideMaximize={compact} />}
      <TopBar
        onSettingsOpen={() => setSettingsOpen(true)}
        chatVisible={chatVisible}
        onToggleChat={toggleChat}
        transcriptBarVisible={transcriptBarVisible}
        onToggleTranscriptBar={toggleTranscriptBar}
        autoAnswerOn={autoAnswerOn}
        onToggleAutoAnswer={toggleAutoAnswer}
        suggestedVisible={suggestedVisible}
        onToggleSuggested={toggleSuggested}
        compact={compact}
        onToggleCompact={toggleCompact}
        customTitlebar={customTitlebar}
      />

      {/* Window opacity — always available, panel-independent */}
      <div className="flex items-center gap-2 px-4 py-1.5 bg-gray-900 border-b border-gray-800">
        <span className="text-[10px] text-gray-500 uppercase tracking-wide">Opacity</span>
        <input
          type="range"
          min={5}
          max={100}
          value={opacityPct}
          onChange={(e) => changeOpacity(Number(e.target.value))}
          className="flex-1 accent-blue-500"
        />
        <span className="text-xs text-gray-400 w-9 text-right">{opacityPct}%</span>
      </div>

      {/* Error banner (recoverable) */}
      {errorBanner && (
        <div className="bg-yellow-900/80 text-yellow-200 text-sm px-4 py-2 flex items-center justify-between">
          <span>{errorBanner.message}</span>
          <button onClick={() => setErrorBanner(null)} className="ml-4 text-yellow-400 hover:text-yellow-200">
            ×
          </button>
        </div>
      )}

      {/* Main panels — draggable split; each panel independently toggleable */}
      <div ref={panelsRef} className="flex-1 flex overflow-hidden">
        {transcriptVisible && (
          <div
            className="h-full overflow-hidden"
            style={{ width: chatVisible ? `${splitPct}%` : '100%' }}
          >
            <TranscriptPanel headerVisible={transcriptBarVisible} />
          </div>
        )}
        {transcriptVisible && chatVisible && (
          <div
            onMouseDown={startDividerDrag}
            title="Drag to resize"
            className="w-1.5 flex-shrink-0 cursor-col-resize bg-gray-700 hover:bg-blue-500 transition-colors"
          />
        )}
        {chatVisible && (
          <div className="h-full overflow-hidden flex-1">
            <AIChatPanel />
          </div>
        )}
      </div>

      {/* Auto-answer suggested-answer band */}
      {autoAnswerOn && suggestedVisible && <SuggestedAnswerPanel />}

      {/* Settings modal */}
      <Settings isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Error modal (non-recoverable) */}
      {errorModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-red-700 rounded-2xl shadow-2xl p-6 max-w-sm w-full">
            <h3 className="text-lg font-semibold text-red-400 mb-2">MeetingPal Error</h3>
            <p className="text-gray-300 text-sm mb-2">{errorModal.message}</p>
            <p className="text-gray-500 text-xs mb-4">Code: {errorModal.code}</p>
            <button
              onClick={() => setErrorModal(null)}
              className="w-full bg-gray-700 hover:bg-gray-600 text-white rounded-lg py-2 text-sm transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [onboardingDone, setOnboardingDone] = useState<boolean | null>(null);

  useEffect(() => {
    // hasApiKey() reads from Windows Credential Manager (always available).
    // getPreferences() requires the sidecar; if it's still starting up or
    // crashed, don't show the onboarding wizard — just trust the API key.
    Promise.all([
      window.electronAPI.hasApiKey(),
      window.electronAPI.getPreferences().catch(() => null),
    ]).then(([hasKey, prefs]) => {
      if (prefs === null) {
        // Sidecar not yet ready — if the key exists, assume onboarding is done
        // so the main layout mounts and retries preferences on its own.
        setOnboardingDone(Boolean(hasKey));
      } else {
        const p = prefs as { onboarding_completed: boolean };
        setOnboardingDone(Boolean(hasKey) && p.onboarding_completed);
      }
    }).catch(() => setOnboardingDone(false));
  }, []);

  if (onboardingDone === null) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950 text-gray-400 text-sm">
        Loading…
      </div>
    );
  }

  if (!onboardingDone) {
    return <OnboardingWizard onComplete={() => setOnboardingDone(true)} />;
  }

  return <MainLayout />;
}
