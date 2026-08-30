"""Temporary-file regressions for simulator publication and queue concurrency."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from simulator import commands, control, world_model
from simulator.file_io import RuntimeFileError


SIM_NOW = datetime(2026, 1, 29, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def isolated_files(tmp_path, monkeypatch):
    """Patch every imported path used here before any simulator file operation."""
    for name in (
        "SIM_STATE_PATH", "HEARTBEAT_PATH", "RUNTIME_SNAPSHOT_PATH",
        "COMMANDS_PATH", "EVENT_LOG_PATH",
    ):
        path = tmp_path / getattr(control, name).name
        monkeypatch.setattr(control, name, path)
        for module in (commands, world_model):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, path)
    return tmp_path


def _publication(kind):
    if kind == "control":
        return (
            control.SIM_STATE_PATH,
            lambda: control.write_control({"status": "RUNNING"}),
            control.read_control,
        )
    if kind == "heartbeat":
        return (
            control.HEARTBEAT_PATH,
            lambda: control.write_heartbeat(SIM_NOW, 7, "RUNNING"),
            control.read_heartbeat,
        )
    world = world_model.SimulationWorld(SimpleNamespace())
    return (
        world_model.RUNTIME_SNAPSHOT_PATH,
        lambda: world.write_runtime_snapshot(SIM_NOW, "RUNNING", 30.0),
        world.read_runtime_snapshot,
    )


@pytest.mark.parametrize("kind", ["control", "heartbeat", "runtime"])
def test_json_publication_keeps_previous_document_until_atomic_replace(
    isolated_files, monkeypatch, kind,
):
    path, publish, _ = _publication(kind)
    previous = {**control.default_control(), "status": "PAUSED", "marker": "previous complete document"}
    path.write_text(json.dumps(previous), encoding="utf-8")
    real_replace = os.replace
    replacements = []

    def inspect_publication(source, destination, *args, **kwargs):
        if Path(destination) == path:
            assert Path(source).parent == path.parent
            assert Path(source) != path
            assert json.loads(path.read_text(encoding="utf-8")) == previous
            staged = json.loads(Path(source).read_text(encoding="utf-8"))
            assert staged["status"] == "RUNNING"
            replacements.append(staged)
        return real_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", inspect_publication)
    publish()

    assert len(replacements) == 1, "A complete JSON document must publish through os.replace"
    assert json.loads(path.read_text(encoding="utf-8")) == replacements[0]


@pytest.mark.parametrize("kind", ["control", "heartbeat", "runtime"])
def test_failed_publication_preserves_previous_document_and_cleans_staging_file(
    isolated_files, monkeypatch, kind,
):
    path, publish, _ = _publication(kind)
    previous = {**control.default_control(), "status": "PAUSED"}
    path.write_text(json.dumps(previous), encoding="utf-8")

    def reject_publication(*args, **kwargs):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(os, "replace", reject_publication)
    with pytest.raises(RuntimeFileError, match=path.name):
        publish()

    assert json.loads(path.read_text(encoding="utf-8")) == previous
    assert set(isolated_files.iterdir()) == {path}


@pytest.mark.parametrize("damaged", ["", "{", "[]", "null"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_damaged_control_is_explicit_error_and_is_not_reinitialized(
    isolated_files, damaged, operation,
):
    path = control.SIM_STATE_PATH
    path.write_text(damaged, encoding="utf-8")

    with pytest.raises(RuntimeFileError, match=path.name):
        if operation == "read":
            control.read_control()
        else:
            control.write_control({"status": "RUNNING"})

    assert path.read_text(encoding="utf-8") == damaged


def test_missing_control_retains_initial_stopped_defaults_without_creating_file(isolated_files):
    assert not control.SIM_STATE_PATH.exists()
    assert control.read_control() == control.default_control()
    assert control.read_control()["status"] == "STOPPED"
    assert not control.SIM_STATE_PATH.exists()


def test_heartbeat_records_wall_clock_utc_separately_from_simulation_time(isolated_files):
    before = datetime.now(timezone.utc)
    control.write_heartbeat(SIM_NOW, 23, "RUNNING")
    after = datetime.now(timezone.utc)

    heartbeat = control.read_heartbeat()
    assert heartbeat is not None
    assert heartbeat["ts"] == SIM_NOW.isoformat()
    assert heartbeat["tick"] == 23
    recorded_at = datetime.fromisoformat(heartbeat["recorded_at"])
    assert recorded_at.utcoffset() == timedelta(0)
    assert before <= recorded_at <= after


@pytest.mark.parametrize("kind", ["control", "heartbeat", "runtime"])
def test_concurrent_readers_only_observe_complete_json_documents(isolated_files, kind):
    _, publish, read = _publication(kind)
    publish()
    ready = Event()
    finished = Event()

    def read_until_finished():
        reads = 0
        while True:
            payload = read()
            assert payload is not None
            assert payload["status"] == "RUNNING"
            reads += 1
            ready.set()
            if finished.is_set():
                break
        return reads

    with ThreadPoolExecutor(max_workers=1) as executor:
        reader = executor.submit(read_until_finished)
        assert ready.wait(5)
        try:
            for _ in range(100):
                publish()
        finally:
            finished.set()
        assert reader.result(timeout=5) > 0


@pytest.mark.parametrize("operation", ["append", "cancel"])
def test_command_transaction_preserves_edits_arriving_during_tick_snapshot(
    isolated_files, operation,
):
    existing = commands.SimulationCommand.create(
        target_type="EQUIPMENT", target_id="TRK-001", action="BREAKDOWN",
    )
    appended = commands.SimulationCommand.create(
        target_type="EQUIPMENT", target_id="TRK-002", action="BREAKDOWN",
    )
    commands.append_command(existing)
    attempted = Event()

    def edit_queue():
        attempted.set()
        if operation == "append":
            return commands.append_command(appended)
        return commands.cancel_command(existing.command_id)

    # On the unfixed implementation nullcontext exposes the lost-update bug;
    # once provided, the real transaction must serialize the entire snapshot.
    transaction = getattr(commands, "command_transaction", nullcontext)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction():
            snapshot = commands.load_all_commands()
            future = executor.submit(edit_queue)
            assert attempted.wait(5)
            blocked = False
            try:
                future.result(timeout=0.1)
            except TimeoutError:
                blocked = True
            snapshot[0].status = "APPLIED"
            commands.rewrite_commands(snapshot)
        future.result(timeout=5)

    final = {item.command_id: item for item in commands.load_all_commands()}
    if operation == "append":
        assert set(final) == {existing.command_id, appended.command_id}
        assert final[appended.command_id].status == "PENDING"
        assert final[existing.command_id].status == "APPLIED"
    else:
        assert final[existing.command_id].status == "CANCELLED"
    assert blocked, "Queue edits must wait until tick snapshot processing commits"
