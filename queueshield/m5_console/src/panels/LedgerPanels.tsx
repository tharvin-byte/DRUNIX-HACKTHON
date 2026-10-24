// DecisionLog and DrunixPanel (docs/M5_CONSOLE.md §3). Never fake a ledger number: offline says so (pitfall 1).
import { useEffect, useState } from "react";
import { config } from "../config";
import type { NetworkInfo } from "../contracts";
import { useQs } from "../store";
import { TEXT } from "../text/claims";

export function DecisionLog() {
  const decisions = useQs((s) => s.decisions);
  const source = useQs((s) => s.sources.control);
  return (
    <section className="panel" data-testid="decision-log">
      <h3>
        Decision log <span className={`badge ${source}`}>{source.toUpperCase()}</span>
      </h3>
      {decisions.length === 0 && <p className="muted">no decisions yet</p>}
      <table>
        <tbody>
          {decisions.map((d) => (
            <tr key={d.rec_id}>
              <td>{d.rec_id}</td>
              <td>{d.operator}</td>
              <td>{d.decision ?? d.status}</td>
              <td>{d.action_ids.length} actions</td>
              <td>
                {d.ledger_tx
                  ? `tx ${d.ledger_tx.slice(0, 8)}${d.ledger_block ? ` · block ${d.ledger_block}` : ""}`
                  : TEXT.recordingOnLedger}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const MOCK_NET: NetworkInfo = {
  mode: "mock",
  channel: "mychannel",
  chaincode: { name: "queueshield", version: "1.0", sequence: 1 },
  height: 41,
  orgs: [
    { mspId: "Org1MSP", litePeers: ["lp0.org1"], committingPeers: ["cp0.org1"], validationServices: ["vs0.org1"] },
    { mspId: "Org2MSP", litePeers: ["lp0.org2"], committingPeers: ["cp0.org2"], validationServices: ["vs0.org2"] },
  ],
};

export function DrunixPanel() {
  const source = useQs((s) => s.sources.ledger);
  const events = useQs((s) => s.ledgerEvents);
  const [net, setNet] = useState<NetworkInfo | null>(null);
  useEffect(() => {
    if (source !== "live") return;
    let alive = true;
    const poll = () =>
      fetch(`${config.ledgerUrl}/v1/network`)
        .then((r) => (r.ok ? r.json() : null))
        .then((n) => alive && setNet(n))
        .catch(() => alive && setNet(null));
    poll();
    const t = setInterval(poll, config.networkPollMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [source]);

  const isOffline = source === "offline";
  const maxBlock = events.reduce((m, e) => Math.max(m, e.block_number ?? 0), 41);
  const activeNet = isOffline ? null : net ?? (source === "mock" ? { ...MOCK_NET, height: maxBlock } : null);

  const advisories = events.filter((e) => e.name === "AdvisoryIssued");
  const breaches = events.filter((e) => e.name === "TATBreach").length;
  const resolved = events.filter((e) => e.name === "PaymentUpdated").length;

  return (
    <section className="panel" data-testid="drunix-panel">
      <h3>
        Drunix ledger{" "}
        <span className={`badge ${source}`}>{isOffline ? TEXT.ledgerOffline : source.toUpperCase()}</span>
      </h3>
      {activeNet ? (
        <>
          <p className="small">
            {activeNet.mode} · channel <code>{activeNet.channel}</code> · block height{" "}
            <strong>{activeNet.height}</strong>
          </p>
          <div className="row" style={{ marginBottom: 6 }}>
            {activeNet.orgs.map((o) => (
              <span key={o.mspId} className="chip">
                {o.mspId}: LP {o.litePeers?.length ?? 0} · CP {o.committingPeers?.length ?? 0} · VS{" "}
                {o.validationServices?.length ?? 0}
              </span>
            ))}
          </div>
          <p className="small">
            TAT breaches: <strong>{breaches}</strong> · Outcomes attested: <strong>{resolved}</strong>
          </p>
          <div className="small">
            Active advisories:
            <ul>
              {advisories.slice(-5).map((e) => {
                const p = e.payload as { id?: string; kind?: string; segmentId?: string };
                return (
                  <li key={e.event_id}>
                    <code>{p.id}</code> · {p.kind} · <code>{p.segmentId}</code> (block {e.block_number})
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      ) : (
        <>
          <p className="muted">{TEXT.ledgerOffline}</p>
          <p className="small">TAT breaches: —</p>
        </>
      )}
    </section>
  );
}
