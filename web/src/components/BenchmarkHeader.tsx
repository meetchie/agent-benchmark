import { SignedIn, SignedOut, UserButton } from "@clerk/clerk-react";

interface BenchmarkHeaderProps {
  onSignInClick?: () => void;
}

export function BenchmarkHeader({ onSignInClick }: BenchmarkHeaderProps) {
  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <a href="https://rindlerapp.com" className="flex items-center gap-2.5">
          <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
          <span className="text-lg font-semibold text-slate-900">Rindler</span>
        </a>
        <span className="text-slate-400 font-light">|</span>
        <span className="text-sm font-medium text-[#3c49ad]">Benchmark</span>
      </div>

      <div className="flex items-center gap-6">
        <SignedIn>
          <UserButton afterSignOutUrl="/" />
        </SignedIn>
        <SignedOut>
          {onSignInClick && (
            <button
              onClick={onSignInClick}
              className="text-sm font-medium text-slate-700 hover:text-slate-900"
            >
              Sign in
            </button>
          )}
        </SignedOut>
        <a
          href="https://rindler.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-medium text-slate-900 border-2 border-slate-900 px-5 py-1.5 hover:bg-slate-900 hover:text-white transition-colors"
        >
          Main Site
        </a>
      </div>
    </header>
  );
}
