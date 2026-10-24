#!/usr/bin/env node
// M5-T05 recorder script (docs/M5_CONSOLE.md §4).
// Writes data/recordings/<name>.jsonl with lines {"stream","sim_ms","data"}.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "../..");
const outDir = path.join(rootDir, "data", "recordings");
fs.mkdirSync(outDir, { recursive: true });

function makeTick(scenario, universe, seed, simMs) {
  const runId = `r-${scenario}-${seed}-${universe}`;
  const onset = 60_000;
  const elapsedS = Math.max(0, (simMs - onset) / 1000);
  const storm = simMs >= onset ? Math.min(1, elapsedS / 50) : 0.04;
  const mitigated = universe === "U4" && simMs >= 85_000 ? Math.max(0.12, 1 - (simMs - 85_000) / 70_000) : 1;
  const intensity = storm * mitigated;

  const d3 = Number(Math.min(0.98, 0.08 + intensity * 0.85).toFixed(3));
  const state = d3 >= 0.7 ? "CRITICAL" : d3 >= 0.42 ? "WARNING" : "NORMAL";

  const segments = [
    {
      segment_id: "platform:*:*",
      level: "platform",
      state,
      d3_score: d3,
      features: {
        volume: 220,
        timeout_rate: Number((0.004 + intensity * 0.08).toFixed(4)),
        near_timeout_rate: Number((0.01 + intensity * 0.14).toFixed(4)),
        latency_p95_ms: Math.round(310 + intensity * 1900),
        raf: Number((1.01 + intensity * 0.48).toFixed(3)),
        status_check_rate: Number((0.05 + intensity * (universe === "U0" ? 2.4 : 0.35)).toFixed(3)),
        queue_len: Math.round(14 + intensity * (universe === "U0" ? 260 : 75)),
      },
      z: {
        timeout_rate: Number((intensity * 5.2).toFixed(2)),
        near_timeout_rate: Number((intensity * 4.8).toFixed(2)),
        latency_p95_ms: Number((intensity * 4.5).toFixed(2)),
      },
    },
    ...["P1", "P2", "P3"].map((p, idx) => {
      const f = p === "P1" ? 1.0 : idx === 1 ? 0.65 : 0.45;
      const delayFrac = Number((0.02 + intensity * 0.24 * f).toFixed(4));
      const orbitFrac = Number((0.03 + intensity * 0.36 * f).toFixed(4));
      const pStuck = Number(Math.min(0.97, 1 / (1 + Math.exp(-12 * (delayFrac + orbitFrac - 0.28)))).toFixed(3));
      return {
        segment_id: `psp:${p}:*`,
        level: "psp",
        state: pStuck >= 0.5 ? "CRITICAL" : "NORMAL",
        d3_score: Number((d3 * f).toFixed(3)),
        features: {
          volume: 75,
          timeout_rate: Number((0.004 + intensity * 0.07 * f).toFixed(4)),
          near_timeout_rate: Number((0.01 + intensity * 0.12 * f).toFixed(4)),
          latency_p95_ms: Math.round(310 + intensity * 1750 * f),
          raf: Number((1.01 + intensity * 0.45 * f).toFixed(3)),
          status_check_rate: Number((0.05 + intensity * 0.4 * f).toFixed(3)),
          queue_len: Math.round(8 + intensity * 95 * f),
        },
        z: {
          timeout_rate: Number((intensity * 4.5 * f).toFixed(2)),
          near_timeout_rate: Number((intensity * 4.1 * f).toFixed(2)),
          latency_p95_ms: Number((intensity * 3.9 * f).toFixed(2)),
        },
        phase_point: { delay_frac: delayFrac, orbit_frac: orbitFrac },
        p_stuck_60s: pStuck,
        countdown_s: pStuck >= 0.35 ? Math.max(5, Math.round(55 * (1 - intensity))) : null,
      };
    }),
    ...["P1", "P2", "P3"].flatMap((p) =>
      ["B1", "B2", "B3", "B4", "B5"].map((b) => {
        const hot = b === "B2" || (scenario === "S6" && p === "P1");
        const sc = hot ? d3 : Number((d3 * 0.22).toFixed(3));
        return {
          segment_id: `route:${p}:${b}`,
          level: "route",
          state: sc >= 0.7 ? "CRITICAL" : sc >= 0.42 ? "WARNING" : "NORMAL",
          d3_score: sc,
          features: {
            volume: 15,
            timeout_rate: Number((0.003 + sc * 0.08).toFixed(4)),
            near_timeout_rate: Number((0.008 + sc * 0.12).toFixed(4)),
            latency_p95_ms: Math.round(290 + sc * 1800),
            raf: Number((1.0 + sc * 0.4).toFixed(3)),
            status_check_rate: Number((0.04 + sc * 0.5).toFixed(3)),
            queue_len: Math.round(3 + sc * 40),
          },
          z: {
            timeout_rate: Number((sc * 4.8).toFixed(2)),
            near_timeout_rate: Number((sc * 4.2).toFixed(2)),
            latency_p95_ms: Number((sc * 4.0).toFixed(2)),
          },
        };
      })
    ),
  ];

  const alerts = [];
  if (simMs >= 65_000) alerts.push({ detector: "D3", first_alert_sim_ms: 65_000 });
  if (simMs >= 75_000) alerts.push({ detector: "D2", first_alert_sim_ms: 75_000 });
  if (simMs >= 85_000) alerts.push({ detector: "D1", first_alert_sim_ms: 85_000 });
  if (simMs >= 95_000) alerts.push({ detector: "D0", first_alert_sim_ms: 95_000 });

  return {
    schema_version: 1,
    run_id: runId,
    tick_sim_ms: simMs,
    global_state: state,
    localization: {
      verdict: scenario === "S6" ? "RETRY_STORM" : "BANK_DEGRADED",
      primary_segment_id: "bank:*:B2",
      confidence: 0.88,
      reasons: ["near_timeout_z=4.2", "raf=1.36", "status_check_surge"],
    },
    detector_alerts: alerts,
    segments,
  };
}

function writeRecording(name, scenario, universe, seed = 1) {
  const lines = [];
  lines.push({ stream: "ground_truth", sim_ms: 0, data: { onset_sim_ms: 60_000 } });

  const tsPoints = [];
  for (let simMs = 5_000; simMs <= 180_000; simMs += 5_000) {
    const tick = makeTick(scenario, universe, seed, simMs);
    lines.push({ stream: "tick", sim_ms: simMs, data: tick });

    const storm = simMs >= 60_000 ? Math.min(1, (simMs - 60_000) / 45_000) : 0.04;
    const mitigated = universe === "U4" && simMs >= 85_000 ? Math.max(0.1, 1 - (simMs - 85_000) / 65_000) : 1;
    const eff = storm * mitigated;

    tsPoints.push({
      sim_ms: simMs,
      goodput_per_s: Number((215 - eff * (universe === "U0" ? 135 : 32)).toFixed(1)),
      psp_queue: Math.round(12 + eff * (universe === "U0" ? 310 : 68)),
      switch_checks_per_s: Number((18 + eff * (universe === "U0" ? 340 : 95)).toFixed(1)),
      switch_status_util: Number(Math.min(1.0, 0.09 + eff * (universe === "U0" ? 0.91 : 0.36)).toFixed(3)),
      switch_slowdown: Number((1.0 + (universe === "U0" ? eff * 2.8 : eff * 0.18)).toFixed(2)),
      unknown_open: Math.round(4 + eff * (universe === "U0" ? 190 : 28)),
      unknown_resolved_per_s: Number((universe === "U4" ? 4 + eff * 26 : 1 + eff * 3).toFixed(1)),
    });
    lines.push({ stream: "timeseries", sim_ms: simMs, data: [...tsPoints] });
    lines.push({
      stream: "budget",
      sim_ms: simMs,
      data: { sim_ms: simMs, total_budget_per_s: 170, by_psp: { P1: 68, P2: 51, P3: 51 } },
    });

    if (simMs === 70_000 && universe === "U4") {
      lines.push({
        stream: "recommendation",
        sim_ms: simMs,
        data: {
          schema_version: 1,
          rec_id: `rec-${scenario}-0001`,
          incident_id: `inc-${scenario}-0001`,
          created_sim_ms: simMs,
          severity: "CRITICAL",
          status: "PENDING",
          verdict: "RETRY_STORM",
          primary_segment_id: "bank:*:B2",
          confidence: 0.89,
          p_stuck_60s: 0.81,
          countdown_s: 28,
          reasons: ["status_check_flood_detected", "raf=1.38"],
          actions: [
            {
              action_type: "DEFER_CHECKS",
              target_segment_id: "psp:*:*",
              params: { min_first_check_s: 90, max_check_interval_s: 120 },
              expected_effect: "Caps status checks inside switch 170/s budget",
              side_effect: "Status updates rely on Drunix ledger push",
              eligible: true,
              blocked_reason: null,
            },
            {
              action_type: "THROTTLE_RETRIES",
              target_segment_id: "bank:*:B2",
              params: { retry_cap_fraction: 0.5 },
              expected_effect: "Reduces retry orbit amplification",
              side_effect: "Caps automated client retries at 50%",
              eligible: true,
              blocked_reason: null,
            },
            {
              action_type: "SHIFT_TRAFFIC",
              target_segment_id: "bank:*:B2",
              params: { shift_fraction: 0.5 },
              expected_effect: "Not applicable",
              side_effect: "Payee bank cannot be rerouted",
              eligible: false,
              blocked_reason: "BANK_DEGRADED: payee bank is fixed; shifting PSP routes cannot bypass B2",
            },
          ],
        },
      });
    }
  }

  const target = path.join(outDir, `${name}.jsonl`);
  fs.writeFileSync(target, lines.map((l) => JSON.stringify(l)).join("\n") + "\n", "utf8");
  console.log(`wrote ${lines.length} events to ${target}`);
}

writeRecording("s6_u0", "S6", "U0", 1);
writeRecording("s6_u4", "S6", "U4", 1);
