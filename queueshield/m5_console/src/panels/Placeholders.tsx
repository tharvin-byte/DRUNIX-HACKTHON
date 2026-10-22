// Panels not built yet. Each placeholder names its data source and acceptance test (docs/M5_CONSOLE.md §3, §9)
// so the M5 owner can replace them one by one.
import { TEXT } from "../text/claims";

function Todo({ title, source, accept }: { title: string; source: string; accept: string }) {
  return (
    <section className="panel todo">
      <h3>{title} <span className="badge">TODO</span></h3>
      <p className="muted small">source: {source}</p>
      <p className="muted small">acceptance: {accept}</p>
    </section>
  );
}

export const MetricStrip = () => <Todo title="Metric strip" source="M3 ticks, selected segment (uPlot sparklines)" accept="updates every tick" />;
export const DetectorRace = () => <Todo title="Detector race" source={`M3 detector_alerts; onset only in replay/arena (live: ${TEXT.onsetUnknown})`} accept="S4: four distinct flags" />;
export const CascadeMap = () => <Todo title="Cascade map" source={`M3 /v1/forecaster/grid + per-PSP phase_point; ${TEXT.contourLabel}`} accept="S4 trail crosses contour; S1 stays below" />;
export const VerificationPanel = () => <Todo title="Verification" source="M2 /v1/timeseries + M4 budget events" accept="S6 spike under U0 replay, flat under U4" />;
export const ArenaTab = () => <Todo title="Arena" source={`M2 /v1/results (${TEXT.arenaLabel})`} accept="U2 always shown next to U4" />;
export const SplitReplay = () => <Todo title="April-2025 split replay" source={`data/recordings U0 vs U4 (${TEXT.splitReplayLabel})`} accept="U-6 same final state at 1x and 4x" />;

export function About() {
  return (
    <section className="panel">
      <h3>About & claims</h3>
      <ul>{TEXT.about.map((t) => <li key={t}>{t}</li>)}</ul>
    </section>
  );
}
