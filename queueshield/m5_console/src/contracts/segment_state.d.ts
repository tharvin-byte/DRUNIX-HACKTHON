/* Generated from contracts/schemas by scripts/gen-types.mjs. Do not edit. */

export interface PerTickDetectionSnapshotM3M4M5 {
  schema_version: 1;
  run_id: string;
  universe: "U0" | "U1" | "U2" | "U3" | "U4";
  tick_sim_ms: number;
  global_state: "MONITORING" | "WARNING" | "CRITICAL" | "RECOVERING" | "DEGRADED_MONITORING";
  segments: {
    segment_id: string;
    eligible: boolean;
    flags: ("warming_up" | "low_volume" | "no_data" | "model_degraded" | "baseline_frozen")[];
    features: {
      arrival_rate?: number | null;
      fresh_rate?: number | null;
      raf?: number | null;
      success_ratio?: number | null;
      timeout_ratio?: number | null;
      near_timeout_ratio?: number | null;
      reject_ratio?: number | null;
      p50_ms?: number | null;
      p95_ms?: number | null;
      p99_ms?: number | null;
      latency_ratio?: number | null;
      pending_count?: number | null;
      pending_frac?: number | null;
      queue_depth?: number | null;
      queue_growth?: number | null;
      utilisation?: number | null;
      queue_delay_est_ms?: number | null;
      orbit_proxy?: number | null;
      status_check_rate?: number | null;
      switch_status_util?: number | null;
      load_over_capacity?: number | null;
      ledger_open_rate?: number | null;
      ledger_unresolved?: number | null;
    };
    z: {
      arrival_rate?: number | null;
      fresh_rate?: number | null;
      raf?: number | null;
      success_ratio?: number | null;
      timeout_ratio?: number | null;
      near_timeout_ratio?: number | null;
      reject_ratio?: number | null;
      p50_ms?: number | null;
      p95_ms?: number | null;
      p99_ms?: number | null;
      latency_ratio?: number | null;
      pending_count?: number | null;
      pending_frac?: number | null;
      queue_depth?: number | null;
      queue_growth?: number | null;
      utilisation?: number | null;
      queue_delay_est_ms?: number | null;
      orbit_proxy?: number | null;
      status_check_rate?: number | null;
      switch_status_util?: number | null;
      load_over_capacity?: number | null;
      ledger_open_rate?: number | null;
      ledger_unresolved?: number | null;
    };
    signals: {
      lat: boolean;
      to: boolean;
      near_to: boolean;
      q: boolean;
      raf: boolean;
      rej: boolean;
    };
    surge: boolean;
    d0_alert: boolean;
    d3_score: number;
    state: "MONITORING" | "WARNING" | "CRITICAL" | "RECOVERING" | "DEGRADED_MONITORING";
    p_stuck?: number | null;
    forecast_state?: "CALM" | "WATCH" | "CRITICAL" | null;
    phase_point?: {
      delay_frac?: number;
      orbit_frac?: number;
    } | null;
    countdown_s_estimate?: number | null;
  }[];
  localization: {
    verdict:
      | "PSP_SIDE"
      | "BANK_SIDE"
      | "ROUTE_SPECIFIC"
      | "SWITCH_STATUS_OVERLOAD"
      | "MULTI_FAULT"
      | "PLATFORM_WIDE"
      | "INSUFFICIENT_EVIDENCE";
    primary_segment_id?: string | null;
    candidates: {
      segment_id?: string;
      share?: number;
      lift?: number;
    }[];
    confidence: number;
    total_excess: number;
  };
  detector_alerts: {
    detector: "D0" | "D1" | "D2" | "D3";
    segment_id: string;
    first_alert_sim_ms: number;
  }[];
  incidents?: IncidentM3M4M5[];
}
export interface IncidentM3M4M5 {
  incident_id: string;
  run_id: string;
  segment_id: string;
  state: "OPEN" | "MITIGATING" | "RECOVERING" | "CLOSED";
  severity: "WARNING" | "CRITICAL";
  opened_sim_ms: number;
  updated_sim_ms: number;
  closed_sim_ms?: number | null;
  verdict:
    | "PSP_SIDE"
    | "BANK_SIDE"
    | "ROUTE_SPECIFIC"
    | "SWITCH_STATUS_OVERLOAD"
    | "MULTI_FAULT"
    | "PLATFORM_WIDE"
    | "INSUFFICIENT_EVIDENCE";
  p_stuck?: number | null;
  countdown_s_estimate?: number | null;
  reasons: Reason[];
  confidence: number;
  model_versions: ModelVersions;
  features_sha256: string;
}
export interface Reason {
  code:
    | "TIMEOUT_UP"
    | "NEAR_TIMEOUT_UP"
    | "LATENCY_UP"
    | "RAF_UP"
    | "QUEUE_GROWING"
    | "REJECTS_UP"
    | "PENDING_BACKLOG"
    | "SWITCH_STATUS_SATURATED"
    | "LEDGER_UNRESOLVED_UP";
  observed?: number;
  baseline?: number;
  z?: number;
}
export interface ModelVersions {
  detector?: string;
  forecaster?: string;
  localizer?: string;
  policy?: string;
}
