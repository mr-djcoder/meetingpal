import { useEffect, useRef, useState } from 'react';
import { AIChatPanel } from './components/AIChatPanel';
import { CustomTitleBar } from './components/CustomTitleBar';
import { Settings } from './components/Settings';
import { SuggestedAnswerPanel } from './components/SuggestedAnswerPanel';
import { TopBar } from './components/TopBar';
import { TranscriptPanel } from './components/TranscriptPanel';
import { useWebSocket } from './hooks/useWebSocket';
import { OnboardingWizard } from './onboarding/OnboardingWizard';

interface SidecarError {
  type: 'error';
  code: string;
  message: string;
  recoverable: boolean;
}

interface ModelDownloadProgress {
  type: 'model_download_progress';
  percent: number;
}

function MainLayout() {
  useWebSocket(); // sets up transcript + auto-answer IPC subscriptions
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [autoAnswerOn, setAutoAnswerOn] = useState(false);
  const [chatVisible, setChatVisible] = useState(true);
  const [customTitlebar, setCustomTitlebar] = useState(false);
  const [splitPct, setSplitPct] = useState(60);
  const panelsRef = useRef<HTMLDivElement>(null);
  const [errorBanner, setErrorBanner] = useState<SidecarError | null>(null);
  const [errorModal, setErrorModal] = useState<SidecarError | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);

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

    // Model download progress
    const offProgress = (window as unknown as { electronAPI: { onModelDownloadProgress?: (cb: (p: unknown) => void) => () => void } }).electronAPI.onModelDownloadProgress;
    let offDl: (() => void) | undefined;
    if (offProgress) {
      offDl = offProgress((p) => {
        const progress = p as ModelDownloadProgress;
        setDownloadProgress(progress.percent);
        if (progress.percent >= 1) {
          setTimeout(() => setDownloadProgress(null), 1000);
        }
      });
    }

    return () => {
      offError();
      offDl?.();
    };
  }, []);

  // Theme / font-size reactivity from preferences
  useEffect(() => {
    window.electronAPI.getPreferences().then((prefs) => {
      const p = prefs as { theme: string; font_size: number };
      document.documentElement.classList.toggle('dark', p.theme === 'dark');
      document.documentElement.classList.toggle('light', p.theme === 'light');
      document.documentElement.style.setProperty('--transcript-font-size', `${p.font_size}px`);
      const aa = prefs as unknown as {
        auto_answer_enabled?: boolean;
        chat_panel_visible?: boolean;
        custom_titlebar?: boolean;
        window_opacity?: number;
        transcript_split?: number;
      };
      setAutoAnswerOn(Boolean(aa.auto_answer_enabled));
      setChatVisible(aa.chat_panel_visible ?? true);
      setCustomTitlebar(Boolean(aa.custom_titlebar));
      setSplitPct(aa.transcript_split ?? 60);
      window.electronAPI.setOpacity(aa.window_opacity ?? 1);
    });
  }, [settingsOpen]); // re-apply after settings close

  const toggleChat = () => {
    const next = !chatVisible;
    setChatVisible(next);
    window.electronAPI.setPreferences({ chat_panel_visible: next } as never);
  };

  const startDividerDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    const onMove = (ev: MouseEvent) => {
      const rect = panelsRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return;
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      setSplitPct(Math.min(80, Math.max(20, pct)));
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      setSplitPct((p) => {
        window.electronAPI.setPreferences({ transcript_split: p } as never);
        return p;
      });
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-900 text-gray-100 overflow-hidden">
      {customTitlebar && <CustomTitleBar />}
      <TopBar
        onSettingsOpen={() => setSettingsOpen(true)}
        chatVisible={chatVisible}
        onToggleChat={toggleChat}
        customTitlebar={customTitlebar}
      />

      {/* Error banner (recoverable) */}
      {errorBanner && (
        <div className="bg-yellow-900/80 text-yellow-200 text-sm px-4 py-2 flex items-center justify-between">
          <span>{errorBanner.message}</span>
          <button onClick={() => setErrorBanner(null)} className="ml-4 text-yellow-400 hover:text-yellow-200">
            ×
          </button>
        </div>
      )}

      {/* Model download progress */}
      {downloadProgress !== null && (
        <div className="bg-blue-900/80 text-blue-200 text-sm px-4 py-2">
          <div className="flex items-center gap-3">
            <span>Downloading Whisper model… {Math.round(downloadProgress * 100)}%</span>
            <div className="flex-1 h-1.5 bg-blue-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-400 rounded-full transition-all"
                style={{ width: `${downloadProgress * 100}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Main panels — draggable split */}
      <div ref={panelsRef} className="flex-1 flex overflow-hidden">
        <div
          className="h-full overflow-hidden"
          style={{ width: chatVisible ? `${splitPct}%` : '100%' }}
        >
          <TranscriptPanel />
        </div>
        {chatVisible && (
          <>
            <div
              onMouseDown={startDividerDrag}
              title="Drag to resize"
              className="w-1.5 flex-shrink-0 cursor-col-resize bg-gray-700 hover:bg-blue-500 transition-colors"
            />
            <div className="h-full overflow-hidden flex-1">
              <AIChatPanel />
            </div>
          </>
        )}
      </div>

      {/* Auto-answer suggested-answer band */}
      {autoAnswerOn && <SuggestedAnswerPanel />}

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
    Promise.all([
      window.electronAPI.hasApiKey(),
      window.electronAPI.getPreferences(),
    ]).then(([hasKey, prefs]) => {
      const p = prefs as { onboarding_completed: boolean };
      setOnboardingDone(hasKey && p.onboarding_completed);
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
