"""Append-only, hash-chained audit ledger.

Every run writes a sequence of events. Each event carries the SHA-256 of the
previous one, so removing, reordering or editing a line breaks the chain and
:meth:`Ledger.verify` says where. The format is plain JSON Lines: readable with
``jq``, shippable to any SIEM, and diffable in a pull request.

The ledger is the evidence an auditor asks for: *what did the agent see, what
did it decide, what did it do, and who approved it?*
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

GENESIS = "0" * 64


class LedgerEvent(BaseModel):
    """One line of the ledger."""

    model_config = ConfigDict(frozen=True)

    seq: int
    run_id: str
    kind: str
    """One of ``run.started``, ``llm.call``, ``tool.decision``, ``tool.call``,
    ``verification``, ``approval``, ``run.finished``."""
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str

    @staticmethod
    def compute_hash(
        seq: int, run_id: str, kind: str, at: datetime, data: dict[str, Any], prev_hash: str
    ) -> str:
        """Canonical hash: sorted keys, no whitespace, ISO timestamps."""
        canonical = json.dumps(
            {
                "seq": seq,
                "run_id": run_id,
                "kind": kind,
                "at": at.isoformat(),
                "data": data,
                "prev_hash": prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LedgerError(RuntimeError):
    """The chain is broken."""


class Ledger:
    """Writes and verifies a hash-chained JSON Lines file.

    ``Ledger(None)`` keeps events in memory only — handy for tests and dry runs.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._events: list[LedgerEvent] = []
        self._last_hash = GENESIS
        self._seq = 0
        if path is not None and path.exists():
            for event in self._read(path):
                self._events.append(event)
                self._last_hash = event.hash
                self._seq = event.seq
        elif path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path | None:
        """Where the ledger is stored (``None`` when in memory)."""
        return self._path

    def append(self, run_id: str, kind: str, data: dict[str, Any] | None = None) -> LedgerEvent:
        """Append one event and return it."""
        with self._lock:
            self._seq += 1
            at = datetime.now(UTC)
            payload = data or {}
            digest = LedgerEvent.compute_hash(self._seq, run_id, kind, at, payload, self._last_hash)
            event = LedgerEvent(
                seq=self._seq,
                run_id=run_id,
                kind=kind,
                at=at,
                data=payload,
                prev_hash=self._last_hash,
                hash=digest,
            )
            self._events.append(event)
            self._last_hash = digest
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(event.model_dump_json() + "\n")
            return event

    def events(self, run_id: str | None = None) -> list[LedgerEvent]:
        """All events, optionally filtered by run."""
        return [e for e in self._events if run_id is None or e.run_id == run_id]

    @staticmethod
    def _read(path: Path) -> Iterator[LedgerEvent]:
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    yield LedgerEvent.model_validate_json(line)
                except ValueError as exc:
                    raise LedgerError(f"{path}:{line_no}: unreadable event: {exc}") from exc

    @classmethod
    def verify(cls, path: Path) -> int:
        """Re-hash the whole file. Returns the number of events, raises on the first break."""
        expected_prev = GENESIS
        count = 0
        for event in cls._read(path):
            count += 1
            if event.prev_hash != expected_prev:
                raise LedgerError(
                    f"{path}: event {event.seq} links to {event.prev_hash[:12]}…, "
                    f"expected {expected_prev[:12]}…"
                )
            recomputed = LedgerEvent.compute_hash(
                event.seq, event.run_id, event.kind, event.at, event.data, event.prev_hash
            )
            if recomputed != event.hash:
                raise LedgerError(f"{path}: event {event.seq} was modified after being written")
            expected_prev = event.hash
        return count
