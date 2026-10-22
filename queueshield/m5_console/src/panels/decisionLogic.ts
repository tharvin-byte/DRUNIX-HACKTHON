// Pure decision-card logic (tested in tests/decision.test.ts). Blocked actions can never be selected (U-4, SI-2).
import type { Decision, Recommendation } from "../contracts";

export type RecAction = Recommendation["actions"][number];

export function selectable(a: RecAction): boolean {
  return a.eligible === true;
}

export function toggle(selected: string[], a: RecAction): string[] {
  if (!selectable(a)) return selected;
  return selected.includes(a.action_type) ? selected.filter((x) => x !== a.action_type) : [...selected, a.action_type];
}

export function buildDecision(rec: Recommendation, kind: Decision["decision"], selected: string[], operator: string,
  note?: string): Decision {
  const eligible = new Set(rec.actions.filter(selectable).map((a) => a.action_type));
  const chosen = kind === "APPROVE_SELECTED" ? selected.filter((t) => eligible.has(t as RecAction["action_type"])) : [];
  const d: Decision = { rec_id: rec.rec_id, decision: kind, operator, actions_selected: chosen as Decision["actions_selected"] };
  if (note) d.note = note.slice(0, 280);
  return d;
}
