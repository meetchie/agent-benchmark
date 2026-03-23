interface URLInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: () => void;
  disabled?: boolean;
}

export function URLInput({ value, onChange, onSubmit, disabled }: URLInputProps) {
  const isValid =
    value === "" || value.startsWith("http://") || value.startsWith("https://");

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && onSubmit) {
      onSubmit();
    }
  };

  return (
    <div className="space-y-2">
      <p className="text-base text-slate-600 font-medium">
        Paste a website URL to generate benchmark tasks
      </p>
      <input
        type="url"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => onSubmit?.()}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder="https://your-site.com"
        className={`w-full rounded-none border-2 px-4 py-3 text-base outline-none transition-colors
          ${isValid ? "border-slate-300 focus:border-[#3c49ad]" : "border-red-600"}
          ${disabled ? "bg-slate-100 text-slate-400 cursor-not-allowed" : "bg-white text-slate-900"}
        `}
      />
      {!isValid && (
        <p className="text-xs text-red-600">URL must start with http:// or https://</p>
      )}
    </div>
  );
}
