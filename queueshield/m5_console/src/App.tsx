// One screen, four tabs (docs/M5_CONSOLE.md §2). Layout: left 60 % detection, right 40 % decisions + ledger.
import { useEffect, useState } from "react";
import { config } from "./config";
import { changeReplaySpeed, connectAll, controlScenario, startScenario } from "./connect";
import { HeatMap } from "./panels/HeatMap";
import { DecisionLog, DrunixPanel } from "./panels/LedgerPanels";
import {
  About,
  ArenaTab,
  CascadeMap,
  DetectorRace,
  MetricStrip,
  SplitReplay,
  VerificationPanel,
} from "./panels/Placeholders";
import { RecommendationCard } from "./panels/RecommendationCard";
import { useQs } from "./store";
import { TEXT } from "./text/claims";

type Tab = "live" | "arena" | "split" | "about";

function Header() {
  const tick = useQs((s) => s.ticks[s.ticks.length - 1]);
  const simStatus = useQs((s) => s.simStatus);
  const sources = useQs((s) => s.sources);

  const simMs = simStatus?.sim_ms ?? tick?.tick_sim_ms ?? 0;
  const runLabel = simStatus
    ? `${simStatus.scenario ?? tick?.run_id ?? "S3"} · seed ${simStatus.seed ?? 1} · ${simStatus.universe ?? "U4"} · t=${Math.round(simMs / 1000)}s · ${simStatus.speed ?? 1}x`
    : tick
    ? `${tick.run_id} · t=${Math.round(tick.tick_sim_ms / 1000)}s`
    : "no run";

  const mode = simStatus?.mode ?? (sources.sim === "live" ? "live" : "mock");

  return (
    <header>
      <strong>QueueShield</strong>
      <span data-testid="header-run">{runLabel}</span>
      <span className={`pill ${tick?.global_state ?? "idle"}`}>{tick?.global_state ?? "IDLE"}</span>
      <span className={`badge ${mode === "live" ? "live" : "mock"}`}>{mode.toUpperCase()}</span>
      {Object.entries(sources).map(([k, v]) => (
        <span key={k} className={`badge ${v}`}>
          {k}: {v}
        </span>
      ))}
      <span className="badge">{TEXT.simulationLabel}</span>
    </header>
  );
}

function ScenarioBar() {
  const [busy, setBusy] = useState(false);
  const [universe, setUniverse] = useState<"U0" | "U2" | "U4">("U4");
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
  const simStatus = useQs((s) => s.simStatus);
  const activeScenario = simStatus?.scenario ?? "";
  const isPaused = simStatus?.state === "PAUSED";

  return (
    <nav className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
      <div className="row">
        {config.scenarios.map((s) => (
          <button
            key={s.id}
            className={activeScenario === s.id ? "active" : ""}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await startScenario(s.id, s.seed, universe, speed);
              setBusy(false);
            }}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="row">
        <select
          aria-label="Universe"
          value={universe}
          onChange={(e) => setUniverse(e.target.value as "U0" | "U2" | "U4")}
        >
          <option value="U4">U4 · QueueShield + Drunix</option>
          <option value="U2">U2 · Tuned baseline</option>
          <option value="U0">U0 · Unprotected</option>
        </select>
        {([1, 2, 4] as const).map((sp) => (
          <button
            key={sp}
            className={(simStatus?.speed ?? speed) === sp ? "active" : ""}
            onClick={() => {
              setSpeed(sp);
              changeReplaySpeed(sp);
            }}
          >
            {sp}x
          </button>
        ))}
        <button onClick={() => controlScenario(isPaused ? "RESUME" : "PAUSE")}>
          {isPaused ? "Resume" : "Pause"}
        </button>
        <button onClick={() => controlScenario("RESET")}>Reset</button>
      </div>
    </nav>
  );
}

const TAB_LABELS: Record<Tab, string> = {
  live: "Live",
  arena: "Arena",
  split: "April-2025 split replay",
  about: "About & claims",
};

export function App() {
  const [tab, setTab] = useState<Tab>("live");
  useEffect(() => connectAll(), []);
  return (
    <div className="app">
      <Header />
      <ScenarioBar />
      <nav className="tabs row" style={{ marginBottom: 10 }}>
        {(["live", "arena", "split", "about"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>
      {tab === "live" && (
        <main className="grid">
          <div className="left">
            <HeatMap />
            <MetricStrip />
            <DetectorRace />
            <CascadeMap />
          </div>
          <div className="right">
            <RecommendationCard />
            <DecisionLog />
            <DrunixPanel />
            <VerificationPanel />
          </div>
        </main>
      )}
      {tab === "arena" && <ArenaTab />}
      {tab === "split" && <SplitReplay />}
      {tab === "about" && <About />}
    </div>
  );
}
