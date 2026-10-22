// 3 PSP x 5 bank grid coloured by D3 score, localizer primary outlined (docs/M5_CONSOLE.md §3). Click selects.
import { useQs } from "../store";

const PSPS = ["P1", "P2", "P3"];
const BANKS = ["B1", "B2", "B3", "B4", "B5"];

function colour(score: number): string {
  const s = Math.max(0, Math.min(1, score));
  return `rgba(255, ${Math.round(190 - 150 * s)}, 60, ${0.15 + 0.85 * s})`;
}

export function HeatMap() {
  const tick = useQs((s) => s.ticks[s.ticks.length - 1]);
  const select = useQs((s) => s.select);
  const selected = useQs((s) => s.selectedSegment);
  if (!tick) return <section className="panel"><h3>Heat map</h3><p className="muted">waiting for detection ticks…</p></section>;
  const seg = Object.fromEntries(tick.segments.map((x) => [x.segment_id, x]));
  const primary = tick.localization.primary_segment_id ?? "";
  const cell = 64;
  return (
    <section className="panel">
      <h3>Heat map <span className="muted">verdict: {tick.localization.verdict}</span></h3>
      <svg width={cell * 6 + 60} height={cell * 4 + 30} role="img" aria-label="segment heat map">
        {BANKS.map((b, j) => <text key={b} x={60 + j * cell + cell / 2} y={16} textAnchor="middle">{b}</text>)}
        {PSPS.map((p, i) => (
          <g key={p}>
            <text x={20} y={30 + i * cell + cell / 2}>{p}</text>
            {BANKS.map((b, j) => {
              const id = `route:${p}:${b}`;
              const s = seg[id];
              const hot = primary === id || primary === `bank:*:${b}` || primary === `psp:${p}:*`;
              return (
                <rect key={id} x={60 + j * cell} y={24 + i * cell} width={cell - 4} height={cell - 4}
                  fill={colour(s?.d3_score ?? 0)} stroke={hot ? "#ffd400" : selected === id ? "#fff" : "#333"}
                  strokeWidth={hot ? 3 : 1} onClick={() => select(id)}>
                  <title>{`${id} d3=${(s?.d3_score ?? 0).toFixed(2)} ${s?.state ?? ""}`}</title>
                </rect>
              );
            })}
          </g>
        ))}
      </svg>
    </section>
  );
}
