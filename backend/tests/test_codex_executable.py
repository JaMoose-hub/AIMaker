"""Local executable discovery only: no authentication or inference requests."""
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import codex_bridge


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.delenv("BOARDVISION_CODEX_BIN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(codex_bridge.shutil, "which", Mock(return_value=None))
    directory = tmp_path / "OpenAI" / "Codex" / "bin"
    directory.mkdir(parents=True)
    return directory


def executable(directory, release=None, modified=1):
    path = directory / release / "codex.exe" if release else directory / "codex.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (modified, modified))
    return path


def test_explicit_override_wins_over_path_and_desktop(installation, monkeypatch):
    configured = str(installation / "custom cli.exe")
    monkeypatch.setenv("BOARDVISION_CODEX_BIN", f'"{configured}"')
    codex_bridge.shutil.which.side_effect = lambda name: configured if name == configured else "other"
    assert codex_bridge.resolve_codex_executable() == configured
    codex_bridge.shutil.which.assert_called_once_with(configured)


def test_invalid_override_does_not_silently_switch_installation(installation, monkeypatch):
    executable(installation)
    monkeypatch.setenv("BOARDVISION_CODEX_BIN", "missing.exe")
    with pytest.raises(RuntimeError, match="BOARDVISION_CODEX_BIN"):
        codex_bridge.resolve_codex_executable()
    codex_bridge.shutil.which.assert_called_once_with("missing.exe")


def test_path_cli_retains_priority(installation):
    executable(installation, "a" * 16)
    codex_bridge.shutil.which.return_value = "path-cli"
    assert codex_bridge.resolve_codex_executable() == "path-cli"


def test_missing_path_finds_newest_installed_desktop_cli(installation):
    executable(installation, modified=999)  # Legacy shim must not beat an update.
    executable(installation, "a" * 16, modified=10)
    newest = executable(installation, "b" * 16, modified=20)
    executable(installation, "arbitrary-download", modified=1000)
    (installation / ("c" * 16)).mkdir()  # Incomplete release is skipped.
    assert codex_bridge.resolve_codex_executable() == str(newest)


def test_desktop_update_is_discovered_again_without_pinning_old_hash(installation):
    first = executable(installation, "a" * 16, modified=10)
    assert codex_bridge.resolve_codex_executable() == str(first)
    second = executable(installation, "b" * 16, modified=20)
    assert codex_bridge.resolve_codex_executable() == str(second)


def test_legacy_desktop_cli_still_works(installation):
    legacy = executable(installation)
    assert codex_bridge.resolve_codex_executable() == str(legacy)


def test_no_cli_keeps_actionable_error(installation):
    with pytest.raises(RuntimeError, match="找不到 Codex CLI"):
        codex_bridge.resolve_codex_executable()


def test_no_desktop_environment_keeps_path_only_behaviour(installation, monkeypatch):
    executable(installation)
    monkeypatch.delenv("LOCALAPPDATA")
    with pytest.raises(RuntimeError, match="找不到 Codex CLI"):
        codex_bridge.resolve_codex_executable()


def test_missing_installation_does_not_mask_actionable_error(installation, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(installation / "absent"))
    with pytest.raises(RuntimeError, match="找不到 Codex CLI"):
        codex_bridge.resolve_codex_executable()


def test_bridge_launches_resolved_cli_hidden_and_uses_existing_handshake(installation, monkeypatch):
    path = executable(installation, "a" * 16)
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setattr(codex_bridge.subprocess, "Popen", popen)
    monkeypatch.setattr(codex_bridge.threading, "Thread", Mock())
    bridge = codex_bridge.CodexBridge()
    bridge._rpc = Mock(return_value={})
    bridge._send = Mock()
    try:
        bridge._start()
        args, kwargs = popen.call_args
        assert args[0] == [str(path), "app-server"]
        assert kwargs["cwd"] == bridge._workspace.name
        assert kwargs["creationflags"] == (codex_bridge.subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        bridge._rpc.assert_called_once_with("initialize", {"clientInfo": {"name": "boardvision", "version": "0.1.0"}})
        bridge._send.assert_called_once_with({"method": "initialized", "params": {}})
    finally:
        process.poll.return_value = 0
        bridge.close()
