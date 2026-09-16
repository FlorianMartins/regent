import json
from pathlib import Path

import pytest

from regent.core.ledger import Ledger, LedgerError


def test_append_and_verify(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append("r1", "run.started", {"a": 1})
    ledger.append("r1", "tool.call", {"tool": "x"})
    ledger.append("r2", "run.started")
    assert Ledger.verify(path) == 3
    assert [e.kind for e in ledger.events("r1")] == ["run.started", "tool.call"]


def test_reopen_continues_chain(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    Ledger(path).append("r1", "a")
    Ledger(path).append("r1", "b")
    assert Ledger.verify(path) == 2
    events = Ledger(path).events()
    assert events[1].prev_hash == events[0].hash and events[1].seq == 2


def test_tamper_is_detected(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    ledger.append("r1", "a", {"usd": 1})
    ledger.append("r1", "b")
    lines = path.read_text().splitlines()
    doc = json.loads(lines[0])
    doc["data"]["usd"] = 0
    path.write_text("\n".join([json.dumps(doc), lines[1]]) + "\n")
    with pytest.raises(LedgerError, match="modified"):
        Ledger.verify(path)


def test_removal_is_detected(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    ledger = Ledger(path)
    for k in "abc":
        ledger.append("r1", k)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(LedgerError, match="links to"):
        Ledger.verify(path)


def test_unreadable_line(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    path.write_text("not json\n")
    with pytest.raises(LedgerError, match="unreadable"):
        Ledger.verify(path)


def test_in_memory_ledger():
    ledger = Ledger(None)
    ledger.append("r", "x")
    assert ledger.path is None and len(ledger.events()) == 1
