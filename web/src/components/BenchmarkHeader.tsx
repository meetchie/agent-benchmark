export function BenchmarkHeader() {
  return (
    <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-3">
      <a href="https://rindlerapp.com" className="flex items-center gap-2.5">
        <img src="/rindler-logo.png" alt="Rindler" className="h-9 w-auto" />
        <span className="text-lg font-semibold text-slate-900">Rindler</span>
      </a>
      <span className="text-slate-400 font-light">|</span>
      <span className="text-sm font-medium text-[#3c49ad]">Benchmark</span>
    </header>
  );
}
