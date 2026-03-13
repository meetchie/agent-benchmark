import { useState, useEffect, useRef, useCallback } from "react";
import tasksData from "../tasks.yaml";
import { startBenchmark, pollStatus } from "./lib/api";
import type { Category, Task, StepRecord, RunStatus, SummaryData } from "./lib/types";

import { BenchmarkHeader } from "./components/BenchmarkHeader";
import { URLInput } from "./components/URLInput";
import { CategorySelector } from "./components/CategorySelector";
import { TaskCard } from "./components/TaskCard";
import { RunButton } from "./components/RunButton";
import { ScreenshotViewer } from "./components/ScreenshotViewer";
import { StepLog } from "./components/StepLog";
import { SummaryCard } from "./components/SummaryCard";

const CATEGORIES: Category[] = tasksData.categories;
const MAX_POLLS = 180;
const POLL_INTERVAL_MS = 1000;

export default function App() {
  const [url, setUrl] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [steps, setSteps] = useState<StepRecord[]>([]);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const retriesRef = useRef(0);

  const selectedCategory = CATEGORIES.find((c) => c.id === categoryId) ?? null;
  const selectedTask = selectedCategory?.tasks.find((t) => t.id === taskId) ?? null;

  const isUrlValid = url.startsWith("http://") || url.startsWith("https://");
  const canRun = isUrlValid && selectedTask !== null && runStatus !== "running";

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (runId: string) => {
      pollCountRef.current = 0;
      retriesRef.current = 0;

      pollRef.current = setInterval(async () => {
        pollCountRef.current++;

        if (pollCountRef.current > MAX_POLLS) {
          stopPolling();
          setRunStatus("error");
          setErrorMsg("Timed out after 3 minutes.");
          return;
        }

        try {
          const data = await pollStatus(runId);

          if (data.status === "error") {
            stopPolling();
            setRunStatus("error");
            setErrorMsg(data.message);
            return;
          }

          setSteps(data.steps);

          const latest = data.steps[data.steps.length - 1];
          if (latest?.screenshot_b64) {
            setScreenshot(latest.screenshot_b64);
          }

          if (data.status === "complete") {
            stopPolling();
            setRunStatus("complete");
            setSummary({
              success: data.success,
              summary: data.summary,
              total_ms: data.total_ms,
            });
          }

          retriesRef.current = 0;
        } catch {
          retriesRef.current++;
          if (retriesRef.current >= 3) {
            stopPolling();
            setRunStatus("error");
            setErrorMsg("Lost connection to server.");
          }
        }
      }, POLL_INTERVAL_MS);
    },
    [stopPolling]
  );

  const handleRun = useCallback(async () => {
    if (!canRun || !selectedTask) return;

    setRunStatus("running");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);

    try {
      const { run_id } = await startBenchmark(url, selectedTask.goal);
      startPolling(run_id);
    } catch (e) {
      setRunStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Failed to start benchmark.");
    }
  }, [canRun, selectedTask, url, startPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const isRunning = runStatus === "running";

  return (
    <div className="min-h-screen bg-[#f0f4ff] flex flex-col">
      <BenchmarkHeader />

      <div className="flex flex-1 overflow-hidden">
        {/* LEFT PANEL */}
        <div className="w-[40%] min-w-[300px] border-r border-slate-200 bg-white flex flex-col overflow-y-auto">
          <div className="p-6 space-y-6 flex-1">
            <URLInput value={url} onChange={setUrl} disabled={isRunning} />

            <CategorySelector
              categories={CATEGORIES}
              selected={categoryId}
              onSelect={(id) => {
                setCategoryId(id);
                setTaskId(null);
              }}
              disabled={isRunning}
            />

            {selectedCategory && (
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Task
                </label>
                <div className="space-y-2">
                  {selectedCategory.tasks.map((task: Task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      selected={taskId === task.id}
                      onSelect={() => setTaskId(task.id)}
                      disabled={isRunning}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="p-6 border-t border-slate-100">
            <RunButton status={runStatus} disabled={!canRun} onClick={handleRun} />
          </div>
        </div>

        {/* RIGHT PANEL */}
        <div className="flex-1 flex flex-col overflow-y-auto p-6 space-y-4">
          {summary && <SummaryCard data={summary} />}

          {runStatus === "error" && errorMsg && (
            <div className="border-2 border-red-300 bg-red-50 px-4 py-3">
              <p className="text-sm text-red-700">{errorMsg}</p>
            </div>
          )}

          {runStatus === "idle" && (
            <div className="flex-1 flex flex-col items-center justify-center text-center py-24">
              <div className="w-16 h-16 rounded-full bg-[#3c49ad]/10 flex items-center justify-center mb-4">
                <svg className="w-8 h-8 text-[#3c49ad]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-slate-700">
                Enter a URL, select a category and task, then hit Run.
              </p>
              <p className="mt-1 text-xs text-slate-400">
                The agent's browser will appear here in real time.
              </p>
            </div>
          )}

          {runStatus !== "idle" && (
            <>
              <ScreenshotViewer src={screenshot} />
              <StepLog steps={steps} isRunning={isRunning} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
