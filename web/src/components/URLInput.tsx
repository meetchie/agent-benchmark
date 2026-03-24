interface URLInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  onStop?: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export function URLInput({ value, onChange, onSubmit, onStop, loading, disabled }: URLInputProps) {
  const isValid =
    value === "" || value.startsWith("http://") || value.startsWith("https://");
  const canSubmit = value.startsWith("http://") || value.startsWith("https://");

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      if (loading && onStop) {
        onStop();
      } else if (onSubmit && canSubmit) {
        onSubmit();
      }
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-base text-slate-600 font-medium">
        Paste a website URL to generate benchmark tasks
      </p>
      <div className="relative">
        <input
          type="url"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => { if (!loading) onSubmit?.(); }}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="https://your-site.com"
          className={`w-full rounded-none border-2 px-4 py-3 pr-12 text-base outline-none transition-colors
            ${isValid ? "border-slate-300 focus:border-[#3c49ad]" : "border-red-600"}
            ${disabled ? "bg-slate-100 text-slate-400 cursor-not-allowed" : "bg-white text-slate-900"}
          `}
        />
        {/* Send / Stop button */}
        {loading ? (
          <button
            onClick={onStop}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 flex items-center justify-center rounded-full bg-slate-900 hover:bg-slate-700 transition-colors"
            title="Stop generating"
          >
            <svg className="w-3 h-3 text-white" viewBox="0 0 12 12" fill="currentColor">
              <rect width="12" height="12" rx="1" />
            </svg>
          </button>
        ) : canSubmit ? (
          <button
            onClick={onSubmit}
            disabled={disabled}
            className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 flex items-center justify-center rounded-full bg-[#3c49ad] hover:bg-[#2f3a8a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="Generate tasks"
          >
            <svg className="w-4 h-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </button>
        ) : null}
      </div>
      {!isValid && (
        <p className="text-xs text-red-600">URL must start with http:// or https://</p>
      )}
    </div>
  );
}
