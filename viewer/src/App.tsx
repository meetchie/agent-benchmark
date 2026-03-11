import { useEffect, useState, useCallback, useRef } from "react";
import "./App.css";
import { parseLog, scenarioLabel } from "./lib/parseLog";
import type { ParsedLog } from "./lib/parseLog";
import { SummaryCards } from "./components/SummaryCards";
import { GoalPanel } from "./components/GoalPanel";
import { FrictionPanel } from "./components/FrictionPanel";
import { StepTimeline } from "./components/StepTimeline";
import { CostChart } from "./components/CostChart";
import { TrendsPage } from "./components/TrendsPage";

type Page = "viewer" | "trends";

function App() {
  const [page, setPage] = useState<Page>(() => {
    return window.location.hash === "#trends" ? "trends" : "viewer";
  });
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [log, setLog] = useState<ParsedLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Sync hash with page state
  useEffect(() => {
    const onHashChange = () => {
      setPage(window.location.hash === "#trends" ? "trends" : "viewer");
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigateTo = useCallback((p: Page) => {
    window.location.hash = p === "trends" ? "#trends" : "#viewer";
    setPage(p);
  }, []);

  // Load manifest on mount
  useEffect(() => {
    fetch("/logs/manifest.json")
      .then((r) => r.json())
      .then((data: { files: string[] }) => {
        setFiles(data.files);
      })
      .catch(() => {
        // Manifest not available — user can still upload
      });
  }, []);

  // Load selected log file
  const loadLogFile = useCallback(async (filename: string) => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/logs/${filename}`);
      if (!resp.ok) throw new Error(`Failed to load ${filename}`);
      const raw = await resp.text();
      const parsed = parseLog(raw, filename);
      setLog(parsed);
      setSelectedFile(filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file");
    } finally {
      setLoading(false);
    }
  }, []);

  // Handle file upload
  const handleFileUpload = useCallback(
    async (file: File) => {
      setLoading(true);
      setError(null);
      try {
        const raw = await file.text();
        const parsed = parseLog(raw, file.name);
        setLog(parsed);
        setSelectedFile(file.name);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to parse file"
        );
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Drag and drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file && file.name.endsWith(".log")) {
        handleFileUpload(file);
      }
    },
    [handleFileUpload]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileUpload(file);
    },
    [handleFileUpload]
  );

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-left">
          <img src="/logo.png" alt="Rindler" className="header-logo" />
          <div className="header-title">
            <h1>Rindler</h1>
            <span className="header-subtitle">Arena Log Analyzer</span>
          </div>
          <nav className="header-nav">
            <button
              className={`nav-tab ${page === "viewer" ? "active" : ""}`}
              onClick={() => navigateTo("viewer")}
            >
              Log Viewer
            </button>
            <button
              className={`nav-tab ${page === "trends" ? "active" : ""}`}
              onClick={() => navigateTo("trends")}
            >
              Trends
            </button>
          </nav>
        </div>

        {page === "viewer" && (
          <div className="header-controls">
            <select
              className="file-select"
              value={selectedFile}
              onChange={(e) => {
                if (e.target.value) loadLogFile(e.target.value);
              }}
            >
              <option value="">Select a log file...</option>
              {files.map((f) => (
                <option key={f} value={f}>
                  {scenarioLabel(f)}
                </option>
              ))}
            </select>
            <span className="or-divider">or</span>
            <button
              className="upload-btn"
              onClick={() => fileInputRef.current?.click()}
            >
              Upload .log
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".log"
              style={{ display: "none" }}
              onChange={handleInputChange}
            />
          </div>
        )}
      </header>

      {/* Main content */}
      {page === "viewer" ? (
        <main
          className={`app-main ${dragOver ? "drag-over" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {loading && (
            <div className="loading-overlay">
              <div className="spinner" />
              Parsing log...
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          {!log && !loading && (
            <div className="empty-state">
              <div className="empty-icon">📊</div>
              <h2>Arena Log Analyzer</h2>
              <p>
                Select a log file from the dropdown above, or drag &amp; drop a{" "}
                <code>.log</code> file here to analyze an agent run.
              </p>
              <div className="drop-zone">
                <span>Drop .log file here</span>
              </div>
            </div>
          )}

          {log && (
            <div className="dashboard">
              <SummaryCards log={log} />

              <div className="dashboard-grid">
                <div className="grid-left">
                  <GoalPanel log={log} />
                  <FrictionPanel log={log} />
                </div>
                <div className="grid-right">
                  <CostChart log={log} />
                </div>
              </div>

              <StepTimeline log={log} />

              {log.artifactUrl && (
                <div className="panel artifact-panel">
                  <h3>Session Replay</h3>
                  <a
                    href={log.artifactUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="artifact-link"
                  >
                    Open Browserbase Session Replay &rarr;
                  </a>
                </div>
              )}
            </div>
          )}
        </main>
      ) : (
        <main className="app-main">
          <TrendsPage />
        </main>
      )}
    </div>
  );
}

export default App;
