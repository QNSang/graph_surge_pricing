from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)



def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path: Path, value: dict) -> None:
    """Exclusive artifact creation. Never silently replace an experiment result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')

from contextlib import contextmanager

@contextmanager
def trial_lock(folder: Path):
    lock = folder / ".training.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError(f"Trial is locked: {folder}. Check another training process before removing a stale lock") from exc
    try:
        handle.write("DuoCast trial in progress\n")
        handle.close()
        yield
    finally:
        handle.close()
        lock.unlink(missing_ok=True)
