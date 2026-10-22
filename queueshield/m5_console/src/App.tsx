// One screen, four tabs (docs/M5_CONSOLE.md §2). Layout: left 60 % detection, right 40 % decisions + ledger.
import { useEffect, useState } from "react";
import { config } from "./config";
import { connectAll, startScenario } from "./connect";
import { HeatMap } from "./panels/HeatMap";
import { DecisionLog, DrunixPanel } from "./panels/LedgerPanels";
import { About, ArenaTab, CascadeMap, DetectorRace, MetricStrip, SplitReplay, VerificationPanel } from "./panels/Placeholders";
import { RecommendationCard } from "./panels/RecommendationCard";
import { useQs } from "./store";
import { TEXT } from "./text/claims";

type Tab = "live" | "arena" | "split" | "about";

function Header() {
  const tick = useQs((s) => s.ticks[s.ticks.length - 1]);
  const sources = useQs((s) => s.sources);
  return (
    <header>
      <strong>QueueShield</strong>
      <span>{tick ? `${tick.run_id} · t=${Math.round(tick.tick_sim_ms / 1000)}s` : "no run"}</span>
      <span className={`pill ${tick?.global_state ?? "idle"}`}>{tick?.global_state ?? "IDLE"}</span>
      {Object.entries(sources).map(([k, v]) => <span key={k} className={`badge ${v}`}>{k}: {v}</span>)}
      <span className="badge">{TEXT.simulationLabel}</span>
    </header>
  );
}

function ScenarioBar() {
  const [busy, setBusy] = useState(false);
  return (
    <nav className="row">
      {config.scenarios.map((s) => (
        <button key={s.id} disabled={busy} onClick={async () => { setBusy(true); await startScenario(s.id, s.seed); setBusy(false); }}>
          {s.label}
        </button>
      ))}
    </nav>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("live");
  useEffect(() => connectAll(), []);
  return (
    <div className="app">
      <Header />
      <ScenarioBar />
      <nav className="tabs">
        {(["live", "arena", "split", "about"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {tab === "live" && (
        <main className="grid">
          <div className="left"><HeatMap /><MetricStrip /><DetectorRace /><CascadeMap /></div>
          <div className="right"><RecommendationCard /><DecisionLog /><DrunixPanel /><VerificationPanel /></div>
        </main>
      )}
      {tab === "arena" && <ArenaTab />}
      {tab === "split" && <SplitReplay />}
      {tab === "about" && <About />}
    </div>
  );
}
