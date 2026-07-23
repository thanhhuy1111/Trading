"""Closed-candle market-data ingestion worker for paper trading (F-02).

The worker pulls candles from a pluggable ``CandleSource`` and drives the paper pipeline:

    source (public WS/REST) -> closed-candle detection -> dedup -> clock-skew / gap checks
    -> PaperPipeline.process_candle_close

Design notes:
- Public data only. No API key, no private endpoints (safety boundary preserved).
- Only closed candles are processed; open/forming candles are ignored.
- Duplicate and out-of-order candles are dropped; a sequence gap degrades the runtime and
  triggers a public backfill; entries never open while not RUNNING (the pipeline enforces this).
- Dedup / sequence state is in-memory in this pass. DB-backed idempotency (unique on
  session+symbol+timeframe+close_time) is Phase B and is BLOCKED here (no Postgres) — see
  docs/remediation/REMAINING_LIMITATIONS.md.
- The live ``BinanceRestCandleSource`` is implemented but NOT runtime-verified (no network in
  tests). Worker LOGIC is verified with a ``FakeCandleSource``.
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator, Dict, List, Optional, Protocol, Set, Tuple
from uuid import UUID

from packages.common.logger import logger
from packages.market_data.models import Candle
from packages.paper.models import PaperSessionStatus
from packages.paper.session import paper_session_manager


class WorkerState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class HandleResult(str, Enum):
    IGNORED_OPEN = "IGNORED_OPEN"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    SKEW_DEGRADED = "SKEW_DEGRADED"
    GAP_RECOVERED = "GAP_RECOVERED"
    GAP_UNRECOVERABLE = "GAP_UNRECOVERABLE"
    PROCESSED = "PROCESSED"


class CandleSource(Protocol):
    """Yields ``(candle, sequence_number)`` and can backfill a missing sequence range."""

    def stream(self) -> AsyncIterator[Tuple[Candle, int]]: ...

    async def backfill(self, symbol: str, timeframe: str, from_seq: int, to_seq: int) -> List[Tuple[Candle, int]]: ...


class PaperIngestionWorker:
    def __init__(
        self,
        session_id: UUID,
        pipeline,
        *,
        clock_skew_limit_ms: float = 5000.0,
    ) -> None:
        self.session_id = session_id
        self.pipeline = pipeline
        self.clock_skew_limit_ms = clock_skew_limit_ms
        self.state = WorkerState.CREATED
        self._task: Optional[asyncio.Task] = None
        self._source: Optional[CandleSource] = None
        self._last_seq: Dict[str, int] = {}
        self._processed: Set[Tuple[str, str, str]] = set()

    # ----- session state reflection (guarded against invalid transitions) -----
    def _try_transition(self, to_status: PaperSessionStatus, reason: str) -> None:
        try:
            paper_session_manager.transition_status(self.session_id, to_status, reason=reason)
        except Exception as exc:  # invalid transition for current status; keep worker state authoritative
            logger.info("Session transition skipped", extra={"to": to_status.value, "err": str(exc)})

    def _degrade(self, reason: str) -> None:
        self.state = WorkerState.DEGRADED
        sess = paper_session_manager.sessions.get(self.session_id)
        if sess and sess.status == PaperSessionStatus.RUNNING:
            self._try_transition(PaperSessionStatus.DEGRADED, reason)

    def _resume(self, reason: str) -> None:
        self.state = WorkerState.RUNNING
        sess = paper_session_manager.sessions.get(self.session_id)
        if sess and sess.status == PaperSessionStatus.DEGRADED:
            self._try_transition(PaperSessionStatus.RUNNING, reason)

    def _require_recovery(self, reason: str) -> None:
        self.state = WorkerState.RECOVERY_REQUIRED
        self._try_transition(PaperSessionStatus.HALTED, reason)
        self._try_transition(PaperSessionStatus.RECOVERY_REQUIRED, reason)

    @staticmethod
    def _key(candle: Candle) -> Tuple[str, str, str]:
        tf = candle.timeframe.value if hasattr(candle.timeframe, "value") else str(candle.timeframe)
        return (candle.symbol, tf, candle.close_time.isoformat())

    async def _process(self, candle: Candle) -> None:
        self._processed.add(self._key(candle))
        await self.pipeline.process_candle_close(self.session_id, candle)

    async def _handle_candle(self, candle: Candle, seq: int, now: Optional[datetime] = None) -> HandleResult:
        # 1. Only closed candles are actionable
        if not candle.is_closed:
            return HandleResult.IGNORED_OPEN

        # 2. Deduplication
        if self._key(candle) in self._processed:
            return HandleResult.DUPLICATE

        # 3. Clock-skew: stale data fails closed (no processing, degrade)
        now = now or datetime.now(timezone.utc)
        skew_ms = abs((now - candle.exchange_timestamp).total_seconds()) * 1000.0
        if skew_ms > self.clock_skew_limit_ms:
            self._degrade(f"CLOCK_SKEW_{skew_ms:.0f}ms")
            return HandleResult.SKEW_DEGRADED

        # 4. Sequence continuity
        last = self._last_seq.get(candle.symbol)
        if last is not None and seq <= last:
            return HandleResult.OUT_OF_ORDER  # duplicate/older sequence: quarantine

        if last is not None and seq > last + 1:
            # gap -> degrade and attempt public backfill
            self._degrade(f"SEQUENCE_GAP {last}->{seq}")
            tf = candle.timeframe.value if hasattr(candle.timeframe, "value") else str(candle.timeframe)
            recovered: List[Tuple[Candle, int]] = []
            if self._source is not None:
                recovered = await self._source.backfill(candle.symbol, tf, last + 1, seq - 1)
            expected = seq - last - 1
            if len(recovered) != expected:
                self._require_recovery(f"UNRECOVERABLE_GAP expected={expected} got={len(recovered)}")
                return HandleResult.GAP_UNRECOVERABLE
            for bf_candle, bf_seq in sorted(recovered, key=lambda x: x[1]):
                if bf_candle.is_closed and self._key(bf_candle) not in self._processed:
                    self._last_seq[candle.symbol] = bf_seq
                    await self._process(bf_candle)
            self._last_seq[candle.symbol] = seq
            await self._process(candle)
            self._resume("GAP_BACKFILLED")
            return HandleResult.GAP_RECOVERED

        # 5. Normal in-order closed candle
        self._last_seq[candle.symbol] = seq
        await self._process(candle)
        return HandleResult.PROCESSED

    async def start(self, source: CandleSource) -> None:
        if self._task is not None and not self._task.done():
            logger.warning("Ingestion worker already running", extra={"session_id": str(self.session_id)})
            return
        self._source = source
        self.state = WorkerState.RUNNING

        async def _run() -> None:
            try:
                async for candle, seq in source.stream():
                    await self._handle_candle(candle, seq)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # do not let the loop die silently
                logger.error("Ingestion worker error", extra={"session_id": str(self.session_id), "err": str(exc)})
                self._degrade(f"WORKER_EXCEPTION: {exc}")

        self._task = asyncio.create_task(_run())

    async def stop(self) -> None:
        self.state = WorkerState.STOPPING
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.state = WorkerState.STOPPED
