import { useState } from "react";
import type { ParsedLog } from "../lib/parseLog";

interface Props {
  log: ParsedLog;
}

export function GoalPanel({ log }: Props) {
  const [showPrompt, setShowPrompt] = useState(false);

  return (
    <div className="panel goal-panel">
      <div className="prompt-header">
        <div className="prompt-header-left">
          <h3>
            Agent Prompt
            <span className="scenario-badge">{log.scenario}</span>
          </h3>
          {log.startUrl && (
            <div className="goal-url">
              Target:{" "}
              <a href={log.startUrl} target="_blank" rel="noopener">
                {log.startUrl}
              </a>
            </div>
          )}
        </div>
        <button
          className={`view-prompt-btn ${showPrompt ? "active" : ""}`}
          onClick={() => setShowPrompt(!showPrompt)}
        >
          <span className="view-prompt-icon">{showPrompt ? "▾" : "▸"}</span>
          {showPrompt ? "Hide Prompt" : "View Prompt"}
        </button>
      </div>

      {showPrompt && (
        <div className="prompt-viewer">
          <div className="prompt-viewer-toolbar">
            <span className="prompt-viewer-label">Full prompt sent to agent</span>
            <button
              className="prompt-copy-btn"
              onClick={() => navigator.clipboard.writeText(log.goal)}
              title="Copy prompt to clipboard"
            >
              Copy
            </button>
          </div>
          <pre className="prompt-text">{log.goal}</pre>
        </div>
      )}
    </div>
  );
}
