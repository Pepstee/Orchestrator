"""infra.atomic_io — the ONLY sanctioned file writer/deleter (law L7).

All file mutation in the system goes through here, so writes are crash-safe and auditable:
- write_json_atomic: temp file + fsync + atomic rename (never a half-written file)
- append_jsonl: fsynced append for the event log
- read_jsonl: tolerant read that skips a truncated final line (crash safety)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator


def write_json_atomic(path: Path | str, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def write_text_atomic(path: Path | str, text: str) -> None:
    """Write raw text crash-safely (temp + fsync + atomic rename) — the text counterpart to
    write_json_atomic, used e.g. by the mutation-testing sandbox."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def append_jsonl(path: Path | str, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_json(path: Path | str) -> Any | None:
    """Read a JSON file, or None if absent/corrupt (the read counterpart to write_json_atomic)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def remove(path: Path | str) -> None:
    """Best-effort delete — the single sanctioned deleter (law L7)."""
    try:
        Path(path).unlink()
    except (FileNotFoundError, OSError):
        pass


def read_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a truncated final line (a crash mid-append)
