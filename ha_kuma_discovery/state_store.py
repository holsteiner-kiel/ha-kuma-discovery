"""Persistent discovery state with atomic writes and backup recovery."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


def _read_state_file(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("State must be a JSON object")
    return data


def load_state(path: Path, log) -> Dict[str, Any]:
    for candidate in (path, path.with_suffix(".json.bak")):
        try:
            data = _read_state_file(candidate)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as exc:
            log.warning(
                "Cannot read state file %s (%s)",
                candidate.name,
                type(exc).__name__,
            )
            continue
        if candidate != path:
            log.warning("Recovered state from backup %s", candidate.name)
        return data
    log.warning("No usable saved state; starting with empty state")
    return {"known_slugs": [], "known_shelly_device_ids": []}


def _atomic_write(path: Path, content: str) -> None:
    # Same directory keeps os.replace on the same filesystem.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as file:
            temp_path = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def save_state(state: Dict[str, Any], path: Path, log) -> None:
    if not isinstance(state, dict):
        raise ValueError("State must be a JSON object")
    content = json.dumps(state, indent=2, sort_keys=True)
    # Never replace a valid backup with a corrupt primary file.
    try:
        previous = _read_state_file(path)
    except FileNotFoundError:
        previous = None
    except (OSError, ValueError) as exc:
        log.warning("Skipping backup of unreadable state (%s)", type(exc).__name__)
        previous = None
    if previous is not None:
        _atomic_write(
            path.with_suffix(".json.bak"),
            json.dumps(previous, indent=2, sort_keys=True),
        )
    _atomic_write(path, content)
