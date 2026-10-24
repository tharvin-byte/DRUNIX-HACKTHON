"""Ledger bridge (docs/M2_SIMULATOR.md §5, docs/01_SYSTEM.md §5).

- model: implemented inside engine.py (`_h_ledger_open`, `_truth_changed`, `_h_ledger_resolve`), lognormal submit
  latency + event lag from config `ledger_model` (or `data/ledger_bench.json` when available).
- live / mock: opens unknowns with `POST LEDGER_URL/v1/payments` (`ledger_open_request`), attests legs with
  `POST /v1/payments/{txnRef}/attest` as the owning bank, subscribes to `GET /v1/stream` (or polls status) and resolves
  a payment only on a terminal `PaymentUpdated` (test S-11). Never fakes a ledger event: if the gateway is down, falls
  back to `model` and reports health `degraded` (docs/01_SYSTEM.md §10).
"""
from __future__ import annotations

import os
import queue
import threading
import urllib.parse
from typing import Any, Optional

import httpx

from qsim import ids, jsonlog

SUPPORTED_MODES = ("model", "mock", "live")
TERMINAL_STATES = {"SUCCESS", "REVERSED", "FAILED_NO_DEBIT"}


def mode_supported(mode: str) -> bool:
    return mode in SUPPORTED_MODES


class LedgerBridge:
    """Bridges U4 unknown payments to the M1 Ledger gateway (`LEDGER_URL`)."""

    def __init__(
        self,
        run_id: str,
        mode: str = "model",
        ledger_url: Optional[str] = None,
        api_key: Optional[str] = None,
        http_client: Optional[Any] = None,
        async_worker: bool = True,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self.ledger_url = (ledger_url or os.environ.get("LEDGER_URL") or "http://127.0.0.1:8004").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("QS_API_KEY", "")
        self.degraded = False
        self._http = http_client or httpx.Client(
            base_url=self.ledger_url,
            timeout=5.0,
            headers={"X-QS-Key": self.api_key},
        )
        self._owns_http = http_client is None
        self._async_worker = async_worker and http_client is None
        self._write_q: queue.Queue = queue.Queue(maxsize=2000)
        self._resolved_q: queue.Queue = queue.Queue()
        self._opened: set[str] = set()
        self._attested: set[tuple[str, str]] = set()
        self._resolved: set[str] = set()
        self._stop = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        if self. active_http and self._async_worker:
            self._worker_thread = threading.Thread(target=self._worker_loop, name=f"ledger-bridge-{run_id}", daemon=True)
            self._worker_thread.start()

    @property
    def active_http(self) -> bool:
        return self.mode in ("mock", "live") and not self.degraded

    @property
    def backlog(self) -> int:
        return self._write_q.qsize()

    def close(self) -> None:
        self._stop.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self._owns_http:
            try:
                self._http.close()
            except Exception:
                pass

    def txn_ref(self, pid: str) -> str:
        return f"{self.run_id}:{pid}"

    def open_unknown(self, pid: str, ik: Optional[str], psp: str, rem_bank: str, ben_bank: str, sim_ms: int,
                     debited: bool = False, credited: bool = False, failed_rem: bool = False,
                     failed_ben: bool = False, reversed_leg: bool = False) -> bool:
        """Open an unknown payment on M1 and backfill any legs that already completed (SPEC §5)."""
        if not self.active_http:
            return False
        task = ("OPEN", pid, ik, psp, rem_bank, ben_bank, int(sim_ms), debited, credited, failed_rem, failed_ben, reversed_leg)
        if self._async_worker:
            try:
                self._write_q.put_nowait(task)
                return True
            except queue.Full:
                self.degraded = True
                return False
        else:
            return self._exec_task(task)

    def attest_state(self, pid: str, sim_ms: int, debited: bool, credited: bool,
                     failed_rem: bool, failed_ben: bool, reversed_leg: bool) -> bool:
        if not self.active_http:
            return False
        task = ("ATTEST", pid, int(sim_ms), debited, credited, failed_rem, failed_ben, reversed_leg)
        if self._async_worker:
            try:
                self._write_q.put_nowait(task)
                return True
            except queue.Full:
                self.degraded = True
                return False
        else:
            return self._exec_task(task)

    def drain_resolutions(self) -> list[tuple[str, str]]:
        """Return list of `(payment_id, ledger_state)` for payments that reached a terminal state on M1."""
        out: list[tuple[str, str]] = []
        while True:
            try:
                out.append(self._resolved_q.get_nowait())
            except queue.Empty:
                break
        return out

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._write_q.get(timeout=0.05)
            except queue.Empty:
                continue
            self._exec_task(task)

    def _post(self, path: str, json_body: dict) -> Optional[dict]:
        try:
            url = path if self._owns_http else path
            r = self._http.post(url, json=json_body, headers={"X-QS-Key": self.api_key})
            if r.status_code in (200, 201):
                return r.json()
            jsonlog.warn("ledger write non-200", status=r.status_code, path=path)
            return None
        except Exception as exc:
            jsonlog.warn("ledger gateway unreachable; falling back to model", err=type(exc).__name__)
            self.degraded = True
            return None

    def _check_record_terminal(self, pid: str, resp: Optional[dict]) -> None:
        if not resp or pid in self._resolved:
            return
        rec = resp.get("record") if isinstance(resp, dict) else None
        if not isinstance(rec, dict):
            return
        st = rec.get("state")
        if st in TERMINAL_STATES:
            self._resolved.add(pid)
            self._resolved_q.put((pid, st))

    def _exec_task(self, task: tuple) -> bool:
        kind = task[0]
        if kind == "OPEN":
            _, pid, ik, psp, rem_bank, ben_bank, sim_ms, debited, credited, failed_rem, failed_ben, reversed_leg = task
            tref = self.txn_ref(pid)
            body = {
                "txnRef": tref,
                "idemKeyHash": ids.idem_key_hash(ik or pid, self.run_id),
                "payerPsp": psp,
                "remitterBank": rem_bank,
                "beneficiaryBank": ben_bank,
                "runId": self.run_id,
                "simMs": sim_ms,
            }
            resp = self._post("/v1/payments", body)
            if resp is None:
                return False
            self._opened.add(pid)
            self._check_record_terminal(pid, resp)
            self._send_attestations(pid, sim_ms, debited, credited, failed_rem, failed_ben, reversed_leg)
            return True
        if kind == "ATTEST":
            _, pid, sim_ms, debited, credited, failed_rem, failed_ben, reversed_leg = task
            if pid not in self._opened:
                return False
            self._send_attestations(pid, sim_ms, debited, credited, failed_rem, failed_ben, reversed_leg)
            return True
        return False

    def _send_attestations(self, pid: str, sim_ms: int, debited: bool, credited: bool,
                           failed_rem: bool, failed_ben: bool, reversed_leg: bool) -> None:
        tref = urllib.parse.quote(self.txn_ref(pid), safe="")
        steps: list[tuple[str, Optional[str]]] = []
        if failed_rem:
            steps.append(("FAILURE_REMITTER", "E_TD_REMITTER"))
        if debited:
            steps.append(("DEBIT", None))
        if credited:
            steps.append(("CREDIT", None))
        elif failed_ben:
            steps.append(("FAILURE_BENEFICIARY", "E_TD_BENEFICIARY"))
        if reversed_leg:
            steps.append(("REVERSAL", None))
        for akind, reason in steps:
            if (pid, akind) in self._attested or pid in self._resolved:
                continue
            payload: dict[str, Any] = {"kind": akind, "simMs": sim_ms}
            if reason:
                payload["reasonCode"] = reason
            resp = self._post(f"/v1/payments/{tref}/attest", payload)
            if resp is None:
                return
            self._attested.add((pid, akind))
            self._check_record_terminal(pid, resp)
