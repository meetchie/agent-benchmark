import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth, AuthenticateWithRedirectCallback } from "@clerk/clerk-react";
import { startBenchmark, pollStatus, generateTasks, cancelBenchmark, fetchQuota, fetchHealth, normalizeQuota, pollLimitSeconds, UNKNOWN_QUOTA } from "./lib/api";
import { isClerkMode } from "./lib/auth-mode";
import type { Task, StepRecord, RunStatus, RunStats, SummaryData, Quota, Health } from "./lib/types";

import { SignInModal } from "./components/SignInPage";
import { SetupView } from "./components/SetupView";
import { RunningView } from "./components/RunningView";
import { ExhaustedOverlay } from "./components/ExhaustedOverlay";
import { HeroSection } from "./components/HeroSection";

type View = "home" | "setup" | "running";

// Shown in local mode (no Clerk key) when the backend answers 401 anyway.
const LOCAL_AUTH_REJECTED =
  "The backend rejected the request as unauthenticated. Run it with AUTH_MODE=none, or set VITE_CLERK_PUBLISHABLE_KEY to sign in with Clerk.";

// How long a run is polled before the UI gives up is derived from the
// backend's own agent time limit (GET /health timeout_s); see pollLimitSeconds.
const POLL_INTERVAL_MS = 1000;

export default function App() {
  const { isSignedIn, getToken } = useAuth();

  const [view, setView] = useState<View>("home");

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
  const [analyzingStats, setAnalyzingStats] = useState<RunStats | null>(null);

  // Usage quota. remaining is null until the backend reports a limit (and
  // stays null when it enforces none, e.g. local mode).
  const [quota, setQuota] = useState<Quota>(UNKNOWN_QUOTA);

  // Fetch quota once the visitor is signed in and has left the landing page,
  // which has no use for it (and so makes no request to a backend that may not
  // be running yet). In local mode there is no token: ask without one.
  const atHome = view === "home";
  useEffect(() => {
    if (!isSignedIn || atHome) return;
    (async () => {
      const token = await getToken();
      if (!token && isClerkMode()) return;
      setQuota(await fetchQuota(token));
    })();
  }, [isSignedIn, getToken, atHome]);

  // What the backend says about itself (GET /health): whether it plays canned
  // runs (demo banner) and its agent time limit (how long to keep polling).
  // Asked once, together with the quota, when the visitor leaves the landing
  // page, so the landing page makes no request to a backend that may not be
  // up yet. null until the backend has answered; a run start asks again if so.
  const [health, setHealth] = useState<Health | null>(null);
  const healthRef = useRef<Health | null>(null);
  const healthAskedRef = useRef(false);
  const rememberHealth = useCallback((h: Health | null) => {
    if (!h) return;
    healthRef.current = h;
    setHealth(h);
  }, []);
  useEffect(() => {
    if (atHome || healthAskedRef.current) return;
    healthAskedRef.current = true;
    fetchHealth().then(rememberHealth);
  }, [atHome, rememberHealth]);
  const demoMode = health?.demo_mode === true;

  const [showExhausted, setShowExhausted] = useState(false);

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

  const taskGenAbortRef = useRef<AbortController | null>(null);

  // Clear tasks when user deletes 3+ characters from the generated URL
  useEffect(() => {
    const genUrl = lastGeneratedUrlRef.current;
    if (!genUrl || tasks.length === 0) return;
    if (url.length <= genUrl.length - 3) {
      setTasks([]);
      setTaskId(null);
      setTasksError(null);
      lastGeneratedUrlRef.current = "";
    }
  }, [url, tasks.length]);

  const handleUrlSubmit = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return;
    if (trimmed === lastGeneratedUrlRef.current) return;
    if (tasksLoading) return;
    if (!isSignedIn) {
      setTasksError("Sign in to generate benchmark tasks.");
      setShowSignIn(true);
      return;
    }

    lastGeneratedUrlRef.current = trimmed;
    setTasksLoading(true);
    setTasksError(null);
    setTasks([]);
    setTaskId(null);

    const abort = new AbortController();
    taskGenAbortRef.current = abort;

    try {
      const token = await getToken();
      if (abort.signal.aborted) return;
      if (!token && isClerkMode()) {
        throw new Error("AUTH_EXPIRED");
      }
      const data = await generateTasks(trimmed, token, abort.signal);
      if (!abort.signal.aborted) {
        setTasks(data.tasks);
      }
    } catch (e) {
      if (!abort.signal.aborted) {
        lastGeneratedUrlRef.current = "";
        if (e instanceof Error && e.message === "AUTH_EXPIRED") {
          if (isClerkMode()) {
            setTasksError("Please sign in again to generate benchmark tasks.");
            setShowSignIn(true);
          } else {
            setTasksError(LOCAL_AUTH_REJECTED);
          }
        } else {
          setTasksError(
            e instanceof Error ? e.message : "This site may not allow automated browsing. Try a different URL."
          );
        }
      }
    } finally {
      if (!abort.signal.aborted) {
        setTasksLoading(false);
      }
      if (taskGenAbortRef.current === abort) {
        taskGenAbortRef.current = null;
      }
    }
  }, [url, tasksLoading, isSignedIn, getToken]);

  const handleStopGenerate = useCallback(() => {
    if (taskGenAbortRef.current) {
      taskGenAbortRef.current.abort();
      taskGenAbortRef.current = null;
    }
    setTasksLoading(false);
    lastGeneratedUrlRef.current = "";
  }, []);

  const handleRegenerateTasks = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return;
    if (tasksLoading) return;
    if (!isSignedIn) {
      setTasksError("Sign in to generate benchmark tasks.");
      setShowSignIn(true);
      return;
    }

    lastGeneratedUrlRef.current = "";
    setTasksLoading(true);
    setTasksError(null);
    setTasks([]);
    setTaskId(null);

    try {
      const token = await getToken();
      if (!token && isClerkMode()) {
        throw new Error("AUTH_EXPIRED");
      }
      const data = await generateTasks(trimmed, token);
      setTasks(data.tasks);
      lastGeneratedUrlRef.current = trimmed;
    } catch (e) {
      lastGeneratedUrlRef.current = "";
      if (e instanceof Error && e.message === "AUTH_EXPIRED") {
        if (isClerkMode()) {
          setTasksError("Please sign in again to generate benchmark tasks.");
          setShowSignIn(true);
        } else {
          setTasksError(LOCAL_AUTH_REJECTED);
        }
      } else {
        setTasksError(
          e instanceof Error ? e.message : "This site may not allow automated browsing. Try a different URL."
        );
      }
    } finally {
      setTasksLoading(false);
    }
  }, [url, tasksLoading, isSignedIn, getToken]);

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
      const maxPolls = Math.ceil((pollLimitSeconds(healthRef.current?.timeout_s) * 1000) / POLL_INTERVAL_MS);

      pollRef.current = setInterval(async () => {
        pollCountRef.current++;

        if (pollCountRef.current > maxPolls) {
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
              cost_usd: data.cost_usd,
              agent_model: data.agent_model,
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
              cost_usd: data.cost_usd,
              agent_model: data.agent_model,
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
    if (!token && isClerkMode()) {
      setErrorMsg("Could not get auth token. Please sign in again.");
      return;
    }

    // Check quota before starting (a null remaining means no limit is enforced)
    if (quota.remaining !== null && quota.remaining <= 0) {
      const q = await fetchQuota(token);
      setQuota(q);
      if (q.remaining !== null && q.remaining <= 0) {
        setShowExhausted(true);
        return;
      }
    }

    // The backend was not up when health was first asked: ask again, so the
    // demo label and the poll limit are right for this run.
    if (!healthRef.current) rememberHealth(await fetchHealth());

    setRunStatus("running");
    setSteps([]);
    setScreenshot(null);
    setSummary(null);
    setErrorMsg(null);
    setAnalyzingStats(null);
    setView("running");

    try {
      // Compute the screenshot container size to match the viewer's browser
      // Mobile (< 768px): full width minus padding, no sidebar
      // Desktop: full width minus sidebar (300px) minus padding (16*2) minus gap (16) minus border (4)
      const isMobile = window.innerWidth < 768;
      const vpWidth = isMobile
        ? Math.round(window.innerWidth - 16 * 2)
        : Math.round(window.innerWidth - 300 - 16 * 2 - 16 - 4);
      const vpHeight = isMobile
        ? Math.round(window.innerHeight * 0.45)
        : Math.round(window.innerHeight * 0.55);
      const data = await startBenchmark(url, selectedTask.goal, selectedTask.label, token, { width: vpWidth, height: vpHeight }) as { run_id: string; remaining?: number | null; resets_in?: number; limit?: number | null };
      currentRunIdRef.current = data.run_id;
      if (data.remaining !== undefined) {
        setQuota((prev) => normalizeQuota({ remaining: data.remaining, resets_in: data.resets_in, limit: data.limit ?? prev.limit }));
      }
      startPolling(data.run_id);
    } catch (e) {
      setRunStatus("error");
      if (e instanceof Error && e.message === "AUTH_EXPIRED") {
        setErrorMsg(isClerkMode() ? "Your session expired. Sign in again to run a benchmark." : LOCAL_AUTH_REJECTED);
      } else {
        setErrorMsg(e instanceof Error ? e.message : "Failed to start benchmark.");
      }
    }
  }, [selectedTask, isSignedIn, getToken, url, startPolling, quota.remaining, rememberHealth]);

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
    if (isSignedIn) {
      setTasksError((prev) => {
        if (
          prev === "Sign in to generate benchmark tasks." ||
          prev === "Please sign in again to generate benchmark tasks."
        ) {
          return null;
        }
        return prev;
      });
    }
  }, [isSignedIn, showSignIn]);

  // Handle SSO callback (Google OAuth redirect)
  if (window.location.pathname === "/sso-callback") {
    return <AuthenticateWithRedirectCallback />;
  }

  if (view === "running") {
    return (
      <>
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
          remainingRuns={quota.remaining ?? undefined}
          runLimit={quota.limit ?? undefined}
          resetsIn={quota.resets_in}
          demoMode={demoMode}
        />
        {showExhausted && <ExhaustedOverlay resetsIn={quota.resets_in} onClose={() => setShowExhausted(false)} />}
      </>
    );
  }

  if (view === "home") {
    return (
      <div className="view-enter" key="home">
        <HeroSection
          onSignInClick={isSignedIn ? undefined : () => setShowSignIn(true)}
          onCTA={() => setView("setup")}
        />
        {showSignIn && <SignInModal onClose={() => setShowSignIn(false)} />}
      </div>
    );
  }

  return (
    <div className="view-enter" key="setup">
      <SetupView
        url={url}
        onUrlChange={setUrl}
        onUrlSubmit={handleUrlSubmit}
        onStopGenerate={handleStopGenerate}
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
        remainingRuns={isSignedIn ? quota.remaining ?? undefined : undefined}
        runLimit={isSignedIn ? quota.limit ?? undefined : undefined}
        resetsIn={isSignedIn ? quota.resets_in : undefined}
        demoMode={demoMode}
      />
      {showSignIn && <SignInModal onClose={() => setShowSignIn(false)} />}
      {showExhausted && <ExhaustedOverlay resetsIn={quota.resets_in} onClose={() => setShowExhausted(false)} />}
    </div>
  );
}
