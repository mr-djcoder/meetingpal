import { useState } from 'react';
import { ApiKeyStep } from './steps/ApiKeyStep';
import { AudioSetupStep } from './steps/AudioSetupStep';
import { AudioTestStep } from './steps/AudioTestStep';
import { DemoStep } from './steps/DemoStep';
import { ReadyStep } from './steps/ReadyStep';

interface Props {
  onComplete: () => void;
}

const STEP_LABELS = ['API Key', 'Audio Setup', 'Audio Test', 'Demo', 'Ready'];

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);

  const next = () => setStep((s) => Math.min(s + 1, 5) as 1 | 2 | 3 | 4 | 5);
  const back = () => setStep((s) => Math.max(s - 1, 1) as 1 | 2 | 3 | 4 | 5);

  return (
    <div className="fixed inset-0 bg-gray-950 flex items-center justify-center p-4 z-50">
      <div className="w-full max-w-md bg-gray-900 rounded-2xl shadow-2xl border border-gray-700 p-8">
        {/* Logo */}
        <div className="flex items-center gap-2 mb-6">
          <div className="w-8 h-8 bg-blue-500 rounded-xl flex items-center justify-center text-white font-bold">
            M
          </div>
          <span className="font-bold text-white">MeetingPal</span>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-1 mb-8">
          {STEP_LABELS.map((label, i) => {
            const stepNum = i + 1;
            const isActive = stepNum === step;
            const isComplete = stepNum < step;
            return (
              <div key={label} className="flex items-center flex-1">
                <div
                  className={`w-full h-1 rounded-full ${
                    isComplete ? 'bg-blue-500' : isActive ? 'bg-blue-500/50' : 'bg-gray-700'
                  }`}
                />
              </div>
            );
          })}
        </div>

        {/* Step content */}
        <div>
          {step === 1 && <ApiKeyStep onNext={next} />}
          {step === 2 && <AudioSetupStep onNext={next} onBack={back} />}
          {step === 3 && <AudioTestStep onNext={next} onBack={back} />}
          {step === 4 && <DemoStep onNext={next} onBack={back} />}
          {step === 5 && <ReadyStep onComplete={onComplete} onBack={back} />}
        </div>

        {/* Step label */}
        <p className="text-center text-xs text-gray-600 mt-6">
          Step {step} of 5 — {STEP_LABELS[step - 1]}
        </p>
      </div>
    </div>
  );
}
