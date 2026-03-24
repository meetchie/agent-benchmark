import { SignedIn, SignedOut, UserButton } from "@clerk/clerk-react";

interface BenchmarkHeaderProps {
  onSignInClick?: () => void;
}

export function BenchmarkHeader({ onSignInClick }: BenchmarkHeaderProps) {
  return (
    <header className="bg-white border-b border-slate-200 px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 sm:gap-3 min-w-0 shrink-0">
        <a href="/" className="flex items-center gap-2 sm:gap-2.5 shrink-0">
          <img src="/rindler-logo.png" alt="Rindler" className="h-7 sm:h-9 w-auto" />
          <span className="text-base sm:text-lg font-semibold text-slate-900">Rindler</span>
        </a>
        <span className="text-slate-400 font-light shrink-0">|</span>
        <span className="text-xs sm:text-sm font-medium text-[#3c49ad] shrink-0">Benchmark</span>
      </div>

      <div className="flex items-center gap-3 sm:gap-6 shrink-0">
        <SignedIn>
          <UserButton afterSignOutUrl="/" />
        </SignedIn>
        <SignedOut>
          {onSignInClick && (
            <button
              onClick={onSignInClick}
              className="text-xs sm:text-sm font-medium text-slate-700 hover:text-slate-900 whitespace-nowrap"
            >
              Sign in
            </button>
          )}
        </SignedOut>
        <a
          href="https://rindler.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs sm:text-sm font-semibold text-[#3c49ad] border-2 border-[#3c49ad] px-3 sm:px-5 py-1 sm:py-1.5 hover:bg-[#3c49ad] hover:text-white transition-colors whitespace-nowrap"
        >
          Learn More
        </a>
      </div>
    </header>
  );
}
