// SSE per docs/01_SYSTEM.md §9: monotonic ids, Last-Event-ID replay from a ring (>= 50 000), `reset` for ids
// that fell off the ring, `: hb` heartbeat every 5 s.
import type { ServerResponse } from "node:http";
import { config } from "./config.ts";

export type Msg = { id: number; event: string; data: string };

export class SseHub {
  private ring: Msg[] = [];
  private next = 1;
  private clients = new Set<ServerResponse>();

  publish(event: string, data: unknown): number {
    const m = { id: this.next++, event, data: JSON.stringify(data) };
    this.ring.push(m);
    if (this.ring.length > config.sseRing) this.ring.splice(0, this.ring.length - config.sseRing);
    for (const c of this.clients) c.write(SseHub.fmt(m));
    return m.id;
  }

  static fmt(m: Msg): string {
    return `id: ${m.id}\nevent: ${m.event}\ndata: ${m.data}\n\n`;
  }

  /** Replay after `lastEventId` (or `reset` if too old), then stream live. */
  attach(res: ServerResponse, lastEventId?: string): void {
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
    for (const chunk of this.replay(lastEventId)) res.write(chunk);
    this.clients.add(res);
    const hb = setInterval(() => res.write(": hb\n\n"), config.heartbeatMs);
    res.on("close", () => { clearInterval(hb); this.clients.delete(res); });
  }

  replay(lastEventId?: string): string[] {
    const last = lastEventId ? Number(lastEventId) : NaN;
    if (!Number.isFinite(last)) return [];
    const oldest = this.ring.length ? this.ring[0].id : this.next;
    if (last + 1 < oldest) return [SseHub.fmt({ id: this.next - 1, event: "reset", data: "{}" })];
    return this.ring.filter((m) => m.id > last).map(SseHub.fmt);
  }

  clear(): void {
    this.ring = [];
  }
}
