// Deterministic simulation fixtures & scenario generators for MOCK and Replay modes (docs/M5_CONSOLE.md §3, §4).
// All values represent synthetic simulation outputs and are labelled "simulation".
import type { Recommendation, RunResult, SegmentState } from "./contracts";
import type { BudgetPoint, ForecasterGridData, OperatorSweepRow, TimeseriesPoint } from "./store";

const PSPS = ["P1", "P2", "P3"] as const;
const BANKS = ["B1", "B2", "B3", "B4", "B5"] as const;

export function buildMockForecasterGrid(): ForecasterGridData {
  const delay_bins = Array.from({ length: 21 }, (_, i) => Number((i * 0.1).toFixed(2)));
  const orbit_bins = Array.from({ length: 21 }, (_, j) => Number((j * 0.15).toFixed(2)));
  const p: number[][] = [];
  for (let i = 0; i < 20; i++) {
    const row: number[] = [];
    const d = (delay_bins[i] + delay_bins[i + 1]) / 2;
    for (let j = 0; j < 20; j++) {
      const o = (orbit_bins[j] + orbit_bins[j + 1]) / 2;
      const z = 3.2 * (d / 2.0) + 2.8 * (o / 3.0) - 2.65;
      const prob = 1 / (1 + Math.exp(-z));
      row.push(Number(prob.toFixed(4)));
    }
    p.push(row);
  }
  const contour_0_5: [number, number][] = [];
  for (let j = 0; j < 20; j++) {
    const oMid = Number(((orbit_bins[j] + orbit_bins[j + 1]) / 2).toFixed(4));
    const hitIdx = p.findIndex((row) => row[j] >= 0.5);
    if (hitIdx >= 0) {
      contour_0_5.push([delay_bins[hitIdx], oMid]);
    }
  }
  return { version: "grid-v1", delay_bins, orbit_bins, p, contour_0_5 };
}

export function buildScenarioTimeseries(scenario: string, universe: "U0" | "U2" | "U4" = "U4"): TimeseriesPoint[] {
  const pts: TimeseriesPoint[] = [];
  for (let s = 5; s <= 240; s += 5) {
    const sim_ms = s * 1000;
    const inFault = s >= 120 && s <= 195;
    const postFault = s > 195;
    let goodput = 162;
    let queue = 14;
    let checks = 6;
    let util = 0.14;
    let slowdown = 1.0;
    let unknownOpen = 4;
    let resolved = 3.8;

    if (scenario === "S0") {
      goodput = 163 + ((s % 15) - 7) * 0.4;
      queue = 12 + (s % 5);
    } else if (scenario === "S1") {
      // Festive surge: volume rises 1.45x cleanly, no timeouts or switch saturation
      const surge = s >= 110 && s <= 200 ? 1.42 : 1.0;
      goodput = Math.round(162 * surge);
      queue = Math.round(16 * surge);
      checks = Math.round(7 * surge);
      util = Number((0.16 * surge).toFixed(3));
    } else if (scenario === "S3") {
      // Bank B1 slowdown
      if (inFault) {
        const prog = (s - 120) / 75;
        if (universe === "U0") {
          goodput = Math.max(48, Math.round(162 - 110 * prog));
          queue = Math.round(20 + 290 * prog);
          checks = Math.round(10 + 95 * prog);
          util = Number(Math.min(0.98, 0.2 + 0.78 * prog).toFixed(3));
          slowdown = util > 0.8 ? Number((1 + 1.12 * ((util - 0.8) / 0.2) ** 2).toFixed(2)) : 1.0;
          unknownOpen = Math.round(12 + 180 * prog);
          resolved = 8;
        } else if (universe === "U2") {
          goodput = Math.round(136 - 18 * Math.sin(prog * Math.PI));
          queue = Math.round(24 + 95 * Math.sin(prog * Math.PI));
          checks = Math.round(12 + 34 * Math.sin(prog * Math.PI));
          util = Number((0.24 + 0.38 * Math.sin(prog * Math.PI)).toFixed(3));
          unknownOpen = Math.round(10 + 48 * Math.sin(prog * Math.PI));
          resolved = 14;
        } else {
          goodput = Math.round(144 - 12 * Math.sin(prog * Math.PI));
          queue = Math.round(18 + 58 * Math.sin(prog * Math.PI));
          checks = Math.round(9 + 18 * Math.sin(prog * Math.PI));
          util = Number((0.18 + 0.24 * Math.sin(prog * Math.PI)).toFixed(3));
          unknownOpen = Math.round(8 + 26 * Math.sin(prog * Math.PI));
          resolved = 22;
        }
      } else if (postFault && universe === "U0") {
        goodput = 42;
        queue = 340;
        checks = 112;
        util = 0.99;
        slowdown = 2.08;
        unknownOpen = 210;
        resolved = 6;
      }
    } else if (scenario === "S4" || scenario === "S6" || scenario === "S8") {
      // S4 Retry storm / S6 April-2025 verification storm / S8 Payout burst
      if (inFault) {
        const prog = Math.min(1, (s - 120) / 60);
        if (universe === "U0") {
          goodput = Math.max(12, Math.round(162 * (1 - 0.9 * prog)));
          queue = Math.round(18 + 382 * prog);
          checks = Math.round(8 + 145 * prog);
          util = Number(Math.min(1.0, 0.18 + 0.82 * prog).toFixed(3));
          slowdown = util > 0.8 ? Number((1 + 1.12 * ((util - 0.8) / 0.2) ** 2).toFixed(2)) : 1.0;
          unknownOpen = Math.round(10 + 260 * prog);
          resolved = Math.max(3, Math.round(12 * (1 - 0.6 * prog)));
        } else if (universe === "U2") {
          goodput = Math.round(148 - 26 * Math.sin(prog * Math.PI));
          queue = Math.round(22 + 110 * Math.sin(prog * Math.PI));
          checks = Math.round(10 + 38 * Math.sin(prog * Math.PI));
          util = Number((0.22 + 0.42 * Math.sin(prog * Math.PI)).toFixed(3));
          unknownOpen = Math.round(8 + 64 * Math.sin(prog * Math.PI));
          resolved = 19;
        } else {
          // U4: governed status checks + Drunix pushed attestations keep switch below 0.85 knee
          goodput = Math.round(156 - 14 * Math.sin(prog * Math.PI));
          queue = Math.round(16 + 52 * Math.sin(prog * Math.PI));
          checks = Math.round(8 + 19 * Math.sin(prog * Math.PI));
          util = Number((0.18 + 0.28 * Math.sin(prog * Math.PI)).toFixed(3));
          unknownOpen = Math.round(6 + 28 * Math.sin(prog * Math.PI));
          resolved = 28;
        }
      } else if (postFault) {
        const recov = Math.min(1, (s - 195) / 40);
        if (universe === "U0") {
          // Latched metastable congestion collapse under U0
          goodput = 8;
          queue = 400;
          checks = 158;
          util = 1.0;
          slowdown = 2.12;
          unknownOpen = 295;
          resolved = 3;
        } else if (universe === "U2") {
          goodput = Math.round(138 + 24 * recov);
          queue = Math.round(68 * (1 - 0.75 * recov));
          checks = Math.round(28 * (1 - 0.65 * recov));
          util = Number((0.44 * (1 - 0.6 * recov)).toFixed(3));
          unknownOpen = Math.round(32 * (1 - 0.8 * recov));
          resolved = 16;
        } else {
          goodput = Math.round(154 + 9 * recov);
          queue = Math.round(30 * (1 - 0.55 * recov));
          checks = Math.round(14 * (1 - 0.45 * recov));
          util = Number((0.26 * (1 - 0.4 * recov)).toFixed(3));
          unknownOpen = Math.round(12 * (1 - 0.7 * recov));
          resolved = 20;
        }
      }
    }

    pts.push({
      sim_ms,
      goodput_per_s: goodput,
      psp_queue: queue,
      switch_checks_per_s: checks,
      switch_status_util: util,
      switch_slowdown: slowdown,
      unknown_open: unknownOpen,
      unknown_resolved_per_s: resolved,
    });
  }
  return pts;
}

export function buildScenarioBudgets(scenario: string): BudgetPoint[] {
  const out: BudgetPoint[] = [];
  for (let s = 5; s <= 240; s += 5) {
    const inStorm = (scenario === "S3" || scenario === "S4" || scenario === "S6" || scenario === "S8") && s >= 125 && s <= 205;
    const total = inStorm ? 32 : 68;
    out.push({
      sim_ms: s * 1000,
      total_budget_per_s: total,
      by_psp: { P1: Math.round(total * 0.4), P2: Math.round(total * 0.35), P3: Math.round(total * 0.25) },
    });
  }
  return out;
}

export function buildScenarioTicks(
  scenario: string,
  seed = 1,
  universe: "U0" | "U1" | "U2" | "U3" | "U4" = "U4"
): SegmentState[] {
  const run_id = `r-${scenario}-${seed}-${universe}`;
  const ticks: SegmentState[] = [];
  const tickTimes = [
    60_000, 75_000, 90_000, 105_000, 120_000, 125_000, 130_000, 135_000,
    140_000, 145_000, 150_000, 155_000, 160_000, 165_000, 170_000, 175_000, 180_000,
  ];

  for (const tick_sim_ms of tickTimes) {
    const isCalm = scenario === "S0" || scenario === "S1" || tick_sim_ms <= 120_000;
    const prog = isCalm ? 0 : Math.min(1, (tick_sim_ms - 120_000) / 50_000);
    const isS3 = scenario === "S3";
    const isS6 = scenario === "S6";
    const isS8 = scenario === "S8";

    const global_state: SegmentState["global_state"] = isCalm
      ? "MONITORING"
      : prog >= 0.45
      ? "CRITICAL"
      : "WARNING";

    const verdict: SegmentState["localization"]["verdict"] = isCalm
      ? "INSUFFICIENT_EVIDENCE"
      : isS3
      ? "BANK_SIDE"
      : isS6
      ? "SWITCH_STATUS_OVERLOAD"
      : isS8
      ? "ROUTE_SPECIFIC"
      : "PSP_SIDE";

    const primary_segment_id = isCalm
      ? null
      : isS3
      ? "bank:*:B1"
      : isS6
      ? "switch:*:*"
      : isS8
      ? "route:P1:B2"
      : "psp:P1:*";

    const segments: SegmentState["segments"] = [];

    const makeSeg = (
      segment_id: string,
      hotFactor: number,
      isPsp = false,
      pspIdx = 0
    ): SegmentState["segments"][number] => {
      const surge = scenario === "S1" && tick_sim_ms >= 120_000;
      const score = isCalm ? (surge ? 0.14 : 0.06) : Math.min(0.98, Number((0.15 + 0.82 * hotFactor * prog).toFixed(3)));
      const timeout_ratio = isCalm ? 0.008 : Number((0.01 + 0.34 * hotFactor * prog).toFixed(4));
      const near_timeout_ratio = isCalm ? 0.015 : Number((0.02 + 0.42 * hotFactor * prog).toFixed(4));
      const p95_ms = isCalm ? (surge ? 410 : 340) : Math.round(350 + 2450 * hotFactor * prog);
      const raf = isCalm ? 1.02 : Number((1.03 + (universe === "U0" ? 0.95 : 0.36) * hotFactor * prog).toFixed(3));
      const queue_depth = isCalm ? (surge ? 24 : 12) : Math.round(14 + (universe === "U0" ? 240 : 62) * hotFactor * prog);
      const zScale = isCalm ? 0.3 : Number((1.2 + 5.4 * hotFactor * prog).toFixed(2));

      const segState: SegmentState["segments"][number]["state"] =
        score >= 0.75 ? "CRITICAL" : score >= 0.45 ? "WARNING" : "MONITORING";

      const base: SegmentState["segments"][number] = {
        segment_id,
        eligible: true,
        flags: [],
        features: {
          arrival_rate: surge ? 38 : 26,
          fresh_rate: 24,
          raf,
          success_ratio: Number((1 - timeout_ratio).toFixed(4)),
          timeout_ratio,
          near_timeout_ratio,
          reject_ratio: 0.004,
          p50_ms: Math.round(p95_ms * 0.55),
          p95_ms,
          p99_ms: Math.round(p95_ms * 1.25),
          latency_ratio: Number((p95_ms / 340).toFixed(2)),
          pending_count: Math.round(queue_depth * 0.7),
          pending_frac: Number(Math.min(0.95, queue_depth / 120).toFixed(3)),
          queue_depth,
          queue_growth: isCalm ? 0 : Number((hotFactor * 3.2).toFixed(2)),
          utilisation: Number(Math.min(0.99, 0.45 + 0.5 * hotFactor * prog).toFixed(3)),
          queue_delay_est_ms: Math.round(queue_depth * 18),
          orbit_proxy: Number((raf - 1).toFixed(3)),
          status_check_rate: isCalm ? 6 : Math.round(8 + 64 * hotFactor * prog),
          switch_status_util: isCalm ? 0.16 : Number(Math.min(0.99, 0.22 + 0.68 * hotFactor * prog).toFixed(3)),
          load_over_capacity: Number((0.55 + 0.55 * hotFactor * prog).toFixed(3)),
          ledger_open_rate: isCalm ? 0.4 : Number((4.5 * hotFactor * prog).toFixed(2)),
          ledger_unresolved: isCalm ? 2 : Math.round(28 * hotFactor * prog),
        },
        z: {
          timeout_ratio: zScale,
          near_timeout_ratio: Number((zScale * 1.15).toFixed(2)),
          p95_ms: Number((zScale * 1.1).toFixed(2)),
          raf: Number((zScale * 0.9).toFixed(2)),
          queue_depth: Number((zScale * 1.05).toFixed(2)),
        },
        signals: {
          lat: score >= 0.35,
          to: score >= 0.5,
          near_to: score >= 0.3,
          q: score >= 0.4,
          raf: score >= 0.45,
          rej: false,
        },
        surge,
        d0_alert: score >= 0.82,
        d3_score: score,
        state: segState,
      };

      if (isPsp) {
        // S1 stays well below the 0.5 contour; S4/S6/S3 cross or approach contour depending on PSP & universe
        const trailScale = scenario === "S1" ? 0.22 : scenario === "S0" ? 0.12 : hotFactor;
        const maxDelay = universe === "U0" ? 1.65 : 1.18;
        const maxOrbit = universe === "U0" ? 2.35 : 1.55;
        const delay_frac = Number(
          Math.min(1.95, 0.14 + (pspIdx * 0.05) + (isCalm ? (surge ? 0.18 : 0.04) : maxDelay * trailScale * prog)).toFixed(3)
        );
        const orbit_frac = Number(
          Math.min(2.9, 0.18 + (pspIdx * 0.06) + (isCalm ? (surge ? 0.15 : 0.05) : maxOrbit * trailScale * prog)).toFixed(3)
        );
        const zLogit = 3.2 * (delay_frac / 2.0) + 2.8 * (orbit_frac / 3.0) - 2.65;
        const p_stuck = Number((1 / (1 + Math.exp(-zLogit))).toFixed(3));
        base.p_stuck = p_stuck;
        base.forecast_state = p_stuck >= 0.5 ? "CRITICAL" : p_stuck >= 0.3 ? "WATCH" : "CALM";
        base.phase_point = { delay_frac, orbit_frac };
        base.countdown_s_estimate = p_stuck >= 0.5 ? 0 : Math.max(8, Math.round((0.5 - p_stuck) * 95));
      }
      return base;
    };

    segments.push(makeSeg("platform:*:*", isCalm ? 0.1 : 0.85));
    segments.push(makeSeg("switch:*:*", isS6 ? 1.0 : 0.65));

    PSPS.forEach((p, idx) => {
      const hotPsp = scenario === "S4" ? (p === "P1" ? 1.0 : p === "P2" ? 0.82 : 0.64) : isS6 ? 0.92 : 0.78;
      segments.push(makeSeg(`psp:${p}:*`, hotPsp, true, idx));
    });

    BANKS.forEach((b) => {
      const hotBank = isS3 ? (b === "B1" ? 1.0 : 0.12) : b === "B1" || b === "B2" ? 0.75 : 0.45;
      segments.push(makeSeg(`bank:*:${b}`, hotBank));
    });

    PSPS.forEach((p) => {
      BANKS.forEach((b) => {
        let hotCell = 0.2;
        if (isS3) hotCell = b === "B1" ? 0.96 : 0.12;
        else if (isS8) hotCell = p === "P1" && b === "B2" ? 0.98 : 0.18;
        else if (scenario === "S4") hotCell = p === "P1" ? 0.92 : p === "P2" ? 0.74 : 0.52;
        else if (isS6) hotCell = 0.84;
        segments.push(makeSeg(`route:${p}:${b}`, hotCell));
      });
    });

    // Detector race flags (S4/S3/S6/S8 show 4 distinct flags: D3 earliest, then D2, D1, D0)
    const detector_alerts: SegmentState["detector_alerts"] = [];
    if (!isCalm) {
      const targetSeg = primary_segment_id ?? "platform:*:*";
      if (tick_sim_ms >= 125_000) {
        detector_alerts.push({ detector: "D3", segment_id: targetSeg, first_alert_sim_ms: 125_000 });
      }
      if (tick_sim_ms >= 135_000) {
        detector_alerts.push({ detector: "D2", segment_id: targetSeg, first_alert_sim_ms: 135_000 });
      }
      if (tick_sim_ms >= 145_000) {
        detector_alerts.push({ detector: "D1", segment_id: targetSeg, first_alert_sim_ms: 145_000 });
      }
      if (tick_sim_ms >= 160_000) {
        detector_alerts.push({ detector: "D0", segment_id: "platform:*:*", first_alert_sim_ms: 160_000 });
      }
    }

    ticks.push({
      schema_version: 1,
      run_id,
      universe,
      tick_sim_ms,
      global_state,
      segments,
      localization: {
        verdict,
        primary_segment_id,
        candidates: primary_segment_id ? [{ segment_id: primary_segment_id, share: 0.78, lift: 4.1 }] : [],
        confidence: isCalm ? 0.15 : 0.91,
        total_excess: isCalm ? 0 : Math.round(48 * prog),
      },
      detector_alerts,
      incidents: [],
    });
  }
  return ticks;
}

export function buildScenarioRec(scenario: string, seed = 1): Recommendation | null {
  if (scenario === "S0" || scenario === "S1") return null;
  const isS3 = scenario === "S3";
  const isS6 = scenario === "S6";
  const segment_id = isS3 ? "bank:*:B1" : isS6 ? "switch:*:*" : scenario === "S8" ? "route:P1:B2" : "psp:P1:*";
  const verdict = isS3
    ? "BANK_SIDE"
    : isS6
    ? "SWITCH_STATUS_OVERLOAD"
    : scenario === "S8"
    ? "ROUTE_SPECIFIC"
    : "PSP_SIDE";

  return {
    rec_id: `rec-${scenario.toLowerCase()}-0001`,
    incident_id: `inc-${scenario.toLowerCase()}-0001`,
    run_id: `r-${scenario}-${seed}-U4`,
    created_sim_ms: 130_000,
    segment_id,
    severity: "CRITICAL",
    verdict,
    p_stuck: isS3 ? 0.68 : 0.76,
    confidence: 0.89,
    countdown_s_estimate: 25,
    reasons: [
      { code: "NEAR_TIMEOUT_UP", observed: 0.28, baseline: 0.02, z: 5.4 },
      { code: "QUEUE_GROWING", observed: 72, baseline: 14, z: 4.6 },
      { code: "RAF_UP", observed: 1.38, baseline: 1.02, z: 3.9 },
    ],
    actions: [
      {
        action_type: "THROTTLE_RETRIES",
        params: { retry_budget_frac: 0.25, backoff_ms: 4000 },
        scope_segment_id: segment_id,
        eligible: true,
        blocked_by: null,
        advisory_kind: "SLOW_RETRIES",
        side_effect: "Caps client retry rate to 25% of baseline and spaces retries by 4 s.",
        rollback_condition: "Auto-proposes rollback after 6 consecutive clean ticks (30 s).",
      },
      {
        action_type: "DEFER_CHECKS",
        params: { first_check_delay_s: 90, min_interval_s: 45, max_checks: 3 },
        scope_segment_id: segment_id,
        eligible: true,
        blocked_by: null,
        advisory_kind: "DEFER_CHECKS",
        side_effect: "Paces switch status checks (first check at 90 s, interval 45 s) while Drunix pushes settlements.",
        rollback_condition: "Auto-proposes rollback after 6 consecutive clean ticks (30 s).",
      },
      {
        action_type: "SHIFT_TRAFFIC",
        params: { shift_frac: 0.5 },
        scope_segment_id: segment_id,
        eligible: false,
        blocked_by:
          "Blocked: beneficiary bank B1 is the destination across all PSPs; shifting PSP routes cannot bypass a slow beneficiary bank.",
        advisory_kind: "DO_NOT_SHIFT",
        side_effect: "Publishes DO_NOT_SHIFT advisory on Drunix so peer PSPs do not trigger a failover stampede.",
        rollback_condition: "Expires or revokes when bank B1 latency returns to baseline.",
      },
    ],
    status: "PENDING",
    model_versions: {
      detector: "d3-rules-v1",
      forecaster: "grid-v1",
      localizer: "lift-v1",
      policy: "rules-v1",
    },
    features_sha256: "a8f5f167f44f4964e6c998dee827110c84b6b8e2f82e39a07b21011898b2c001",
  };
}

export function buildMockArenaData(): {
  results: RunResult[];
  series: Record<string, TimeseriesPoint[]>;
  sweep: OperatorSweepRow[];
} {
  const scenarios: RunResult["scenario"][] = ["S6", "S4", "S3", "S1"];
  const universes: ("U0" | "U2" | "U4")[] = ["U0", "U2", "U4"];
  const results: RunResult[] = [];
  const series: Record<string, TimeseriesPoint[]> = {};

  for (const sc of scenarios) {
    for (const u of universes) {
      series[`${sc}:${u}`] = buildScenarioTimeseries(sc, u);
      for (let seed = 1; seed <= 5; seed++) {
        const jit = (seed - 3) * 0.015;
        const isSurge = sc === "S1";
        const u0Stuck = !isSurge && u === "U0";
        const isU2 = u === "U2";
        results.push({
          run_id: `r-${sc}-${seed}-${u}`,
          scenario: sc,
          seed,
          universe: u,
          config_sha256: "calibrated-v1",
          sim_version: "0.2.0",
          metrics: {
            goodput_min_frac: isSurge
              ? 0.99
              : u0Stuck
              ? Number(Math.max(0, 0.04 + jit).toFixed(3))
              : isU2
              ? Number((0.91 + jit).toFixed(3))
              : Number((0.97 + jit).toFixed(3)),
            peak_queue: isSurge
              ? 28
              : u0Stuck
              ? 400
              : isU2
              ? 132 + seed * 3
              : 68 + seed * 2,
            excess_retries: isSurge
              ? 18
              : u0Stuck
              ? 5840 + seed * 90
              : isU2
              ? 1420 + seed * 35
              : 490 + seed * 18,
            recovery_time_s: isSurge ? 0 : u0Stuck ? null : isU2 ? 35 + seed : 12 + seed,
            unique_success: isSurge ? 51200 : u0Stuck ? 24800 : isU2 ? 46900 : 48750,
            duplicate_commits: 0,
            peak_switch_checks_per_s: isSurge ? 11 : u0Stuck ? 158 + seed * 2 : isU2 ? 48 + seed : 26 + seed,
            switch_checks_total: isSurge ? 1850 : u0Stuck ? 19400 + seed * 200 : isU2 ? 5200 + seed * 60 : 2450 + seed * 40,
            switch_checks_per_unknown: isSurge ? 1.0 : u0Stuck ? 6.8 : isU2 ? 2.4 : 0.72,
            unknowns_total: isSurge ? 40 : u0Stuck ? 2850 : isU2 ? 890 : 410,
            median_resolve_s: isSurge ? 2.1 : u0Stuck ? 94.0 : isU2 ? 28.5 : 6.4,
            p95_resolve_s: isSurge ? 5.0 : u0Stuck ? 180.0 : isU2 ? 64.0 : 14.2,
            escalated: isSurge ? 0 : u0Stuck ? 640 : isU2 ? 42 : 4,
            harmful_failovers: isSurge ? 0 : sc === "S3" && u === "U0" ? 3 : 0,
            tat_breaches: isSurge ? 0 : u0Stuck ? 412 : isU2 ? 19 : 0,
          },
          ground_truth: isSurge
            ? []
            : [
                {
                  incident_id: `gt-${sc}-1`,
                  onset_ms: 120_000,
                  end_ms: 195_000,
                  level: sc === "S3" ? "bank" : sc === "S6" ? "switch" : "psp",
                  psp: sc === "S4" ? "P1" : null,
                  bank: sc === "S3" ? "B1" : null,
                  kind: sc,
                  magnitude: 0.65,
                  is_incident: true,
                },
              ],
          files: { events: `data/runs/r-${sc}-${seed}-${u}/events.jsonl` },
        });
      }
    }
  }

  const sweep: OperatorSweepRow[] = [
    { operator_delay_s: 5, recovery_time_s: 10.0, excess_retries: 3502.0, peak_queue: 269.0, goodput_min_frac: 0.985 },
    { operator_delay_s: 15, recovery_time_s: 18.0, excess_retries: 3537.0, peak_queue: 312.0, goodput_min_frac: 0.962 },
    { operator_delay_s: 30, recovery_time_s: 28.0, excess_retries: 3816.0, peak_queue: 355.0, goodput_min_frac: 0.924 },
    { operator_delay_s: 60, recovery_time_s: 52.0, excess_retries: 4427.0, peak_queue: 400.0, goodput_min_frac: 0.815 },
    { operator_delay_s: 120, recovery_time_s: 95.0, excess_retries: 4980.0, peak_queue: 400.0, goodput_min_frac: 0.64 },
  ];

  return { results, series, sweep };
}
