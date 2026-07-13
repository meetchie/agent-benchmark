import { useEffect, useState, useCallback } from "react";
import Cal, { getCalApi } from "@calcom/embed-react";

const CAL_LINK = "example/demo";

const ua = typeof window !== "undefined" ? navigator.userAgent : "";
const isSafari = () => /^((?!chrome|android).)*safari/i.test(ua);
const isFirefox = () => /firefox/i.test(ua);

let calInitialized = false;

interface DemoModalProps {
  children: React.ReactNode;
}

export function DemoModal({ children }: DemoModalProps) {
  const [open, setOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (calInitialized) return;
    calInitialized = true;
    (async function () {
      const cal = await getCalApi();
      cal("ui", {
        theme: "light",
        layout: "month_view",
        styles: {
          branding: { brandColor: "#3c49ad" },
        },
        cssVarsPerTheme: {
          light: { "cal-brand": "#3c49ad" },
          dark: { "cal-brand": "#3c49ad" },
        },
        hideEventTypeDetails: false,
      });
      cal("on", {
        action: "linkReady",
        callback: () => setIsLoading(false),
      });
    })();
  }, []);

  // Fallback: hide spinner after 5s in case linkReady doesn't fire
  useEffect(() => {
    if (!isLoading) return;
    const fallback = setTimeout(() => setIsLoading(false), 5000);
    return () => clearTimeout(fallback);
  }, [isLoading]);

  const handleOpen = useCallback(() => {
    setIsLoading(true);
    setOpen(true);
  }, []);

  const handleClose = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, handleClose]);

  return (
    <>
      <span onClick={handleOpen} className="contents">{children}</span>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 modal-backdrop" onClick={handleClose} />

          <div className="relative w-[95vw] max-w-4xl max-h-[90vh] bg-white border-2 border-slate-200 shadow-2xl flex flex-col">
            {/* Close button row */}
            <div className="flex shrink-0 items-center justify-end px-4 pt-4 pb-2">
              <button
                onClick={handleClose}
                className="p-2 text-slate-400 hover:text-slate-600 transition-colors"
                aria-label="Close"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className={[
              "relative w-full max-h-[85vh] overflow-y-auto px-6 pb-4 transform-gpu will-change-transform",
              // Safari's wide-canvas workaround for Cal is desktop-only; on mobile the
              // forced 1120px width pushed the calendar off-screen (swipe required).
              isSafari() ? "lg:overflow-x-auto" : "",
              isFirefox() ? "overflow-hidden" : "",
            ].join(" ")}>
              {isLoading && (
                <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/90">
                  <svg className="animate-spin h-10 w-10 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                </div>
              )}
              <div className={[
                "w-full",
                isSafari() ? "lg:min-w-[1120px]" : "",
                isFirefox() ? "[&_iframe]:bg-white [&_iframe]:border-0" : "",
              ].join(" ")}>
                <Cal
                  calLink={CAL_LINK}
                  style={isFirefox() ? { overflow: "hidden", background: "white" } : undefined}
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
