interface AgentCardProps {
  /** Model id the backend ran the agent on; unknown until the run finishes. */
  model?: string | null;
  /** Whether the backend priced the run (cost_usd present). */
  priced?: boolean;
}

/** Which model drove the agent, as reported by the backend once the run finishes. */
export function AgentCard({ model, priced = true }: AgentCardProps) {
  return (
    <div
      data-testid="agent-card"
      className="flex-1 bg-white border-t-[3px] border-t-[#3c49ad] p-5 flex flex-col justify-center"
    >
      <p className="text-xs text-slate-600 uppercase tracking-wider mb-1.5">Agent model</p>
      {model ? (
        <p className="text-base font-bold text-slate-900 font-mono break-all">{model}</p>
      ) : (
        <p className="text-sm text-slate-400">Reported when the run finishes</p>
      )}
      <p className="text-xs text-slate-500 mt-3 leading-relaxed">
        {model && !priced
          ? "The backend has no per-token rate for this model, so only token counts are shown."
          : "A browser-use agent works through the task. Cost is its token usage at this model's rates."}
      </p>
    </div>
  );
}
