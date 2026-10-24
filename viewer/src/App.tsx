import { useEffect, useState, useCallback, useRef } from "react";
import "./App.css";
import { parseLog, parseLogMeta } from "./lib/parseLog";
import type { ParsedLog, LogFileMeta } from "./lib/parseLog";
import { SummaryCards } from "./components/SummaryCards";
import { GoalPanel } from "./components/GoalPanel";
import { FrictionPanel } from "./components/FrictionPanel";
import { StepTimeline } from "./components/StepTimeline";
import { CostChart } from "./components/CostChart";
import { ResultsPage } from "./components/ResultsPage";

type Page = "results" | "logs";

function agentTag(meta: LogFileMeta): { cls: string; label: string } {
  if (meta.agent.toUpperCase().includes("RINDLER")) {
    return { cls: "rindler", label: "RINDLER" };
  }
  return meta.isMcp ? { cls: "mcp", label: "MCP" } : { cls: "bu", label: "BU" };
}

function App() {
  const [page, setPage] = useState<Page>(() => {
    return window.location.hash === "#logs" ? "logs" : "results";
  });
  const [fileMetas, setFileMetas] = useState<LogFileMeta[]>([]);
  const [metaLoading, setMetaLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [log, setLog] = useState<ParsedLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const rawCache = useRef<Map<string, string>>(new Map());

  // Sync hash with page state
  useEffect(() => {
    const onHashChange = () => {
      setPage(window.location.hash === "#logs" ? "logs" : "results");
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigateTo = useCallback((p: Page) => {
    window.location.hash = p === "logs" ? "#logs" : "#results";
    setPage(p);
  }, []);

  // Load manifest on mount
  useEffect(() => {
    setMetaLoading(true);
    fetch("/logs/manifest.json")
      .then((r) => r.json())
      .then(async (data: { files: string[] }) => {
        const metas = await Promise.all(
          data.files.map(async (f) => {
            try {
              const resp = await fetch(`/logs/${f}`);
              const raw = await resp.text();
              rawCache.current.set(f, raw);
              return parseLogMeta(raw, f);
            } catch {
              return null;
            }
          })
        );
        setFileMetas(metas.filter((m): m is LogFileMeta => m !== null));
      })
      .catch(() => {})
      .finally(() => setMetaLoading(false));
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const loadLogFile = useCallback(async (filename: string) => {
    setLoading(true);
    setError(null);
    try {
      let raw = rawCache.current.get(filename);
      if (!raw) {
        const resp = await fetch(`/logs/${filename}`);
        if (!resp.ok) throw new Error(`Failed to load ${filename}`);
        raw = await resp.text();
        rawCache.current.set(filename, raw);
      }
      const parsed = parseLog(raw, filename);
      setLog(parsed);
      setSelectedFile(filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleFileUpload = useCallback(async (file: File) => {
    setLoading(true);
    setError(null);
    try {
      const raw = await file.text();
      const parsed = parseLog(raw, file.name);
      setLog(parsed);
      setSelectedFile(file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to parse file");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file && file.name.endsWith(".log")) handleFileUpload(file);
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

  const selectedMeta = fileMetas.find((m) => m.filename === selectedFile) ?? null;

  // Log selector UI (shared between main page log section and logs page)
  const logSelectorUI = (
    <div className="log-selector" ref={dropdownRef}>
      <button
        className={`log-selector-trigger ${dropdownOpen ? "open" : ""}`}
        onClick={() => setDropdownOpen(!dropdownOpen)}
      >
        {selectedMeta ? (
          <span className="log-selector-value">
            <span className={`agent-tag ${agentTag(selectedMeta).cls}`}>
              {agentTag(selectedMeta).label}
            </span>
            <span className="log-selector-site">{selectedMeta.site}</span>
            <span className="log-selector-date">
              {selectedMeta.dateLabel} {selectedMeta.timeLabel}
            </span>
            <span className={`verdict-dot ${selectedMeta.verdict.toLowerCase()}`} />
          </span>
        ) : (
          <span className="log-selector-placeholder">
            {metaLoading ? "Loading runs..." : "Select a log run..."}
          </span>
        )}
        <span className="log-selector-chevron">&#9662;</span>
      </button>

      {dropdownOpen && (
        <div className="log-selector-dropdown">
          {fileMetas.length === 0 && (
            <div className="log-selector-empty">
              {metaLoading ? "Loading..." : "No log files found"}
            </div>
          )}
          {fileMetas.map((meta) => (
            <button
              key={meta.filename}
              className={`log-selector-option ${
                selectedFile === meta.filename ? "selected" : ""
              }`}
              onClick={() => {
                loadLogFile(meta.filename);
                setDropdownOpen(false);
              }}
            >
              <span className={`agent-tag ${agentTag(meta).cls}`}>
                {agentTag(meta).label}
              </span>
              <span className="log-selector-site">{meta.site}</span>
              <span className="log-selector-date">
                {meta.dateLabel} {meta.timeLabel}
              </span>
              <span className={`verdict-indicator ${meta.verdict.toLowerCase()}`}>
                {meta.verdict === "PASS" ? "PASS" : meta.verdict === "FAIL" ? "FAIL" : "-"}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const logViewerContent = (
    <>
      {loading && (
        <div className="loading-overlay">
          <div className="spinner" />
          Parsing log...
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {!log && !loading && (
        <div className="empty-state">
          <div className="empty-icon">&#128202;</div>
          <h2>VHListings Log Viewer</h2>
          <p>
            Select a run from the dropdown, or drag &amp; drop a{" "}
            <code>.log</code> file here.
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
              <h3>Browserbase Session</h3>
              <code className="artifact-link">
                {log.artifactUrl.split("/").pop()}
              </code>
              <p className="artifact-note">
                Session id from the original run. The replay belonged to the
                original Rindler Browserbase account and cannot be opened from
                here.
              </p>
            </div>
          )}
        </div>
      )}
    </>
  );

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-left">
          <img src="/logo.png" alt="Rindler" className="header-logo" />
          <div className="header-brand">
            <span className="header-brand-name">Rindler</span>
            <span className="header-brand-sub">VHListings Benchmark</span>
          </div>
          <nav className="header-nav">
            <button
              className={`nav-tab ${page === "results" ? "active" : ""}`}
              onClick={() => navigateTo("results")}
            >
              Results
            </button>
            <button
              className={`nav-tab ${page === "logs" ? "active" : ""}`}
              onClick={() => navigateTo("logs")}
            >
              Log Viewer
            </button>
          </nav>
        </div>

        {page === "logs" && (
          <div className="header-controls">
            {logSelectorUI}
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
      {page === "results" ? (
        <ResultsPage
          logSelectorUI={logSelectorUI}
          fileInputRef={fileInputRef}
          handleInputChange={handleInputChange}
          logViewerContent={logViewerContent}
          dragOver={dragOver}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        />
      ) : (
        <main
          className={`app-main ${dragOver ? "drag-over" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {logViewerContent}
        </main>
      )}
    </div>
  );
}

export default App;
