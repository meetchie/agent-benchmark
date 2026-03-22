import { useState, useEffect, useRef, useCallback } from "react";
import { startBenchmark, pollStatus, generateTasks, hasToken, getMe, clearToken } from "./lib/api";
import type { Task, StepRecord, RunStatus, SummaryData } from "./lib/types";

import { SetupView } from "./components/SetupView";
import { RunningView } from "./components/RunningView";
import { SignInPage } from "./components/SignInPage";
import { SignUpPage } from "./components/SignUpPage";

type View = "signin" | "signup" | "setup" | "running";

const MAX_POLLS = 180;
const POLL_INTERVAL_MS = 1000;

export default function App() {
  const [view, setView] = useState<View>(hasToken() ? "setup" : "signin");
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [remainingRuns, setRemainingRuns] = useState(3);
  const [resetTime, setResetTime] = useState<string | null>(null);

  const [url, setUrl] = useState("");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [steps, setSteps] = useState<StepRecord[]>([]);
  const [screenshot, setScreenshot] = useState<string | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const retriesRef = useRef(0);
  const lastGeneratedUrlRef = useRef("");

  const selectedTask = tasks.find((t) => t.id === taskId) ?? null;

  const isUrlValid = url.startsWith("http://") || url.startsWith("https://");
  const canRun = isUrlValid && selectedTask !== null && runStatus !== "running" && remainingRuns > 0;

  // Check auth on mount
  useEffect(() => {
    if (hasToken()) {
      getMe()
        .then((me) => {
          setUserEmail(me.email);
          setRemainingRuns(me.remaining_runs);
          setResetTime(me.reset_time);
        })
        .catch(() => {
          clearToken();
          setView("signin");
        });
    }
  }, []);

  const handleSignedIn = useCallback(() => {
    getMe().then((me) => {
      setUserEmail(me.email);
      setRemainingRuns(me.remaining_runs);
      setResetTime(me.reset_time);
      setView("setup");
    });
  }, []);

  const handleSignOut = useCallback(() => {
    clearToken();
    setUserEmail(null);
    setView("signin");
  }, []);

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

    lastGeneratedUrlRef.current = "";  // Clear so it regenerates even for same URL
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
              input_tokens: data.input_tokens,
              output_tokens: data.output_tokens,
              total_tokens: data.total_tokens,
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
    setView("running");

    try {
      const data = await startBenchmark(url, selectedTask.goal);
      if (data.remaining_runs !== undefined) {
        setRemainingRuns(data.remaining_runs);
      }
      startPolling(data.run_id);
    } catch (e) {
      setRunStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Failed to start benchmark.");
    }
  }, [canRun, selectedTask, url, startPolling]);

  const handleRunAgain = useCallback(async () => {
    if (!selectedTask) return;

    setRunStatus("running");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);

    try {
      const data = await startBenchmark(url, selectedTask.goal);
      if (data.remaining_runs !== undefined) {
        setRemainingRuns(data.remaining_runs);
      }
      startPolling(data.run_id);
    } catch (e) {
      setRunStatus("error");
      setErrorMsg(e instanceof Error ? e.message : "Failed to start benchmark.");
    }
  }, [selectedTask, url, startPolling]);

  const handleNewTest = useCallback(() => {
    stopPolling();
    setRunStatus("idle");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);
    setView("setup");
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  if (view === "signin") {
    return <SignInPage onSignedIn={handleSignedIn} onSwitchToSignUp={() => setView("signup")} />;
  }
  if (view === "signup") {
    return <SignUpPage onSignedUp={handleSignedIn} onSwitchToSignIn={() => setView("signin")} />;
  }

  if (view === "running") {
    return (
      <RunningView
        url={url}
        taskLabel={selectedTask?.label ?? ""}
        isRunning={runStatus === "running"}
        steps={steps}
        screenshot={screenshot}
        summary={summary}
        errorMsg={errorMsg}
        onRunAgain={handleRunAgain}
        onNewTest={handleNewTest}
        remainingRuns={remainingRuns}
      />
    );
  }

  return (
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
      remainingRuns={remainingRuns}
      resetTime={resetTime}
      userEmail={userEmail}
      onSignOut={handleSignOut}
    />
  );
}
