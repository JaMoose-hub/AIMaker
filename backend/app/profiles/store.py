"""ProfileStore: loads and validates board profiles.

Each board lives at <profile_dir>/boards/<board_id>/board.json (a flat
<profile_dir>/<board_id>/board.json layout is also accepted, used by test
fixtures). Every profile is validated twice:

1. against schemas/board-profile.schema.json (jsonschema), and
2. with BoardProfile.model_validate (pydantic, the runtime source of truth).

Validation failures raise ProfileValidationError with a readable message that
names the offending file and, when possible, the offending pin / JSON path.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import jsonschema
from pydantic import ValidationError

from app.profiles.models import BoardProfile

# board-vision/schemas/board-profile.schema.json
# (this file: board-vision/backend/app/profiles/store.py)
_DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "board-profile.schema.json"


class ProfileError(Exception):
    """Base class for profile store errors."""

    error_code = "profile_error"
    params: dict[str, object] = {}


class ProfileNotFoundError(ProfileError):
    error_code = "profile_not_found"

    def __init__(self, board_id: str, searched: list[Path]):
        self.board_id = board_id
        self.params = {"board_id": board_id}
        super().__init__(
            f"board profile '{board_id}' not found (searched: "
            + ", ".join(str(p) for p in searched)
            + ")"
        )


class ProfileValidationError(ProfileError):
    error_code = "profile_invalid"

    def __init__(self, file: Path, message: str):
        self.file = file
        self.params = {"file": str(file), "reason": message}
        super().__init__(f"invalid board profile {file}: {message}")


def _pin_hint(raw: dict, path: tuple) -> str:
    """Turn a JSON path like ('pins', 3, 'capabilities', 0, 'type') into a
    readable location that names the pin when possible."""
    parts = list(path)
    loc = "/".join(str(p) for p in parts) or "<root>"
    if len(parts) >= 2 and parts[0] == "pins" and isinstance(parts[1], int):
        pin_label = f"pins[{parts[1]}]"
        try:
            pin = raw.get("pins", [])[parts[1]]
            if isinstance(pin, dict) and pin.get("id"):
                pin_label = f"pin '{pin['id']}' (pins[{parts[1]}])"
        except (IndexError, TypeError, AttributeError):
            pass
        return f"{pin_label} at {loc}"
    return f"at {loc}"


class ProfileStore:
    def __init__(self, profile_dir: str | Path, schema_path: str | Path | None = None) -> None:
        self.profile_dir = Path(profile_dir)
        self.schema_path = Path(schema_path) if schema_path else _DEFAULT_SCHEMA_PATH
        self._schema: dict | None = None
        self._cache: dict[str, tuple[BoardProfile, dict]] = {}
        self._lock = threading.Lock()

    # -- paths ---------------------------------------------------------------

    def board_dir(self, board_id: str) -> Path:
        """Directory holding board.json + reference assets for a board."""
        nested = self.profile_dir / "boards" / board_id
        if nested.is_dir():
            return nested
        return self.profile_dir / board_id

    def _board_json_path(self, board_id: str) -> Path:
        return self.board_dir(board_id) / "board.json"

    def available_boards(self) -> list[str]:
        roots = [self.profile_dir / "boards", self.profile_dir]
        found: list[str] = []
        for root in roots:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if (child / "board.json").is_file() and child.name not in found:
                    found.append(child.name)
        return found

    # -- loading -------------------------------------------------------------

    def _load_schema(self) -> dict:
        if self._schema is None:
            with open(self.schema_path, "r", encoding="utf-8") as f:
                self._schema = json.load(f)
        return self._schema

    def load(self, board_id: str) -> tuple[BoardProfile, dict]:
        """Load + validate a board profile. Cached after first success."""
        with self._lock:
            if board_id in self._cache:
                return self._cache[board_id]

            path = self._board_json_path(board_id)
            if not path.is_file():
                searched = [
                    self.profile_dir / "boards" / board_id / "board.json",
                    self.profile_dir / board_id / "board.json",
                ]
                raise ProfileNotFoundError(board_id, searched)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except json.JSONDecodeError as e:
                raise ProfileValidationError(path, f"not valid JSON: {e}") from e

            # 1) jsonschema (documentation/CI schema)
            try:
                jsonschema.validate(instance=raw, schema=self._load_schema())
            except jsonschema.ValidationError as e:
                hint = _pin_hint(raw if isinstance(raw, dict) else {}, tuple(e.absolute_path))
                raise ProfileValidationError(path, f"schema violation {hint}: {e.message}") from e

            # 2) pydantic (runtime source of truth)
            try:
                profile = BoardProfile.model_validate(raw)
            except ValidationError as e:
                first = e.errors()[0]
                hint = _pin_hint(raw, tuple(first.get("loc", ())))
                raise ProfileValidationError(path, f"model violation {hint}: {first.get('msg')}") from e

            self._cache[board_id] = (profile, raw)
            return self._cache[board_id]

    def reload(self, board_id: str) -> tuple[BoardProfile, dict]:
        """Force a fresh read + re-validation of board.json, discarding any
        cached copy. Used after something (e.g. POST /api/calibrate's
        write_calibration()) modifies board.json on disk."""
        with self._lock:
            self._cache.pop(board_id, None)
        return self.load(board_id)

    def profile(self, board_id: str) -> BoardProfile:
        return self.load(board_id)[0]

    def raw(self, board_id: str) -> dict:
        return self.load(board_id)[1]

    def has(self, board_id: str) -> bool:
        try:
            self.load(board_id)
            return True
        except ProfileError:
            return False
