import { useEffect, useState } from "react";
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
  onRegenerateTasks: () => void;
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
  onRegenerateTasks,
}: SetupViewProps) {
  const hasContent = tasks.length > 0 || tasksLoading || tasksError;

  // Delay showing tasks so the fade-in triggers after mount
  const [tasksVisible, setTasksVisible] = useState(false);
  useEffect(() => {
    if (tasks.length > 0 && !tasksLoading) {
      const t = setTimeout(() => setTasksVisible(true), 50);
      return () => clearTimeout(t);
    }
    setTasksVisible(false);
  }, [tasks.length, tasksLoading]);

  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col">
      <BenchmarkHeader />

      <div
        className="flex-1 flex flex-col items-center px-6 transition-all duration-500 ease-in-out"
        style={{ paddingTop: hasContent ? "48px" : "30vh" }}
      >
        <div className="w-full max-w-[480px]">
          {/* Subtitle — fades out */}
          <div
            className="text-center mb-6 transition-all duration-300 ease-in-out"
            style={{
              opacity: hasContent ? 0 : 1,
              maxHeight: hasContent ? 0 : "40px",
              overflow: "hidden",
            }}
          >
            <p className="text-sm text-slate-400">
              Paste a URL to generate benchmark tasks
            </p>
          </div>

          {/* URL input */}
          <URLInput
            value={url}
            onChange={onUrlChange}
            onSubmit={onUrlSubmit}
            disabled={runStatus === "running"}
          />

          {/* Loading indicator — below URL */}
          <div
            className="flex items-center justify-center gap-2 transition-all duration-300"
            style={{
              opacity: tasksLoading ? 1 : 0,
              maxHeight: tasksLoading ? "40px" : 0,
              marginTop: tasksLoading ? "16px" : 0,
              overflow: "hidden",
            }}
          >
            <svg
              className="animate-spin h-4 w-4 text-[#3c49ad]"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-xs text-slate-400">Generating tasks...</span>
          </div>

          {/* Tasks section — fades in */}
          <div
            className="transition-all duration-500 ease-in-out"
            style={{
              opacity: tasksVisible ? 1 : 0,
              transform: tasksVisible ? "translateY(0)" : "translateY(12px)",
              maxHeight: tasksVisible ? "600px" : 0,
              overflow: "hidden",
              marginTop: tasksVisible ? "24px" : 0,
            }}
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Task
                </label>
                {tasks.length > 0 && (
                  <button
                    onClick={onRegenerateTasks}
                    className="text-xs text-[#3c49ad] hover:text-[#2f3a8a] flex items-center gap-1"
                  >
                    <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Redo Tasks
                  </button>
                )}
              </div>

              {tasksError && (
                <div className="border-2 border-amber-300 bg-amber-50 px-4 py-3">
                  <p className="text-sm text-amber-700">{tasksError}</p>
                </div>
              )}

              {tasks.length > 0 && (
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

            {tasks.length > 0 && (
              <div className="mt-6">
                <RunButton status={runStatus} disabled={!canRun} onClick={onRun} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
