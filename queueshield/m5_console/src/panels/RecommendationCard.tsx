// RecommendationCard (docs/M5_CONSOLE.md §2, M5-T02).
// - Every eligible action has a checkbox (checked by default).
// - Every ineligible action renders disabled with its `blocked_by` reason visible in red/amber (U-4).
// - Approve all / Approve selected / Reject buttons + keyboard shortcuts A / S / R + optional note (<=280 chars).
import { useEffect, useState } from "react";
import { config } from "../config";
import { postDecision } from "../connect";
import type { Recommendation } from "../contracts";
import { useQs } from "../store";
import { TEXT } from "../text/claims";
import { buildDecision, type RecAction, selectable } from "./decisionLogic";

export function RecommendationCard() {
  const recs = useQs((s) => s.recs);
  const src = useQs((s) => s.sources.control);
  const upsertRec = useQs((s) => s.upsertRec);
  const addDecision = useQs((s) => s.addDecision);

  const pending = Object.values(recs).filter((r) => r.status === "PENDING");
  const rec: Recommendation | undefined = pending[0] ?? Object.values(recs)[0];

  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [operator, setOperator] = useState<string>(config.operators[0] ?? "saran");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const isChecked = (a: RecAction) => selectable(a) && (selected[a.action_type] ?? true);

  async function submit(kind: "APPROVE_ALL" | "APPROVE_SELECTED" | "REJECT") {
    if (!rec || busy || rec.status !== "PENDING") return;
    setBusy(true);
    const chosen = rec.actions.filter(isChecked).map((a) => a.action_type);
    const decisionPayload = buildDecision(rec, kind, chosen, operator.trim() || "saran", note.trim());
    const res = await postDecision(decisionPayload);
    setBusy(false);
    if (res.ok) {
      const b = res.body as {
        status: Recommendation["status"];
        decision_id?: string;
        action_ids?: string[];
        ledger?: { decision_tx?: string | null; block_number?: number | null };
      };
      upsertRec({ ...rec, status: b.status });
      addDecision({
        rec_id: rec.rec_id,
        decision_id: b.decision_id,
        operator: operator.trim() || "saran",
        decision: kind,
        status: b.status,
        action_ids: b.action_ids ?? [],
        ledger_tx: b.ledger?.decision_tx ?? null,
        ledger_block: b.ledger?.block_number ?? null,
      });
    }
  }

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (!rec || rec.status !== "PENDING" || busy) return;
      const k = ev.key.toUpperCase();
      if (k === "A") {
        ev.preventDefault();
        void submit("APPROVE_ALL");
      } else if (k === "S") {
        ev.preventDefault();
        void submit("APPROVE_SELECTED");
      } else if (k === "R") {
        ev.preventDefault();
        void submit("REJECT");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!rec) {
    return (
      <section className="panel" aria-label="Recommendation">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3>Recommendation</h3>
          <span className={`badge ${src}`}>{src.toUpperCase()}</span>
        </div>
        <p className="muted">No active recommendation — controller is watching.</p>
      </section>
    );
  }

  const pStuck = rec.p_stuck ?? 0;

  return (
    <section
      className={`panel ${rec.severity === "CRITICAL" ? "sev-critical" : "sev-warning"}`}
      aria-label="Recommendation"
      data-testid="recommendation-card"
    >
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          Recommendation <code>{rec.rec_id}</code> · <span>{rec.severity}</span>
        </h3>
        <span className={`badge ${src}`}>{src.toUpperCase()}</span>
      </div>
      <div className="row small" style={{ marginBottom: 6 }}>
        <span>
          segment <code>{rec.segment_id}</code>
        </span>
        <span>
          verdict <strong>{rec.verdict}</strong>
        </span>
        <span>
          P(stuck) <strong>{(pStuck * 100).toFixed(0)}%</strong>
        </span>
        {rec.countdown_s_estimate != null && (
          <span>
            ~{rec.countdown_s_estimate}s to threshold ({TEXT.countdownCaveat})
          </span>
        )}
        <span className="chip">{rec.status}</span>
      </div>
      <div className="small muted" style={{ marginBottom: 6 }}>
        {TEXT.reasonsCaveat}:{" "}
        {rec.reasons.map((r) => `${r.code} (z=${(r.z ?? 0).toFixed(1)})`).join(", ") || "policy rollback condition met"}
      </div>
      <ul className="actions">
        {rec.actions.map((a) => (
          <li key={a.action_type} className={a.eligible ? "eligible" : "blocked"} data-testid={`action-${a.action_type}`}>
            <label>
              <input
                type="checkbox"
                role="checkbox"
                aria-label={a.action_type}
                disabled={!a.eligible}
                checked={isChecked(a)}
                onChange={(e) => setSelected({ ...selected, [a.action_type]: e.target.checked })}
              />{" "}
              <strong>{a.action_type}</strong>
              {a.advisory_kind && <span className="muted small"> · advisory {a.advisory_kind}</span>}
            </label>
            <div className="small">{a.side_effect}</div>
            <div className="muted small">rollback: {a.rollback_condition}</div>
            {!a.eligible && a.blocked_by && (
              <div className="danger small" role="note" data-testid={`blocked-${a.action_type}`}>
                🔒 {a.blocked_by}
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="row" style={{ marginBottom: 8 }}>
        <label className="small">
          Operator{" "}
          <select aria-label="Operator handle" value={operator} onChange={(e) => setOperator(e.target.value)}>
            {config.operators.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
        </label>
        <label className="small" style={{ flex: 1 }}>
          Note{" "}
          <input
            type="text"
            aria-label="Decision note"
            placeholder="Reason or runbook reference (<= 280 chars)"
            value={note}
            maxLength={280}
            onChange={(e) => setNote(e.target.value)}
            style={{ width: "75%" }}
          />
        </label>
      </div>
      <div className="row">
        <button disabled={busy || rec.status !== "PENDING"} onClick={() => submit("APPROVE_ALL")} title="Shortcut: A">
          Approve all (A)
        </button>
        <button
          disabled={busy || rec.status !== "PENDING"}
          onClick={() => submit("APPROVE_SELECTED")}
          title="Shortcut: S"
        >
          Approve selected (S)
        </button>
        <button disabled={busy || rec.status !== "PENDING"} onClick={() => submit("REJECT")} title="Shortcut: R">
          Reject (R)
        </button>
      </div>
    </section>
  );
}
