// DecisionLog and DrunixPanel (docs/M5_CONSOLE.md §3). Never fake a ledger number: offline says so (pitfall 1).
import { useEffect, useState } from "react";
import { config } from "../config";
import type { NetworkInfo } from "../contracts";
import { useQs } from "../store";
import { TEXT } from "../text/claims";

export function DecisionLog() {
  const decisions = useQs((s) => s.decisions);
  return (
    <section className="panel">
      <h3>Decision log</h3>
      {decisions.length === 0 && <p className="muted">no decisions yet</p>}
      <table>
        <tbody>
          {decisions.map((d) => (
            <tr key={d.rec_id}>
              <td>{d.rec_id}</td><td>{d.operator}</td><td>{d.decision ?? d.status}</td>
              <td>{d.action_ids.length} actions</td>
              <td>{d.ledger_tx ? `tx ${d.ledger_tx.slice(0, 8)}${d.ledger_block ? ` · block ${d.ledger_block}` : ""}` : TEXT.recordingOnLedger}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function DrunixPanel() {
  const source = useQs((s) => s.sources.ledger);
  const events = useQs((s) => s.ledgerEvents);
  const [net, setNet] = useState<NetworkInfo | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = () => fetch(`${config.ledgerUrl}/v1/network`).then((r) => r.json())
      .then((n) => alive && setNet(n)).catch(() => alive && setNet(null));
    poll();
    const t = setInterval(poll, config.networkPollMs);
    return () => { alive = false; clearInterval(t); };
  }, []);
  const advisories = events.filter((e) => e.name === "AdvisoryIssued");
  const breaches = events.filter((e) => e.name === "TATBreach").length;
  return (
    <section className="panel">
      <h3>Drunix ledger <span className={`badge ${source}`}>{source === "offline" ? TEXT.ledgerOffline : source.toUpperCase()}</span></h3>
      {net ? (
        <>
          <p>{net.mode} · channel {net.channel} · block height {net.height}</p>
          <div className="row">{net.orgs.map((o) => <span key={o.mspId} className="chip">{o.mspId}: LP {o.litePeers?.length ?? 0} · CP {o.committingPeers?.length ?? 0} · VS {o.validationServices?.length ?? 0}</span>)}</div>
        </>
      ) : <p className="muted">{TEXT.ledgerOffline}</p>}
      <p>TAT breaches: {source === "offline" ? "—" : breaches}</p>
      <p>Active advisories:</p>
      <ul>{advisories.slice(-5).map((e) => {
        const p = e.payload as { id?: string; kind?: string; segmentId?: string };
        return <li key={e.event_id}>{p.id} {p.kind} {p.segmentId}</li>;
      })}</ul>
    </section>
  );
}
