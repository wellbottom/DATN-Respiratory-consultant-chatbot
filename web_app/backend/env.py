from __future__ import annotations

from pathlib import Path

_ENV_STATE: dict[str, Path | None | bool] = {"loaded": False, "path": None}


def load_local_env(*, root: Path | None = None, override: bool = False) -> Path | None:
    if _ENV_STATE["loaded"] and not override:
        return _ENV_STATE["path"]  # type: ignore[return-value]

    try:
        from dotenv import load_dotenv
    except ImportError:
        _ENV_STATE["loaded"] = True
        _ENV_STATE["path"] = None
        return None

    app_root = root or Path(__file__).resolve().parents[1]
    candidates = [app_root / ".env", app_root.parent / ".env", Path.cwd() / ".env"]
    seen: set[Path] = set()
    loaded_from: Path | None = None

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.exists():
            continue
        load_dotenv(resolved, override=override)
        seen.add(resolved)
        if loaded_from is None:
            loaded_from = resolved

    _ENV_STATE["loaded"] = True
    _ENV_STATE["path"] = loaded_from
    return loaded_from
