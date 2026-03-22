import { useEffect, useState } from "react";

interface ScreenshotViewerProps {
  src: string | null;
}

export function ScreenshotViewer({ src }: ScreenshotViewerProps) {
  const [visible, setVisible] = useState(true);

  // Fade transition on update
  useEffect(() => {
    setVisible(false);
    const t = setTimeout(() => setVisible(true), 80);
    return () => clearTimeout(t);
  }, [src]);

  if (!src) {
    return (
      <div className="flex items-center justify-center h-64 bg-slate-100 border-2 border-dashed border-slate-300">
        <p className="text-sm text-slate-400">Screenshot will appear here</p>
      </div>
    );
  }

  return (
    <div className="border-2 border-slate-200 overflow-hidden">
      <img
        src={src}
        alt="Agent screenshot"
        className={`w-full object-cover transition-opacity duration-150 ${visible ? "opacity-100" : "opacity-0"}`}
      />
    </div>
  );
}
