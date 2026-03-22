import type { Task } from "../lib/types";

interface TaskCardProps {
  task: Task;
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}

export function TaskCard({ task, selected, onSelect, disabled }: TaskCardProps) {
  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      className={`w-full text-left rounded-none border-2 p-4 transition-all
        ${
          selected
            ? "border-[#3c49ad] bg-[#f0f4ff]"
            : "border-slate-200 bg-white hover:border-[#3c49ad]/50"
        }
        ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}
      `}
    >
      <p className={`text-base font-semibold ${selected ? "text-[#3c49ad]" : "text-slate-800"}`}>
        {task.label}
      </p>
      <p className="mt-1 text-sm text-slate-500 line-clamp-2 leading-relaxed">
        {task.goal.split("\n")[0]}
      </p>
    </button>
  );
}
