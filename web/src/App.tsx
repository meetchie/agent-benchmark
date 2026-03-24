import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth, AuthenticateWithRedirectCallback } from "@clerk/clerk-react";
import { startBenchmark, pollStatus, generateTasks, cancelBenchmark } from "./lib/api";
import type { Task, StepRecord, RunStatus, SummaryData } from "./lib/types";

import { SignInModal } from "./components/SignInPage";
import { SetupView } from "./components/SetupView";
import { RunningView } from "./components/RunningView";

type View = "setup" | "running";

const MAX_POLLS = 300; // 5 min — backend handles 3-min agent timeout + judge
const POLL_INTERVAL_MS = 1000;

export default function App() {
  const { isSignedIn, getToken } = useAuth();

  const [view, setView] = useState<View>("setup");

  // Persist URL, tasks, and selection in sessionStorage so they survive sign-in
  const [url, setUrl] = useState(() => sessionStorage.getItem("bench_url") || "");
  const [tasks, setTasks] = useState<Task[]>(() => {
    try { return JSON.parse(sessionStorage.getItem("bench_tasks") || "[]"); } catch { return []; }
  });
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(() => sessionStorage.getItem("bench_taskId"));

  // Sync to sessionStorage on change
  useEffect(() => { sessionStorage.setItem("bench_url", url); }, [url]);
  useEffect(() => { sessionStorage.setItem("bench_tasks", JSON.stringify(tasks)); }, [tasks]);
  useEffect(() => { if (taskId) sessionStorage.setItem("bench_taskId", taskId); else sessionStorage.removeItem("bench_taskId"); }, [taskId]);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [steps, setSteps] = useState<StepRecord[]>([]);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [analyzingStats, setAnalyzingStats] = useState<{
    total_ms: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const retriesRef = useRef(0);
  const currentRunIdRef = useRef<string | null>(null);
  const analyzingStatsRef = useRef(analyzingStats);
  const stepsRef = useRef(steps);
  useEffect(() => { analyzingStatsRef.current = analyzingStats; }, [analyzingStats]);
  useEffect(() => { stepsRef.current = steps; }, [steps]);
  const lastGeneratedUrlRef = useRef(
    (() => { try { return JSON.parse(sessionStorage.getItem("bench_tasks") || "[]").length > 0 ? sessionStorage.getItem("bench_url") || "" : ""; } catch { return ""; } })()
  );

  const selectedTask = tasks.find((t) => t.id === taskId) ?? null;

  const isUrlValid = url.startsWith("http://") || url.startsWith("https://");
  const canRun = isUrlValid && selectedTask !== null && runStatus !== "running";

  const handleUrlSubmit = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return;
    if (trimmed === lastGeneratedUrlRef.current) return;
    if (tasksLoading) return;

    lastGeneratedUrlRef.current = trimmed;
    setTasksLoading(true);
    setTasksError(null);
    setTasks([]);
    setTaskId(null);

    try {
      const data = await generateTasks(trimmed);
      setTasks(data.tasks);
    } catch (e) {
      setTasksError(
        e instanceof Error ? e.message : "This site may not allow automated browsing. Try a different URL."
      );
    } finally {
      setTasksLoading(false);
    }
  }, [url, tasksLoading]);

  const handleRegenerateTasks = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return;
    if (tasksLoading) return;

    lastGeneratedUrlRef.current = "";
    setTasksLoading(true);
    setTasksError(null);
    setTasks([]);
    setTaskId(null);

    try {
      const data = await generateTasks(trimmed);
      setTasks(data.tasks);
      lastGeneratedUrlRef.current = trimmed;
    } catch (e) {
      setTasksError(
        e instanceof Error ? e.message : "This site may not allow automated browsing. Try a different URL."
      );
    } finally {
      setTasksLoading(false);
    }
  }, [url, tasksLoading]);

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
          setErrorMsg("Lost connection — the run may still be processing on the server.");
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

          if (data.status === "analyzing") {
            setRunStatus("analyzing");
            setAnalyzingStats({
              total_ms: data.total_ms,
              input_tokens: data.input_tokens,
              output_tokens: data.output_tokens,
              total_tokens: data.total_tokens,
            });
            // Don't stop polling — wait for "complete"
          }

          if (data.status === "complete") {
            stopPolling();
            setRunStatus("complete");
            setSummary({
              success: data.success,
              summary: data.summary,
              result_state: data.result_state,
              total_ms: data.total_ms,
              input_tokens: data.input_tokens,
              output_tokens: data.output_tokens,
              total_tokens: data.total_tokens,
              phases: data.phases ?? [],
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

  const doRun = useCallback(async () => {
    if (!selectedTask) return;

    if (!isSignedIn) {
      setShowSignIn(true);
      return;
    }

    const token = await getToken();
    if (!token) {
      setErrorMsg("Could not get auth token. Please sign in again.");
      return;
    }

    setRunStatus("running");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);
    setAnalyzingStats(null);
    setView("running");

    try {
      const data = await startBenchmark(url, selectedTask.goal, token);
      currentRunIdRef.current = data.run_id;
      startPolling(data.run_id);
    } catch (e) {
      setRunStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Failed to start benchmark.");
    }
  }, [selectedTask, isSignedIn, getToken, url, startPolling]);

  const handleRun = useCallback(async () => {
    if (!canRun || !selectedTask) return;
    await doRun();
  }, [canRun, selectedTask, doRun]);

  const handleRunAgain = useCallback(async () => {
    if (!selectedTask) return;
    await doRun();
  }, [selectedTask, doRun]);

  const handleNewTest = useCallback(() => {
    stopPolling();
    if (currentRunIdRef.current) {
      cancelBenchmark(currentRunIdRef.current);
      currentRunIdRef.current = null;
    }
    setRunStatus("idle");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);
    setAnalyzingStats(null);
    setUrl("");
    setTasks([]);
    setTaskId(null);
    lastGeneratedUrlRef.current = "";
    setView("setup");
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const [showSignIn, setShowSignIn] = useState(false);

  // Close modal when user signs in
  useEffect(() => {
    if (isSignedIn && showSignIn) {
      setShowSignIn(false);
    }
  }, [isSignedIn, showSignIn]);

  // Handle SSO callback (Google OAuth redirect)
  if (window.location.pathname === "/sso-callback") {
    return <AuthenticateWithRedirectCallback />;
  }

  if (view === "running") {
    return (
      <RunningView
        url={url}
        taskLabel={selectedTask?.label ?? ""}
        isRunning={runStatus === "running"}
        isAnalyzing={runStatus === "analyzing"}
        analyzingStats={analyzingStats}
        steps={steps}
        screenshot={screenshot}
        summary={summary}
        errorMsg={errorMsg}
        onRunAgain={handleRunAgain}
        onNewTest={handleNewTest}
      />
    );
  }

  return (
    <>
      <SetupView
        url={url}
        onUrlChange={setUrl}
        onUrlSubmit={handleUrlSubmit}
        tasks={tasks}
        tasksLoading={tasksLoading}
        tasksError={tasksError}
        taskId={taskId}
        onTaskSelect={(id) => setTaskId(id)}
        runStatus={runStatus}
        canRun={canRun}
        onRun={handleRun}
        onRegenerateTasks={handleRegenerateTasks}
        onSignInClick={() => setShowSignIn(true)}
      />
      {showSignIn && <SignInModal onClose={() => setShowSignIn(false)} />}
    </>
  );
}
