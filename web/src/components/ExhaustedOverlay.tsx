import { useState, useEffect } from "react";
import { DemoModal } from "./DemoModal";

interface ExhaustedOverlayProps {
  resetsIn: number;
}

function formatCountdown(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function ExhaustedOverlay({ resetsIn }: ExhaustedOverlayProps) {
  const [remaining, setRemaining] = useState(resetsIn);

  useEffect(() => {
    setRemaining(resetsIn);
    const interval = setInterval(() => {
      setRemaining((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [resetsIn]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 modal-backdrop" />

      <div className="relative w-full max-w-[400px] bg-white border-2 border-slate-200 m-4 shadow-2xl p-8 text-center">
        <div className="text-lg font-bold text-slate-900 mb-1">You've used all your runs</div>
        <div className="text-sm text-slate-500 mb-2">Your runs reset in</div>
        <div className="text-3xl font-bold text-[#3c49ad] font-mono my-4">{formatCountdown(remaining)}</div>
        <div className="flex gap-2 mt-6">
          <a
            href="https://rindler.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 border-2 border-[#3c49ad] bg-white text-[#3c49ad] py-2.5 text-sm font-semibold text-center hover:bg-[#3c49ad] hover:text-white transition-all"
          >
            Learn More
          </a>
          <DemoModal>
            <button className="flex-1 border-2 border-transparent bg-[#3c49ad] text-white py-2.5 text-sm font-semibold text-center hover:bg-[#5563c9] transition-all">
              Book a Demo
            </button>
          </DemoModal>
        </div>
      </div>
    </div>
  );
}
