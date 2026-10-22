// Resilient SSE client (docs/M5_CONSOLE.md §4).
// - Resume: the browser's EventSource reconnects by itself and sends the Last-Event-ID header (servers replay from
//   their ring). We only rebuild the connection, with exponential backoff 0.5-8 s, once the browser has given up
//   (readyState CLOSED); a rebuilt connection starts from "now" because EventSource cannot set headers.
// - Watchdog: the stream is marked stale when nothing (not even a `: hb` heartbeat) arrives for 15 s.
// - Rows are de-duplicated by event id in the store, so a replay never adds duplicate rows (U-5).
import { config } from "../config";

export type StreamStatus = "connecting" | "live" | "stale" | "offline";

export interface StreamHandle {
  close(): void;
}

export function backoffMs(attempt: number, rand: () => number = Math.random): number {
  const base = Math.min(config.backoffMaxMs, config.backoffMinMs * 2 ** attempt);
  return base / 2 + rand() * (base / 2);                    // jitter is display-side only, never logic
}

export function openStream(url: string, events: string[], onMessage: (event: string, data: unknown, id: string) => void,
  onStatus: (s: StreamStatus) => void): StreamHandle {
  let es: EventSource | null = null;
  let attempt = 0;
  let closed = false;
  let lastSeen = Date.now();
  const watchdog = setInterval(() => {
    if (!closed && es?.readyState === EventSource.OPEN && Date.now() - lastSeen > config.staleAfterMs) onStatus("stale");
  }, 1000);

  const connect = () => {
    if (closed) return;
    onStatus("connecting");
    es = new EventSource(url);
    es.onopen = () => { attempt = 0; lastSeen = Date.now(); onStatus("live"); };
    for (const ev of events) {
      es.addEventListener(ev, (m) => {
        const msg = m as MessageEvent<string>;
        lastSeen = Date.now();
        try { onMessage(ev, JSON.parse(msg.data), msg.lastEventId); } catch { /* invalid JSON dropped, never crashes */ }
      });
    }
    es.onerror = () => {
      onStatus("offline");
      if (es?.readyState === EventSource.CLOSED) setTimeout(connect, backoffMs(attempt++));
    };
  };
  connect();
  return { close() { closed = true; clearInterval(watchdog); es?.close(); } };
}
