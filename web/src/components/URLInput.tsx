interface URLInputProps {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}

export function URLInput({ value, onChange, disabled }: URLInputProps) {
  const isValid =
    value === "" || value.startsWith("http://") || value.startsWith("https://");

  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        Website URL
      </label>
      <input
        type="url"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="https://your-site.com"
        className={`w-full rounded-none border-2 px-3 py-2 text-sm outline-none transition-colors
          ${isValid ? "border-slate-300 focus:border-[#3c49ad]" : "border-red-400"}
          ${disabled ? "bg-slate-100 text-slate-400 cursor-not-allowed" : "bg-white text-slate-900"}
        `}
      />
      {!isValid && (
        <p className="text-xs text-red-500">URL must start with http:// or https://</p>
      )}
    </div>
  );
}
