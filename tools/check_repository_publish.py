"""Check publication scope and model integrity in the Git index (no hardware).

Run after git add and before committing. Complements, not replaces, Gitleaks.
Uses only the Python standard library. Never prints file contents or credentials.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILES = {
    "board-pose-pi5-handheld-v2.onnx",
    "board-pose-pi5.onnx",
    "hc-sr04-corner-pose-v3-robust.onnx",
    "mrd-tf240-8p-cs-pose.onnx",
}
MODEL_PATHS = {f"models/{name}" for name in MODEL_FILES}
MAX_FILE_BYTES = 50 * 1024 * 1024
PRIVATE_DIRECTORIES = {
    ".codex", ".ssh", "node_modules", "dist", "runs", "datasets",
    "calibration", "__pycache__", ".pytest_cache", ".arduino-user",
}
PRIVATE_NAMES = {"auth.json", "credentials.json", "credentials.yaml", "tokens.json"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_path(name: str) -> bool:
    path = PurePosixPath(name)
    parts = [part.lower() for part in path.parts]
    leaf = parts[-1]
    return (
        name == "backend/config.yaml"
        or any(p in PRIVATE_DIRECTORIES or p.startswith(".venv") for p in parts[:-1])
        or leaf in PRIVATE_NAMES
        or (leaf.startswith(".env") and leaf != ".env.example")
        or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite"}
        or leaf.startswith(("id_rsa", "id_ed25519"))
        or ".bak" in leaf
    )


def check_index() -> list[str]:
    errors = []
    staged = {}
    for entry in git("ls-files", "--stage", "-z").decode("utf-8").split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, oid, stage = metadata.split()
        if stage != "0" or mode not in {"100644", "100755"}:
            errors.append(f"Unmerged entry, link or submodule requires review: {name}")
        staged[name] = oid
    if not staged:
        return ["Nothing staged/tracked. Run git add before this check."]

    ignored = git("ls-files", "--cached", "--ignored", "--exclude-standard", "-z")
    errors.extend(f"Ignored local file is tracked: {p}" for p in ignored.decode().split("\0") if p)
    required = {".gitignore", "backend/config.example.yaml", "models/manifest.json", *MODEL_PATHS}
    errors.extend(f"Required public file missing: {p}" for p in sorted(required - staged.keys()))
    size_output = subprocess.check_output(
        ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
        cwd=ROOT, input=("\n".join(staged.values()) + "\n").encode(),
    ).decode()
    sizes = {oid: int(size) for oid, size in (line.split() for line in size_output.splitlines())}
    for name, oid in staged.items():
        if private_path(name):
            errors.append(f"Private path must not be published: {name}")
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in {".onnx", ".pt", ".pth", ".ckpt", ".engine"} and name not in MODEL_PATHS:
            errors.append(f"Model outside the publication allowlist: {name}")
        if name.startswith("models/") and name not in MODEL_PATHS | {"models/README.md", "models/manifest.json"}:
            errors.append(f"Unexpected model asset: {name}")
        size = sizes[oid]
        if size > MAX_FILE_BYTES:
            errors.append(f"File exceeds 50 MiB publication budget: {name}")

    if "models/manifest.json" in staged:
        manifest = json.loads(git("show", ":models/manifest.json"))
        entries = manifest["models"]
        if len(entries) != len(MODEL_FILES) or {m["file"] for m in entries} != MODEL_FILES:
            errors.append("Manifest must list exactly the four approved model exports.")
        for model in entries:
            name = "models/" + model["file"]
            if name not in MODEL_PATHS or name not in staged:
                continue
            data = git("show", ":" + name)
            if len(data) != model["size_bytes"] or hashlib.sha256(data).hexdigest() != model["sha256"]:
                errors.append(f"Model content differs from manifest: {name}")
    return errors


if __name__ == "__main__":
    try:
        problems = check_index()
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as exc:
        print(f"Publication check could not complete ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(2)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(1)
    print("Publication scope OK: no ignored/private paths, four verified models, files under 50 MiB.")
    print("Also run Gitleaks on the staged content; this check is not a secret scanner.")
