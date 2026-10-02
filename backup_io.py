"""Validated backup I/O with sibling temporary files and atomic replacement."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from ftm300dr_format import validate_backup


def read_backup_file(path) -> bytes:
    data = Path(path).read_bytes()
    validate_backup(data)
    return data


def same_path(left, right) -> bool:
    a, b = Path(left), Path(right)
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))


def save_backup(path, data, *, protected_paths=()) -> None:
    """Never replace a protected source/template; leave destination intact on failure."""
    validate_backup(data)
    target = Path(path).resolve()
    if any(same_path(target, p) for p in protected_paths):
        raise ValueError("Output must be different from the source image and template backup")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as fh:
            temp_path = Path(fh.name)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if read_backup_file(temp_path) != bytes(data):
            raise OSError("Temporary backup verification failed")
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
