"""Unit tests for installing a staged update over a portable installation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from reimbursement_manager import updater
from reimbursement_manager.updater import (
    UpdateApplyError,
    UpdateResult,
    apply_update,
    consume_update_result,
    is_update_invocation,
    wait_for_process,
    write_result,
)


def _make_program(directory: Path, *, marker: str, with_internal: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / updater.EXECUTABLE_NAME).write_text(marker, encoding="utf-8")
    if with_internal:
        internal = directory / "_internal"
        internal.mkdir(exist_ok=True)
        (internal / "runtime.txt").write_text(marker, encoding="utf-8")
    return directory


def test_is_update_invocation_detects_the_updater_flag() -> None:
    assert is_update_invocation(["--apply-update", "--to", "x"]) is True
    assert is_update_invocation(["--help"]) is False


def test_replace_installation_swaps_the_program_directory(tmp_path: Path) -> None:
    source = _make_program(tmp_path / "staging", marker="new")
    target = _make_program(tmp_path / "program", marker="old")

    updater.replace_installation(source, target)

    assert (target / updater.EXECUTABLE_NAME).read_text(encoding="utf-8") == "new"
    leftovers = [
        path.name
        for path in tmp_path.iterdir()
        if path.name.startswith(".program.")
    ]
    assert leftovers == []


def test_replace_installation_refuses_an_incomplete_staging_directory(
    tmp_path: Path,
) -> None:
    source = _make_program(tmp_path / "staging", marker="new", with_internal=False)
    target = _make_program(tmp_path / "program", marker="old")

    with pytest.raises(UpdateApplyError):
        updater.replace_installation(source, target)

    assert (target / updater.EXECUTABLE_NAME).read_text(encoding="utf-8") == "old"


def test_apply_update_replaces_launches_and_records_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_program(tmp_path / "staging", marker="new")
    target = _make_program(tmp_path / "program", marker="old")
    launched: list[Path] = []

    monkeypatch.setattr(updater, "launch_application", launched.append)
    monkeypatch.setattr(
        updater, "_result_path", lambda: tmp_path / "update-result.json"
    )

    apply_update(source=source, target=target, wait_pid=0, version="0.2.2")

    assert (target / updater.EXECUTABLE_NAME).read_text(encoding="utf-8") == "new"
    assert launched == [target]
    payload = json.loads((tmp_path / "update-result.json").read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["version"] == "0.2.2"


def test_apply_update_aborts_when_the_old_process_never_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_program(tmp_path / "staging", marker="new")
    target = _make_program(tmp_path / "program", marker="old")

    monkeypatch.setattr(updater, "wait_for_process", lambda pid, timeout: False)
    monkeypatch.setattr(updater, "launch_application", lambda directory: None)
    monkeypatch.setattr(
        updater, "_result_path", lambda: tmp_path / "update-result.json"
    )

    with pytest.raises(UpdateApplyError):
        apply_update(source=source, target=target, wait_pid=1234, version="0.2.2")

    assert (target / updater.EXECUTABLE_NAME).read_text(encoding="utf-8") == "old"


def test_wait_for_process_returns_true_for_an_already_exited_process() -> None:
    assert wait_for_process(0, timeout=0.1) is True

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=30)
    started = time.monotonic()
    assert wait_for_process(process.pid, timeout=5) is True
    assert time.monotonic() - started < 5


def test_write_and_consume_update_result_round_trips_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = tmp_path / "update-result.json"
    monkeypatch.setattr(updater, "_result_path", lambda: result_path)

    write_result(
        UpdateResult(
            success=True, version="0.2.2", message="更新完成。", timestamp=123.0
        )
    )
    consumed = consume_update_result()

    assert consumed is not None
    assert consumed.success is True
    assert consumed.version == "0.2.2"
    assert consumed.message == "更新完成。"
    # The marker is single-use so the message is shown exactly once.
    assert not result_path.exists()
    assert consume_update_result() is None


def test_cleanup_update_workspace_removes_archives_and_staged_builds(
    tmp_path: Path,
) -> None:
    updates = tmp_path / "updates"
    staged = _make_program(updates / "staging-0.2.2", marker="new")
    (updates / "archive.zip").write_bytes(b"zip")
    (updates / "archive.zip.part").write_bytes(b"partial")

    updater.cleanup_update_workspace(updates)

    assert not staged.exists()
    assert list(updates.iterdir()) == []


def test_cleanup_update_workspace_tolerates_a_missing_directory(
    tmp_path: Path,
) -> None:
    updater.cleanup_update_workspace(tmp_path / "never-created")


def test_consume_update_result_ignores_a_corrupt_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = tmp_path / "update-result.json"
    result_path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(updater, "_result_path", lambda: result_path)

    assert consume_update_result() is None
    assert not result_path.exists()
