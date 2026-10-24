import { useEffect, useState, useRef } from "react";
import type { Task, RunStatus } from "../lib/types";
import { BenchmarkHeader } from "./BenchmarkHeader";
import { BackgroundGrid } from "./BackgroundGrid";
import { URLInput } from "./URLInput";
import { TaskCard } from "./TaskCard";
import { RunButton } from "./RunButton";
import { runsRemainingLabel } from "../lib/utils";

interface SetupViewProps {
  url: string;
  onUrlChange: (v: string) => void;
  onUrlSubmit: () => void;
  onStopGenerate: () => void;
  tasks: Task[];
  tasksLoading: boolean;
  tasksError: string | null;
  taskId: string | null;
  onTaskSelect: (id: string) => void;
  runStatus: RunStatus;
  canRun: boolean;
  onRun: () => void;
  onRegenerateTasks: () => void;
  onSignInClick?: () => void;
  remainingRuns?: number;
  runLimit?: number;
  resetsIn?: number;
}

export function SetupView({
  url,
  onUrlChange,
  onUrlSubmit,
  onStopGenerate,
  tasks,
  tasksLoading,
  tasksError,
  taskId,
  onTaskSelect,
  runStatus,
  canRun,
  onRun,
  onRegenerateTasks,
  onSignInClick,
  remainingRuns,
  runLimit,
  resetsIn,
}: SetupViewProps) {
  const hasShifted = useRef(false);
  if (tasks.length > 0 || tasksLoading) {
    hasShifted.current = true;
  }
  const shifted = hasShifted.current;
  const exhausted = remainingRuns !== undefined && remainingRuns <= 0;

  const [tasksVisible, setTasksVisible] = useState(false);
  useEffect(() => {
    if (tasks.length > 0 && !tasksLoading) {
      const t = setTimeout(() => setTasksVisible(true), 50);
      return () => clearTimeout(t);
    }
    setTasksVisible(false);
  }, [tasks.length, tasksLoading]);

  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col overflow-x-hidden">
      <BenchmarkHeader onSignInClick={onSignInClick} />

      <div
        className="flex-1 flex flex-col items-center px-6 transition-all duration-500 ease-in-out relative"
        style={{ paddingTop: shifted ? "15vh" : "35vh" }}
      >
        <BackgroundGrid />
        <div className="w-full max-w-[560px] relative z-10">
          <URLInput
            value={url}
            onChange={onUrlChange}
            onSubmit={exhausted ? undefined : onUrlSubmit}
            onStop={onStopGenerate}
            loading={tasksLoading}
            disabled={runStatus === "running" || exhausted}
          />

          {remainingRuns !== undefined && (
            <p
              className="text-xs text-slate-400 mt-2 transition-all duration-300"
              style={{
                opacity: remainingRuns > 0 && !exhausted && tasks.length === 0 && !tasksLoading ? 1 : 0,
                maxHeight: remainingRuns > 0 && !exhausted && tasks.length === 0 && !tasksLoading ? "20px" : "0",
                overflow: "hidden",
              }}
            >
              <strong className="text-[#3c49ad]">{remainingRuns}</strong> {remainingRuns === 1 ? "run" : "runs"} remaining
            </p>
          )}
          {exhausted && resetsIn !== undefined && resetsIn > 0 && (
            <p className="text-xs text-red-500 font-semibold mt-1">
              No runs remaining. Resets in {Math.floor(resetsIn / 3600)}h {Math.floor((resetsIn % 3600) / 60)}m
            </p>
          )}

          <div
            className="flex items-center gap-2 transition-all duration-300"
            style={{
              opacity: tasksLoading ? 1 : 0,
              maxHeight: tasksLoading ? "40px" : 0,
              marginTop: tasksLoading ? "16px" : 0,
              overflow: "hidden",
            }}
          >
            <svg className="animate-spin h-4 w-4 text-[#3c49ad]" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm text-slate-400">Generating tasks...</span>
          </div>

          {tasksError && !tasksLoading && (
            <div className="border-2 border-amber-600 bg-amber-50 px-4 py-3 mt-4">
              <p className="text-sm text-amber-600">{tasksError}</p>
            </div>
          )}

          <div
            className="transition-all duration-500 ease-in-out"
            style={{
              opacity: tasksVisible ? 1 : 0,
              transform: tasksVisible ? "translateY(0)" : "translateY(12px)",
              maxHeight: tasksVisible ? "800px" : 0,
              overflow: "hidden",
              marginTop: tasksVisible ? "28px" : 0,
            }}
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Task</label>
                {tasks.length > 0 && (
                  <button onClick={onRegenerateTasks} className="text-sm text-[#3c49ad] hover:text-[#2f3a8a] flex items-center gap-1">
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Redo Tasks
                  </button>
                )}
              </div>
              {tasks.length > 0 && (
                <div className="space-y-3">
                  {tasks.map((task: Task) => (
                    <TaskCard key={task.id} task={task} selected={taskId === task.id} onSelect={() => onTaskSelect(task.id)} disabled={runStatus === "running"} />
                  ))}
                </div>
              )}
            </div>
            {tasks.length > 0 && (
              <div className="mt-8">
                <RunButton status={runStatus} disabled={!canRun || (remainingRuns !== undefined && remainingRuns <= 0)} onClick={onRun} />
                {remainingRuns !== undefined && remainingRuns > 0 && (
                  <p className="text-xs text-slate-500 text-center mt-3">
                    {remainingRuns === 1 && (
                      <svg className="inline w-3.5 h-3.5 text-amber-500 mr-1 -mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                      </svg>
                    )}
                    <strong className="text-[#3c49ad]">{remainingRuns}</strong> {runsRemainingLabel(remainingRuns, runLimit)}
                  </p>
                )}
                {remainingRuns !== undefined && remainingRuns <= 0 && resetsIn !== undefined && resetsIn > 0 && (
                  <p className="text-xs text-red-500 font-semibold text-center mt-3">
                    No runs remaining. Resets in {Math.floor(resetsIn / 3600)}h {Math.floor((resetsIn % 3600) / 60)}m
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
