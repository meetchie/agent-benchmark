import type { Task, RunStatus } from "../lib/types";
import { BenchmarkHeader } from "./BenchmarkHeader";
import { URLInput } from "./URLInput";
import { TaskCard } from "./TaskCard";
import { RunButton } from "./RunButton";

interface SetupViewProps {
  url: string;
  onUrlChange: (v: string) => void;
  onUrlSubmit: () => void;
  tasks: Task[];
  tasksLoading: boolean;
  tasksError: string | null;
  taskId: string | null;
  onTaskSelect: (id: string) => void;
  runStatus: RunStatus;
  canRun: boolean;
  onRun: () => void;
}

export function SetupView({
  url,
  onUrlChange,
  onUrlSubmit,
  tasks,
  tasksLoading,
  tasksError,
  taskId,
  onTaskSelect,
  runStatus,
  canRun,
  onRun,
}: SetupViewProps) {
  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col">
      <BenchmarkHeader />

      <div className="flex-1 flex items-start justify-center pt-12 px-6">
        <div className="w-full max-w-[480px] space-y-6">
          <div className="text-center">
            <p className="text-sm text-slate-400">
              Paste a URL to generate benchmark tasks
            </p>
          </div>

          <URLInput
            value={url}
            onChange={onUrlChange}
            onSubmit={onUrlSubmit}
            disabled={runStatus === "running"}
          />

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Task
            </label>

            {tasksLoading && (
              <div className="flex items-center gap-2 py-4 justify-center">
                <svg
                  className="animate-spin h-4 w-4 text-[#3c49ad]"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                <span className="text-sm text-slate-400">Analyzing website...</span>
              </div>
            )}

            {tasksError && (
              <div className="border-2 border-amber-300 bg-amber-50 px-4 py-3">
                <p className="text-sm text-amber-700">{tasksError}</p>
              </div>
            )}

            {!tasksLoading && !tasksError && tasks.length === 0 && (
              <p className="text-sm text-slate-400 text-center py-2">
                Enter a URL above to generate tasks.
              </p>
            )}

            {!tasksLoading && tasks.length > 0 && (
              <div className="space-y-2">
                {tasks.map((task: Task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    selected={taskId === task.id}
                    onSelect={() => onTaskSelect(task.id)}
                    disabled={runStatus === "running"}
                  />
                ))}
              </div>
            )}
          </div>

          <RunButton status={runStatus} disabled={!canRun} onClick={onRun} />
        </div>
      </div>
    </div>
  );
}
