/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface BatchRunResultM2M3TrainingM5Arena {
  run_id: string;
  scenario: "S0" | "S1" | "S2" | "S3" | "S4" | "S5" | "S6" | "S7" | "S8";
  seed: number;
  universe: "U0" | "U1" | "U2" | "U3" | "U4";
  config_sha256: string;
  sim_version: string;
  metrics: {
    peak_queue?: number | null;
    excess_retries?: number | null;
    recovery_time_s?: number | null;
    unique_success?: number | null;
    duplicate_commits?: number | null;
    peak_switch_checks_per_s?: number | null;
    switch_checks_total?: number | null;
    switch_checks_per_unknown?: number | null;
    unknowns_total?: number | null;
    median_resolve_s?: number | null;
    p95_resolve_s?: number | null;
    escalated?: number | null;
    harmful_failovers?: number | null;
    tat_breaches?: number | null;
    goodput_min_frac?: number | null;
  };
  ground_truth: {
    incident_id: string;
    onset_ms: number;
    end_ms: number;
    level: "psp" | "bank" | "route" | "switch" | "platform";
    psp?: string | null;
    bank?: string | null;
    kind: string;
    magnitude?: number;
    is_incident: boolean;
  }[];
  files: {
    events: string;
    ground_truth?: string;
    ticks?: string;
    timeseries?: string;
  };
}
