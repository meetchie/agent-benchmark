interface DemoBannerProps {
  className?: string;
}

/**
 * Slim, persistent strip shown on every screen of a demo-mode backend, so a
 * canned run is never mistaken for a real one (see App: Health.demo_mode).
 */
export function DemoBanner({ className = "" }: DemoBannerProps) {
  return (
    <div
      role="status"
      data-testid="demo-banner"
      className={`shrink-0 w-full bg-amber-100 border-b border-amber-300 px-4 py-1.5 text-center text-xs font-medium text-amber-900 ${className}`}
    >
      <strong className="font-semibold">Demo mode:</strong> canned runs, no real agent or API calls
    </div>
  );
}
