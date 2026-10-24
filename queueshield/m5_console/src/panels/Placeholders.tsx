// Full implementations of MetricStrip, DetectorRace, CascadeMap, VerificationPanel, ArenaTab, SplitReplay, and About
// (docs/M5_CONSOLE.md §3, §9). Every metric comes from the store or simulator results and carries the simulation label.
import { useEffect, useState } from "react";
import { buildScenarioTimeseries } from "../mockData";
import type { TimeseriesPoint } from "../store";
import { useQs } from "../store";
import { TEXT } from "../text/claims";

function Sparkline({
  values,
  color,
  bandHigh,
  unit = "",
  width = 150,
  height = 44,
}: {
  values: number[];
  color: string;
  bandHigh?: number;
  unit?: string;
  width?: number;
  height?: number;
}) {
  if (values.length === 0) {
    return <div className="muted small">no points</div>;
  }
  const minV = 0;
  const maxV = Math.max(...values, bandHigh ?? 0, 0.001) * 1.15;
  const pts = values
    .map((v, i) => {
      const x = values.length === 1 ? width / 2 : (i / (values.length - 1)) * (width - 8) + 4;
      const y = height - 6 - ((v - minV) / (maxV - minV)) * (height - 12);
      return `${x.toFixed(1)},${Math.max(3, Math.min(height - 3, y)).toFixed(1)}`;
    })
    .join(" ");
  const bandY =
    bandHigh !== undefined
      ? Math.max(3, Math.min(height - 3, height - 6 - ((bandHigh - minV) / (maxV - minV)) * (height - 12)))
      : null;
  const last = values[values.length - 1] ?? 0;

  return (
    <div className="spark-card">
      <svg width={width} height={height} role="img" aria-label="metric sparkline">
        {bandY !== null && (
          <rect x={2} y={bandY} width={width - 4} height={Math.max(1, height - 4 - bandY)} fill="rgba(62, 207, 142, 0.09)" />
        )}
        {bandY !== null && (
          <line x1={2} y1={bandY} x2={width - 2} y2={bandY} stroke="#39404f" strokeDasharray="3 3" strokeWidth={1} />
        )}
        <polyline fill="none" stroke={color} strokeWidth={2} points={pts} />
      </svg>
      <div className="spark-val">
        {unit === "%" ? `${(last * 100).toFixed(1)}%` : unit === "ms" ? `${Math.round(last)} ms` : last.toFixed(2)}
      </div>
    </div>
  );
}

export function MetricStrip() {
  const ticks = useQs((s) => s.ticks);
  const selected = useQs((s) => s.selectedSegment);
  const select = useQs((s) => s.select);
  const source = useQs((s) => s.sources.detect);

  const recent = ticks.slice(-24);
  const segSeries = recent.map((t) => {
    const found = t.segments.find((x) => x.segment_id === selected) ?? t.segments[0];
    return found?.features ?? { timeout_ratio: 0, near_timeout_ratio: 0, p95_ms: 0, raf: 1, queue_depth: 0 };
  });

  const lastSeg =
    recent[recent.length - 1]?.segments.find((x) => x.segment_id === selected) ??
    recent[recent.length - 1]?.segments[0];

  return (
    <section className="panel" data-testid="metric-strip">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          Metric strip · <code>{selected}</code>{" "}
          <span className={`badge ${source}`}>{source.toUpperCase()}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        {selected !== "platform:*:*" && (
          <button className="small" onClick={() => select("platform:*:*")}>
            Reset to platform:*:*
          </button>
        )}
      </div>
      {recent.length === 0 ? (
        <p className="muted small">waiting for segment tick series…</p>
      ) : (
        <div className="spark-grid">
          <div>
            <div className="small muted">Timeout rate (z={(lastSeg?.z?.timeout_ratio ?? 0).toFixed(1)})</div>
            <Sparkline values={segSeries.map((f) => f.timeout_ratio ?? 0)} color="#f31260" bandHigh={0.02} unit="%" />
          </div>
          <div>
            <div className="small muted">Near-timeout rate (z={(lastSeg?.z?.near_timeout_ratio ?? 0).toFixed(1)})</div>
            <Sparkline values={segSeries.map((f) => f.near_timeout_ratio ?? 0)} color="#f5a524" bandHigh={0.04} unit="%" />
          </div>
          <div>
            <div className="small muted">Latency p95 (z={(lastSeg?.z?.p95_ms ?? 0).toFixed(1)})</div>
            <Sparkline values={segSeries.map((f) => f.p95_ms ?? 0)} color="#ffd400" bandHigh={900} unit="ms" />
          </div>
          <div>
            <div className="small muted">Retry amp. factor (RAF)</div>
            <Sparkline values={segSeries.map((f) => f.raf ?? 1)} color="#f5a524" bandHigh={1.15} />
          </div>
          <div>
            <div className="small muted">Queue depth</div>
            <Sparkline values={segSeries.map((f) => f.queue_depth ?? 0)} color="#3ecf8e" bandHigh={40} />
          </div>
        </div>
      )}
    </section>
  );
}

const DETECTORS: { id: "D0" | "D1" | "D2" | "D3"; label: string }[] = [
  { id: "D0", label: "D0 · Static timeout threshold" },
  { id: "D1", label: "D1 · CUSUM on timeout rate" },
  { id: "D2", label: "D2 · Univariate EWMA" },
  { id: "D3", label: "D3 · QueueShield multi-signal" },
];

export function DetectorRace() {
  const tick = useQs((s) => s.ticks[s.ticks.length - 1]);
  const onsetMs = useQs((s) => s.groundTruthOnsetMs);
  const source = useQs((s) => s.sources.detect);

  const alerts = tick?.detector_alerts ?? [];
  const byDetector = Object.fromEntries(alerts.map((a) => [a.detector, a]));
  const maxMs = Math.max(tick?.tick_sim_ms ?? 180_000, 180_000);
  const minMs = 40_000;
  const xForMs = (ms: number) => 170 + Math.max(0, Math.min(1, (ms - minMs) / (maxMs - minMs))) * 320;

  return (
    <section className="panel" data-testid="detector-race">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          Detector race{" "}
          <span className={`badge ${source}`}>{source.toUpperCase()}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        <span className="muted small">
          {onsetMs !== null ? `ground-truth onset: ${(onsetMs / 1000).toFixed(0)}s (replay)` : TEXT.onsetUnknown}
        </span>
      </div>
      <svg width={520} height={132} role="img" aria-label="detector race timeline">
        {onsetMs !== null && (
          <g>
            <line
              x1={xForMs(onsetMs)}
              y1={12}
              x2={xForMs(onsetMs)}
              y2={116}
              stroke="#ffd400"
              strokeDasharray="4 3"
              strokeWidth={1.5}
            />
            <text x={xForMs(onsetMs) + 4} y={20} fill="#ffd400">
              onset {(onsetMs / 1000).toFixed(0)}s
            </text>
          </g>
        )}
        {DETECTORS.map((d, idx) => {
          const y = 32 + idx * 24;
          const a = byDetector[d.id];
          const ms = a?.first_alert_sim_ms ?? null;
          const cx = ms !== null ? xForMs(ms) : null;
          const leadText =
            ms !== null
              ? onsetMs !== null
                ? `${(ms / 1000).toFixed(0)}s (+${Math.round((ms - onsetMs) / 1000)}s)`
                : `${(ms / 1000).toFixed(0)}s`
              : "quiet";
          return (
            <g key={d.id}>
              <text x={6} y={y + 4}>
                {d.label}
              </text>
              <line x1={170} y1={y} x2={490} y2={y} stroke="#2e3442" strokeWidth={2} />
              {cx !== null ? (
                <g data-testid={`flag-${d.id}`}>
                  <circle cx={cx} cy={y} r={6} fill={d.id === "D3" ? "#3ecf8e" : "#f5a524"} />
                  <text x={Math.min(445, cx + 8)} y={y + 4} fill="#e6e6e6">
                    {leadText}
                  </text>
                </g>
              ) : (
                <text x={450} y={y + 4}>
                  quiet
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </section>
  );
}

const PSP_COLOURS: Record<string, string> = {
  P1: "#ffd400",
  P2: "#3ecf8e",
  P3: "#60a5fa",
};

export function CascadeMap() {
  const grid = useQs((s) => s.forecasterGrid);
  const ticks = useQs((s) => s.ticks);
  const source = useQs((s) => s.sources.detect);

  const w = 300;
  const h = 210;
  const padL = 42;
  const padB = 28;
  const padT = 14;
  const padR = 16;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  const maxDelay = grid?.delay_bins?.[grid.delay_bins.length - 1] ?? 0.35;
  const maxOrbit = grid?.orbit_bins?.[grid.orbit_bins.length - 1] ?? 0.55;

  const toX = (delay: number) => padL + Math.max(0, Math.min(1, delay / maxDelay)) * plotW;
  const toY = (orbit: number) => padT + (1 - Math.max(0, Math.min(1, orbit / maxOrbit))) * plotH;

  const recentTicks = ticks.slice(-12);
  const lastTick = recentTicks[recentTicks.length - 1];
  const psps = ["P1", "P2", "P3"];

  const contourPts = (grid?.contour_0_5 ?? [])
    .map(([d, o]) => `${toX(d).toFixed(1)},${toY(o).toFixed(1)}`)
    .join(" ");

  return (
    <section className="panel" data-testid="cascade-map">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          Cascade map{" "}
          <span className={`badge ${source}`}>{source.toUpperCase()}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        <span className="muted small">{TEXT.forecastClaim}</span>
      </div>
      <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
        <svg width={w} height={h} role="img" aria-label="cascade phase plane">
          {grid &&
            grid.p.map((row, i) =>
              row.map((prob, j) => {
                const rows = grid.p.length;
                const cols = row.length;
                const cw = plotW / rows;
                const ch = plotH / cols;
                const x = padL + i * cw;
                const y = padT + (cols - 1 - j) * ch;
                const fill =
                  prob >= 0.5
                    ? `rgba(243, 18, 96, ${0.15 + 0.55 * prob})`
                    : `rgba(62, 207, 142, ${0.06 + 0.25 * (1 - prob)})`;
                return <rect key={`${i}-${j}`} x={x} y={y} width={cw + 0.5} height={ch + 0.5} fill={fill} />;
              })
            )}
          {contourPts && (
            <polyline
              fill="none"
              stroke="#f31260"
              strokeWidth={2}
              strokeDasharray="5 3"
              points={contourPts}
            />
          )}
          {psps.map((p) => {
            const pts = recentTicks
              .map((t) => t.segments.find((s) => s.segment_id === `psp:${p}:*`)?.phase_point)
              .filter((pt): pt is { delay_frac: number; orbit_frac: number } => Boolean(pt));
            if (pts.length === 0) return null;
            const poly = pts.map((pt) => `${toX(pt.delay_frac).toFixed(1)},${toY(pt.orbit_frac).toFixed(1)}`).join(" ");
            const head = pts[pts.length - 1]!;
            return (
              <g key={p}>
                <polyline fill="none" stroke={PSP_COLOURS[p]} strokeWidth={2.2} points={poly} />
                <circle cx={toX(head.delay_frac)} cy={toY(head.orbit_frac)} r={4.5} fill={PSP_COLOURS[p]} />
                <text x={toX(head.delay_frac) + 6} y={toY(head.orbit_frac) + 4} fill={PSP_COLOURS[p]}>
                  {p}
                </text>
              </g>
            );
          })}
          <text x={padL + plotW / 2} y={h - 6} textAnchor="middle">
            delay_frac (near-timeout + timeout)
          </text>
          <text x={12} y={padT + plotH / 2} transform={`rotate(-90 12 ${padT + plotH / 2})`} textAnchor="middle">
            orbit_frac (retries)
          </text>
        </svg>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div className="small muted" style={{ marginBottom: 6 }}>
            Dashed line: <strong>{TEXT.contourLabel}</strong>
          </div>
          {psps.map((p) => {
            const seg = lastTick?.segments.find((s) => s.segment_id === `psp:${p}:*`);
            const pStuck = seg?.p_stuck ?? 0;
            const countdown = seg?.countdown_s_estimate;
            return (
              <div key={p} className="chip" style={{ display: "block", marginBottom: 6 }}>
                <strong style={{ color: PSP_COLOURS[p] }}>{p}</strong> · p_stuck:{" "}
                <strong>{(pStuck * 100).toFixed(0)}%</strong>
                {countdown !== null && countdown !== undefined ? (
                  <span>
                    {" "}
                    · lock-in in ~{Math.round(countdown)}s ({TEXT.countdownCaveat})
                  </span>
                ) : (
                  <span className="muted"> · below threshold</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function VerificationPanel() {
  const ts = useQs((s) => s.timeseries);
  const budgets = useQs((s) => s.budgets);
  const source = useQs((s) => s.sources.sim);

  const recent = ts.slice(-30);
  const latest = recent[recent.length - 1];
  const latestBudget = budgets[budgets.length - 1]?.total_budget_per_s ?? 170;

  const w = 360;
  const h = 95;
  const maxChecks = Math.max(...recent.map((p) => p.switch_checks_per_s), latestBudget, 220);

  const checkPts = recent
    .map((p, i) => {
      const x = recent.length <= 1 ? 10 : 8 + (i / (recent.length - 1)) * (w - 16);
      const y = h - 10 - (p.switch_checks_per_s / maxChecks) * (h - 20);
      return `${x.toFixed(1)},${Math.max(4, Math.min(h - 6, y)).toFixed(1)}`;
    })
    .join(" ");

  const budgetY = Math.max(4, Math.min(h - 6, h - 10 - (latestBudget / maxChecks) * (h - 20)));

  return (
    <section className="panel" data-testid="verification-panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          Verification{" "}
          <span className={`badge ${source}`}>{source.toUpperCase()}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        <span className="muted small">budget: {Math.round(latestBudget)}/s · knee: 0.85</span>
      </div>
      {recent.length === 0 ? (
        <p className="muted small">waiting for simulator timeseries…</p>
      ) : (
        <>
          <div className="row" style={{ gap: 10, marginBottom: 6 }}>
            <span className="chip">
              Switch checks/s: <strong>{latest?.switch_checks_per_s.toFixed(1)}</strong>
            </span>
            <span className="chip">
              Switch util:{" "}
              <strong className={(latest?.switch_status_util ?? 0) >= 0.85 ? "danger" : ""}>
                {((latest?.switch_status_util ?? 0) * 100).toFixed(0)}%
              </strong>{" "}
              ({(latest?.switch_slowdown ?? 1).toFixed(2)}×)
            </span>
            <span className="chip">
              Unknown open: <strong>{latest?.unknown_open ?? 0}</strong> · resolved/s:{" "}
              <strong>{(latest?.unknown_resolved_per_s ?? 0).toFixed(1)}</strong>
            </span>
          </div>
          <svg width={w} height={h} role="img" aria-label="switch status checks vs budget">
            <line
              x1={8}
              y1={budgetY}
              x2={w - 8}
              y2={budgetY}
              stroke="#ffd400"
              strokeDasharray="4 3"
              strokeWidth={1.5}
            />
            <text x={w - 115} y={Math.max(12, budgetY - 4)} fill="#ffd400">
              M4 budget {Math.round(latestBudget)}/s
            </text>
            <polyline fill="none" stroke="#3ecf8e" strokeWidth={2.2} points={checkPts} />
          </svg>
        </>
      )}
    </section>
  );
}

export function ArenaTab() {
  const results = useQs((s) => s.arenaResults);
  const series = useQs((s) => s.arenaSeries);
  const sweep = useQs((s) => s.operatorSweep);
  const [scenario, setScenario] = useState<string>("S6");

  const scenarios = ["S6", "S4", "S3", "S1"];
  const universes: ("U0" | "U2" | "U4")[] = ["U0", "U2", "U4"];
  const uColours: Record<string, string> = { U0: "#f31260", U2: "#f5a524", U4: "#3ecf8e" };
  const uNames: Record<string, string> = {
    U0: "U0 · Unprotected",
    U2: "U2 · Tuned static baseline",
    U4: "U4 · QueueShield + Drunix",
  };

  function median(vals: (number | null | undefined)[]): number {
    const clean = vals.map((v) => Number(v ?? 0));
    if (clean.length === 0) return 0;
    const sorted = [...clean].sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)]!;
  }

  const rowsForScenario = results.filter((r) => r.scenario === scenario);

  return (
    <section className="panel" data-testid="arena-tab">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <h3>
          Baseline Arena (U0 vs U2 vs U4) <span className="badge">{TEXT.arenaLabel}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        <div className="row">
          {scenarios.map((sc) => (
            <button key={sc} className={scenario === sc ? "active" : ""} onClick={() => setScenario(sc)}>
              {sc}
            </button>
          ))}
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Universe</th>
            <th style={{ textAlign: "right" }}>Min goodput frac</th>
            <th style={{ textAlign: "right" }}>Recovery time (s)</th>
            <th style={{ textAlign: "right" }}>Excess retries</th>
            <th style={{ textAlign: "right" }}>Peak switch checks/s</th>
            <th style={{ textAlign: "right" }}>TAT breaches</th>
            <th style={{ textAlign: "right" }}>Duplicate commits</th>
          </tr>
        </thead>
        <tbody>
          {universes.map((u) => {
            const uRows = rowsForScenario.filter((r) => r.universe === u);
            const minGp = median(uRows.map((r) => r.metrics.goodput_min_frac));
            const recS = median(uRows.map((r) => r.metrics.recovery_time_s ?? 240));
            const retries = median(uRows.map((r) => r.metrics.excess_retries));
            const checks = median(uRows.map((r) => r.metrics.peak_switch_checks_per_s));
            const tat = median(uRows.map((r) => r.metrics.tat_breaches));
            const dup = median(uRows.map((r) => r.metrics.duplicate_commits));
            return (
              <tr key={u} data-testid={`arena-row-${u}`}>
                <td>
                  <strong style={{ color: uColours[u] }}>{uNames[u]}</strong>
                </td>
                <td style={{ textAlign: "right" }}>{(minGp * 100).toFixed(1)}%</td>
                <td style={{ textAlign: "right" }}>{recS >= 239 ? "unrecovered (>240s)" : `${recS.toFixed(0)}s`}</td>
                <td style={{ textAlign: "right" }}>{Math.round(retries)}</td>
                <td style={{ textAlign: "right" }}>{checks.toFixed(1)}/s</td>
                <td style={{ textAlign: "right" }}>{Math.round(tat)}</td>
                <td style={{ textAlign: "right" }}>{Math.round(dup)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="row" style={{ marginTop: 14, gap: 16, alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <h4>
            {scenario} trajectories (U0 / U2 / U4) · <span className="muted small">{TEXT.simulationLabel}</span>
          </h4>
          <ArenaChart
            u0={series[`${scenario}:U0`] ?? buildScenarioTimeseries(scenario, "U0")}
            u2={series[`${scenario}:U2`] ?? buildScenarioTimeseries(scenario, "U2")}
            u4={series[`${scenario}:U4`] ?? buildScenarioTimeseries(scenario, "U4")}
          />
        </div>
        {sweep.length > 0 && (
          <div style={{ flex: 1 }}>
            <h4>
              Operator approval latency sweep (S4 · U4) · <span className="muted small">{TEXT.simulationLabel}</span>
            </h4>
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Operator delay</th>
                  <th style={{ textAlign: "right" }}>Recovery (s)</th>
                  <th style={{ textAlign: "right" }}>Excess retries</th>
                  <th style={{ textAlign: "right" }}>Min goodput</th>
                </tr>
              </thead>
              <tbody>
                {sweep.map((row) => (
                  <tr key={row.operator_delay_s}>
                    <td>{row.operator_delay_s}s</td>
                    <td style={{ textAlign: "right" }}>{row.recovery_time_s}s</td>
                    <td style={{ textAlign: "right" }}>{row.excess_retries}</td>
                    <td style={{ textAlign: "right" }}>{(row.goodput_min_frac * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function ArenaChart({
  u0,
  u2,
  u4,
}: {
  u0: TimeseriesPoint[];
  u2: TimeseriesPoint[];
  u4: TimeseriesPoint[];
}) {
  const w = 440;
  const h = 130;
  const maxChecks = Math.max(
    ...u0.map((p) => p.switch_checks_per_s),
    ...u2.map((p) => p.switch_checks_per_s),
    ...u4.map((p) => p.switch_checks_per_s),
    220
  );
  const toLine = (pts: TimeseriesPoint[]) =>
    pts
      .map((p, i) => {
        const x = pts.length <= 1 ? 10 : 12 + (i / (pts.length - 1)) * (w - 24);
        const y = h - 16 - (p.switch_checks_per_s / maxChecks) * (h - 28);
        return `${x.toFixed(1)},${Math.max(6, Math.min(h - 12, y)).toFixed(1)}`;
      })
      .join(" ");

  return (
    <svg width={w} height={h} role="img" aria-label="arena switch checks comparison">
      <polyline fill="none" stroke="#f31260" strokeWidth={2} points={toLine(u0)} />
      <polyline fill="none" stroke="#f5a524" strokeWidth={2} points={toLine(u2)} />
      <polyline fill="none" stroke="#3ecf8e" strokeWidth={2.5} points={toLine(u4)} />
      <text x={14} y={16} fill="#f31260">
        U0 switch checks/s
      </text>
      <text x={150} y={16} fill="#f5a524">
        U2 tuned baseline
      </text>
      <text x={290} y={16} fill="#3ecf8e">
        U4 QueueShield + Drunix
      </text>
    </svg>
  );
}

export function SplitReplay() {
  const series = useQs((s) => s.arenaSeries);
  const u0All = series["S6:U0"] ?? buildScenarioTimeseries("S6", "U0");
  const u4All = series["S6:U4"] ?? buildScenarioTimeseries("S6", "U4");

  const [idx, setIdx] = useState<number>(Math.min(30, u0All.length - 1));
  const [playing, setPlaying] = useState<boolean>(false);
  const [speed, setSpeed] = useState<1 | 4>(1);

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setIdx((cur) => (cur + 1 >= u0All.length ? 0 : cur + 1));
    }, Math.round(280 / speed));
    return () => clearInterval(timer);
  }, [playing, speed, u0All.length]);

  const curU0 = u0All[idx] ?? u0All[u0All.length - 1];
  const curU4 = u4All[idx] ?? u4All[u4All.length - 1];
  const simS = Math.round((curU0?.sim_ms ?? 155_000) / 1000);

  return (
    <section className="panel" data-testid="split-replay">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <h3>
          April-2025 Status-Check Storm Split Replay (S6 · seed 1){" "}
          <span className="badge">{TEXT.splitReplayLabel}</span>{" "}
          <span className="badge">{TEXT.simulationLabel}</span>
        </h3>
        <div className="row">
          <button onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Play"}</button>
          <button className={speed === 1 ? "active" : ""} onClick={() => setSpeed(1)}>
            1x
          </button>
          <button className={speed === 4 ? "active" : ""} onClick={() => setSpeed(4)}>
            4x
          </button>
          <label className="small muted">
            t = {simS}s{" "}
            <input
              type="range"
              min={0}
              max={Math.max(0, u0All.length - 1)}
              value={idx}
              onChange={(e) => setIdx(Number(e.target.value))}
              aria-label="split replay timeline"
            />
          </label>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="panel sev-critical" data-testid="split-u0">
          <h4>U0 — Unprotected (status-check flood latches switch)</h4>
          <p className="small">
            Goodput/s: <strong>{curU0?.goodput_per_s.toFixed(1)}</strong> · PSP queue:{" "}
            <strong>{curU0?.psp_queue}</strong>
          </p>
          <p className="small">
            Switch checks/s: <strong className="danger">{curU0?.switch_checks_per_s.toFixed(1)}/s</strong> · Switch
            util: <strong className="danger">{((curU0?.switch_status_util ?? 0) * 100).toFixed(0)}%</strong> (
            {(curU0?.switch_slowdown ?? 1).toFixed(2)}× slowdown)
          </p>
          <p className="small">
            Unknown open: <strong>{curU0?.unknown_open}</strong> · Resolved/s:{" "}
            <strong>{curU0?.unknown_resolved_per_s.toFixed(1)}</strong>
          </p>
        </div>

        <div className="panel" style={{ borderLeft: "4px solid var(--good)" }} data-testid="split-u4">
          <h4>U4 — QueueShield + Drunix (budget + ledger push)</h4>
          <p className="small">
            Goodput/s: <strong>{curU4?.goodput_per_s.toFixed(1)}</strong> · PSP queue:{" "}
            <strong>{curU4?.psp_queue}</strong>
          </p>
          <p className="small">
            Switch checks/s: <strong>{curU4?.switch_checks_per_s.toFixed(1)}/s</strong> · Switch util:{" "}
            <strong>{((curU4?.switch_status_util ?? 0) * 100).toFixed(0)}%</strong> (
            {(curU4?.switch_slowdown ?? 1).toFixed(2)}× slowdown)
          </p>
          <p className="small">
            Unknown open: <strong>{curU4?.unknown_open}</strong> · Resolved/s (ledger push):{" "}
            <strong>{curU4?.unknown_resolved_per_s.toFixed(1)}</strong>
          </p>
        </div>
      </div>
    </section>
  );
}

export function About() {
  return (
    <section className="panel" data-testid="about-panel">
      <h3>About & claims</h3>
      <ul>
        {TEXT.about.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </section>
  );
}
