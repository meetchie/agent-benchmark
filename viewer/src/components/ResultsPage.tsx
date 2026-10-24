import { useEffect, useRef, useState } from "react";

// ─── Benchmark Data ────────────────────────────────────────────────────────────

const RINDLER = {
  runs: 60,
  pass: 59,
  passRate: 98.3,
  avgCostPerRun: 0.1366,
  costPerSuccess: 0.14,
  avgDurationSec: 70.1,
  avgSteps: 14.1,
  avgTokens: 52856,
};

const BROWSERUSE = {
  runs: 60,
  pass: 1,
  passRate: 1.7,
  avgCostPerRun: 0.713,
  costPerSuccess: 42.78,
  avgDurationSec: 307.3,
  avgSteps: 28.5,
  avgTokens: 272377,
};

// ─── Funnel Data ───────────────────────────────────────────────────────────────

interface FunnelStage {
  stage: string;
  count: number;
  dropCount: number;
  dropReason?: string;
  isDarkPattern?: boolean;
  darkPatternLabel?: string;
}

const FUNNEL: FunnelStage[] = [
  { stage: "Session started", count: 60, dropCount: 0 },
  {
    stage: "Added 3 items to cart",
    count: 25,
    dropCount: 35,
    dropReason: "Klaviyo email popup blocked all cart interaction",
    isDarkPattern: true,
    darkPatternLabel: "Dark pattern: Klaviyo popup",
  },
  {
    stage: "Reached Shopify checkout",
    count: 17,
    dropCount: 8,
    dropReason:
      "Agent couldn't verify cart contents or navigate past the cart page",
  },
  {
    stage: "Applied SPRING promo code",
    count: 8,
    dropCount: 9,
    dropReason:
      "Shopify React checkout - promo input loads asynchronously, not in DOM on arrival",
    isDarkPattern: true,
    darkPatternLabel: "Dark pattern: Shopify async checkout",
  },
  {
    stage: "VIP Membership removed",
    count: 1,
    dropCount: 7,
    dropReason:
      "VIP Membership auto-added to every cart. Agent couldn't detect or remove it - checkout had 4 items",
    isDarkPattern: true,
    darkPatternLabel: "Dark pattern: VIP auto-add",
  },
  { stage: "Full pass", count: 1, dropCount: 0 },
];

// ─── Component Props ───────────────────────────────────────────────────────────

interface Props {
  logSelectorUI: React.ReactNode;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  logViewerContent: React.ReactNode;
  dragOver: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

// ─── Hero Section ──────────────────────────────────────────────────────────────

function HeroSection() {
  return (
    <div className="hero-section">
      <div className="hero-inner">
        <div className="hero-eyebrow">
          60 runs &middot; VHListings.com &middot; vhlistings_bundle_promo
        </div>
        <h1 className="hero-title">Rindler vs BrowserUse</h1>

        <div className="hero-stats">
          <div className="hero-stat-box rindler">
            <div className="hero-stat-agent">Rindler</div>
            <div className="hero-stat-label">Pass Rate</div>
            <div className="hero-stat-value primary">{RINDLER.passRate}%</div>
            <div className="hero-stat-sub">{RINDLER.pass} of {RINDLER.runs} runs</div>
          </div>

          <div className="hero-vs">vs</div>

          <div className="hero-stat-box browseruse">
            <div className="hero-stat-agent">BrowserUse</div>
            <div className="hero-stat-label">Pass Rate</div>
            <div className="hero-stat-value red">{BROWSERUSE.passRate}%</div>
            <div className="hero-stat-sub">{BROWSERUSE.pass} of {BROWSERUSE.runs} runs</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Scenario Section ──────────────────────────────────────────────────────────

const SCENARIO_STEPS = [
  {
    num: "1",
    label: "Add 3 bundle items",
    detail: "Navigate product pages, add each item to cart",
    note: null,
  },
  {
    num: "2",
    label: "Apply SPRING promo",
    detail: "Enter promo code in Shopify's async checkout",
    note: "Promo input loads asynchronously after page render",
  },
  {
    num: "3",
    label: "Check the order",
    detail: "Report the checkout total. The judge also checks that no VIP Membership is in the order",
    note: "VIP Membership is silently added to every cart",
  },
];

function ScenarioSection() {
  return (
    <div className="scenario-section">
      <div className="scenario-inner">
        <div className="scenario-header">
          <div className="scenario-title">The Task</div>
          <div className="scenario-subtitle">
            Agents shop on vhlistings.com, a live Shopify store with 3 embedded dark patterns, up to applying a promo code at checkout. No payment details are entered
          </div>
        </div>
        <div className="scenario-steps">
          {SCENARIO_STEPS.map((s) => (
            <div key={s.num} className="scenario-step">
              <div className="scenario-step-num">{s.num}</div>
              <div className="scenario-step-body">
                <div className="scenario-step-label">{s.label}</div>
                <div className="scenario-step-detail">{s.detail}</div>
                {s.note && <div className="scenario-step-note">&#9888; {s.note}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Funnel Section ────────────────────────────────────────────────────────────

function FunnelSection() {
  const [animated, setAnimated] = useState(false);
  const [expandedDrop, setExpandedDrop] = useState<number | null>(null);
  const sectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setAnimated(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 }
    );
    if (sectionRef.current) observer.observe(sectionRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="funnel-section" ref={sectionRef}>
      <div className="funnel-inner">
        <div className="section-title">Where BrowserUse Failed</div>
        <div className="section-subtitle">
          60 runs &middot; 3 site-specific dark patterns &middot; <span className="funnel-hint">click a drop to expand</span>
        </div>

        <div className="funnel-track">
          {FUNNEL.map((stage, i) => {
            const barPct = (stage.count / 60) * 100;
            const prevPct = i > 0
              ? Math.round((stage.count / FUNNEL[i - 1].count) * 100)
              : null;
            const hasDrop = stage.dropCount > 0;
            const isExpanded = expandedDrop === i;

            return (
              <div key={stage.stage} className="funnel-item">
                {/* Stage row — label | bar (with inline drop icon) | count */}
                <div
                  className={`funnel-row${hasDrop ? " has-drop" : ""}${isExpanded ? " is-expanded" : ""}`}
                  onClick={() => hasDrop && setExpandedDrop(isExpanded ? null : i)}
                  role={hasDrop ? "button" : undefined}
                  tabIndex={hasDrop ? 0 : undefined}
                  onKeyDown={(e) => hasDrop && e.key === "Enter" && setExpandedDrop(isExpanded ? null : i)}
                >
                  <div className="funnel-row-label">
                    <span className="funnel-row-name">{stage.stage}</span>
                    {prevPct !== null && (
                      <span className="funnel-row-pct">{prevPct}% from prev</span>
                    )}
                  </div>
                  <div className="funnel-row-bar">
                    <div
                      className={`funnel-bar-fill ${animated ? "animate" : ""}`}
                      style={{
                        width: `${barPct}%`,
                        animationDelay: `${0.05 + i * 0.1}s`,
                      }}
                    />
                    {/* Drop indicator — floats in the empty zone of the bar */}
                    {hasDrop && (
                      <div className={`funnel-drop-icon${stage.isDarkPattern ? " dark-pattern" : ""}`}>
                        <span className="fdi-icon">{stage.isDarkPattern ? "⚠" : "↓"}</span>
                        <span className={`fdi-chevron${isExpanded ? " open" : ""}`}>›</span>
                      </div>
                    )}
                  </div>
                  <div className="funnel-row-count">{stage.count}</div>
                </div>

                {/* Expand panel — single card below the row */}
                {hasDrop && isExpanded && (
                  <div className={`funnel-expand${stage.isDarkPattern ? " dark-pattern" : ""}`}>
                    <div className="fex-reason">
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
                        <span className="fex-count">&minus;{stage.dropCount} dropped</span>
                        {stage.isDarkPattern && (
                          <span className="fex-badge">&#9888; {stage.darkPatternLabel?.replace("Dark pattern: ", "")}</span>
                        )}
                      </div>
                      {stage.dropReason}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Metrics Section ───────────────────────────────────────────────────────────

function MetricsSection() {

  return (
    <div className="metrics-section">
      <div className="metrics-inner">
        <div className="section-title" style={{ marginBottom: "0.25rem" }}>
          By the Numbers
        </div>
        <div className="section-subtitle">
          Per-run averages across all 60 runs
        </div>

        <div className="metrics-grid">
          {/* Card 1: Cost per run */}
          <div className="metric-card">
            <div className="metric-card-label">Cost per run</div>
            <div className="metric-rows">
              <div className="metric-row">
                <span className="metric-row-agent">Rindler</span>
                <span className="metric-row-value primary">
                  ${RINDLER.avgCostPerRun.toFixed(2)}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-row-agent">BrowserUse</span>
                <span className="metric-row-value red">
                  ${BROWSERUSE.avgCostPerRun.toFixed(2)}
                </span>
              </div>
            </div>
            <div className="metric-delta">5.2x cheaper</div>
          </div>

          {/* Card 2: Cost per success (featured) */}
          <div className="metric-card featured">
            <div className="metric-card-label">Cost per success</div>
            <div className="metric-rows">
              <div className="metric-row">
                <span className="metric-row-agent">Rindler</span>
                <span className="metric-row-value primary">
                  ${RINDLER.costPerSuccess.toFixed(2)}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-row-agent">BrowserUse</span>
                <span className="metric-row-value red">
                  ${BROWSERUSE.costPerSuccess.toFixed(2)}
                </span>
              </div>
            </div>
            <div className="metric-delta">306x cheaper per success</div>
          </div>

          {/* Card 3: Speed */}
          <div className="metric-card">
            <div className="metric-card-label">Avg completion time</div>
            <div className="metric-rows">
              <div className="metric-row">
                <span className="metric-row-agent">Rindler</span>
                <span className="metric-row-value primary">
                  {Math.round(RINDLER.avgDurationSec)}s
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-row-agent">BrowserUse</span>
                <span className="metric-row-value red">
                  {Math.round(BROWSERUSE.avgDurationSec)}s
                </span>
              </div>
            </div>
            <div className="metric-delta">4.4x faster</div>
          </div>

          {/* Card 4: Tokens */}
          <div className="metric-card">
            <div className="metric-card-label">Avg tokens per run</div>
            <div className="metric-rows">
              <div className="metric-row">
                <span className="metric-row-agent">Rindler</span>
                <span className="metric-row-value primary">
                  {RINDLER.avgTokens.toLocaleString()}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-row-agent">BrowserUse</span>
                <span className="metric-row-value red">
                  {BROWSERUSE.avgTokens.toLocaleString()}
                </span>
              </div>
            </div>
            <div className="metric-delta">5.2x fewer tokens</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Log Section ───────────────────────────────────────────────────────────────

interface LogSectionProps {
  logSelectorUI: React.ReactNode;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  logViewerContent: React.ReactNode;
  dragOver: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

function LogSection({
  logSelectorUI,
  fileInputRef,
  handleInputChange,
  logViewerContent,
  dragOver,
  onDragOver,
  onDragLeave,
  onDrop,
}: LogSectionProps) {
  return (
    <div
      className={`log-section ${dragOver ? "drag-over" : ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="log-section-inner">
        <div className="log-section-header">
          <div className="log-section-title">Explore Individual Runs</div>
          <div className="log-section-sub">
            Step-by-step telemetry for each benchmark run
          </div>
        </div>

        <div className="log-section-controls">
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

        {logViewerContent}
      </div>
    </div>
  );
}

// ─── Results Page ──────────────────────────────────────────────────────────────

export function ResultsPage({
  logSelectorUI,
  fileInputRef,
  handleInputChange,
  logViewerContent,
  dragOver,
  onDragOver,
  onDragLeave,
  onDrop,
}: Props) {
  return (
    <div className="results-page">
      <HeroSection />
      <ScenarioSection />
      <FunnelSection />
      <MetricsSection />
      <LogSection
        logSelectorUI={logSelectorUI}
        fileInputRef={fileInputRef}
        handleInputChange={handleInputChange}
        logViewerContent={logViewerContent}
        dragOver={dragOver}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      />
    </div>
  );
}
