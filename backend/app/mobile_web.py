"""Published LAN HTTPS entry point; no camera or desktop runtime ownership."""
from __future__ import annotations

import json
from pathlib import Path
import socket
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / "runs" / "mobile-web-https"


def web_configuration(root: Path = ROOT) -> dict:
    result = {"available": False, "base_url": None, "web_url": None,
              "certificate_url": "/api/mobile/web-ca", "certificate_profile_url": "/api/mobile/web-ca-profile"}
    try:
        saved = json.loads((root / "connection.json").read_text(encoding="utf-8"))
        base = saved["base_url"].rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return result
        port = parsed.port or 443
        result.update(base_url=base, web_url=base + "/mobile")
        # An old configuration file alone must not advertise a running service.
        with socket.create_connection(("127.0.0.1", port), timeout=.2):
            result["available"] = True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result
