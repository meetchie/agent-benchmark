import type { Category } from "../lib/types";

interface CategorySelectorProps {
  categories: Category[];
  selected: string | null;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

export function CategorySelector({
  categories,
  selected,
  onSelect,
  disabled,
}: CategorySelectorProps) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        Category
      </label>
      <div className="flex flex-wrap gap-2">
        {categories.map((cat) => (
          <button
            key={cat.id}
            onClick={() => onSelect(cat.id)}
            disabled={disabled}
            className={`rounded-full border-2 px-4 py-1.5 text-sm font-medium transition-all
              ${
                selected === cat.id
                  ? "border-[#3c49ad] bg-[#3c49ad] text-white"
                  : "border-slate-300 bg-white text-slate-700 hover:border-[#3c49ad] hover:text-[#3c49ad]"
              }
              ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}
            `}
          >
            {cat.label}
          </button>
        ))}
      </div>
    </div>
  );
}
