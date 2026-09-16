"""Locale-neutral API result helpers.

Expected operational failures use HTTP 200 and stable codes. ``error`` is
retained as a temporary compatibility alias for older clients; new clients
must read ``error_code`` and translate it locally with ``params``.
"""
from __future__ import annotations


def expected_error(error_code: str, **params: object) -> dict[str, object]:
    code = str(error_code)
    return {
        "ok": False,
        "error": code,
        "error_code": code,
        "params": dict(params),
    }
