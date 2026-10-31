"""Provisioning changes the OS: replace only subprocess/tool discovery boundaries."""

import copy
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from test_pipewire_gate import graph as graph


def complete_graph():
    data = graph()
    data[-1]["info"].update(params={"Props": [{"mute": False}]})
    data[-1]["info"]["props"]["object.serial"] = 18
    return data


@pytest.fixture
def machine(tmp_path, monkeypatch):
    from models.audio_routing import managed_microphone as module

    # Only this module sees a Linux host; do not change Python's global platform.
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    if sys.platform == "win32":
        # These cases test provisioning decisions with fake systemctl/graph IO.
        # Real flock serialization remains covered by the Linux-only case below.
        def flock(fd, flags):
            assert flags == 2 | 4
            assert os.fstat(fd.fileno()).st_size == 0

        monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=flock))
        monkeypatch.setattr(module, "os", SimpleNamespace(
            open=os.open, fdopen=os.fdopen, fsync=os.fsync,
            O_CREAT=os.O_CREAT, O_RDWR=os.O_RDWR, O_NOFOLLOW=0,
        ))

    state = SimpleNamespace(
        graph=[],
        started=set(),
        calls=[],
        broken=None,
        ready=True,
        fragments={},
        dropins={},
    )

    def run(args, **kwargs):
        state.calls.append(args)
        assert kwargs["timeout"] <= 5
        assert args[:2] == ["/usr/bin/systemctl", "--user"]
        verb = args[2]
        if state.broken == verb:
            raise subprocess.CalledProcessError(1, args, stderr=b"failure")
        if verb == "show":
            name = args[-1]
            return SimpleNamespace(
                stdout="\n".join(
                    [
                        "LoadState="
                        + ("loaded" if name in state.fragments else "not-found"),
                        "FragmentPath=" + state.fragments.get(name, ""),
                        "DropInPaths=" + " ".join(state.dropins.get(name, [])),
                    ]
                )
            )
        if verb == "daemon-reload":
            state.fragments.update(
                {
                    p.name: str(p)
                    for p in (tmp_path / "config/systemd/user").glob("*.service")
                }
            )
        elif verb == "enable":
            assert "--now" in args
            state.started.update(a for a in args if a.endswith(".service"))
            if len(state.started) == 3 and state.ready:
                state.graph = complete_graph()
        else:
            pytest.fail(f"unexpected host operation {args}")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.shutil, "which", lambda name, **kw: "/usr/bin/" + name)
    env = dict(
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_RUNTIME_DIR=str(tmp_path / "run"),
        PATH="/usr/bin",
    )
    (tmp_path / "run").mkdir()
    setup = module.ManagedMicrophone(
        lambda: copy.deepcopy(state.graph), env=env, timeout=0.03
    )
    return setup, state, tmp_path


def test_existing_manual_graph_is_reused_without_install_or_service_calls(machine):
    setup, state, root = machine
    state.graph = complete_graph()
    setup.ensure()
    assert state.calls == []
    assert not (root / "config").exists()


def test_empty_host_creates_muted_persistent_route_and_reuses_it(machine):
    setup, state, root = machine
    setup.ensure()
    assert len(state.started) == 3
    units = list((root / "config/systemd/user").glob("*.service"))
    assert len(units) == 3
    from models.audio_routing.pipewire_gate import parse_graph

    assert parse_graph(state.graph)["muted"] is True
    before = {p.name: p.stat().st_mtime_ns for p in units}
    calls = len(state.calls)
    setup.ensure()
    assert len(state.calls) == calls
    assert before == {p.name: p.stat().st_mtime_ns for p in units}
    assert all("restart" not in c for c in state.calls)


@pytest.mark.parametrize("fault", ["partial", "wrong_marker", "duplicate"])
def test_foreign_or_ambiguous_graph_is_not_replaced(machine, fault):
    setup, state, root = machine
    state.graph = complete_graph()
    if fault == "partial":
        state.graph.pop()
    elif fault == "wrong_marker":
        state.graph[1]["info"]["props"]["vrct.managed.route"] = "other"
    else:
        state.graph.append(copy.deepcopy(state.graph[1]))
    with pytest.raises(RuntimeError, match="managed_setup_conflict"):
        setup.ensure()
    assert not state.started
    assert not (root / "config/systemd/user").exists()


@pytest.mark.parametrize("kind", ["file", "symlink", "manager", "dropin"])
def test_foreign_service_configuration_is_preserved(machine, kind):
    setup, state, root = machine
    name = "vrct-managed-source.service"
    directory = root / "config/systemd/user"
    directory.mkdir(parents=True)
    path = directory / name
    if kind == "file":
        path.write_text("user content")
    elif kind == "symlink":
        path.symlink_to("/dev/null")
    elif kind == "manager":
        state.fragments[name] = "/etc/systemd/user/" + name
    else:
        state.dropins[name] = ["/etc/systemd/user/" + name + ".d/override.conf"]
    with pytest.raises(RuntimeError, match="managed_setup_conflict"):
        setup.ensure()
    assert not state.started
    if kind == "file":
        assert path.read_text() == "user content"
    if kind == "symlink":
        assert path.is_symlink()


@pytest.mark.parametrize("verb", ["show", "daemon-reload", "enable"])
def test_os_failure_never_reports_ready(machine, verb):
    setup, state, _ = machine
    state.broken = verb
    with pytest.raises(RuntimeError, match="managed_setup_service_failed"):
        setup.ensure()
    assert not state.graph


def test_service_start_success_without_endpoints_is_a_failure(machine):
    setup, state, _ = machine
    state.ready = False
    with pytest.raises(RuntimeError, match="managed_setup_timeout"):
        setup.ensure()
    assert not state.graph


def test_failed_start_can_be_retried_without_replacing_units(machine):
    setup, state, root = machine
    state.broken = "enable"
    with pytest.raises(RuntimeError):
        setup.ensure()
    before = {
        p.name: p.read_bytes() for p in (root / "config/systemd/user").glob("*.service")
    }
    state.broken = None
    setup.ensure()
    assert state.graph
    assert before == {
        p.name: p.read_bytes() for p in (root / "config/systemd/user").glob("*.service")
    }


def test_missing_tools_and_custom_remote_do_not_modify_host(machine, monkeypatch):
    setup, state, root = machine
    from models.audio_routing import managed_microphone as module

    monkeypatch.setattr(module.shutil, "which", lambda *a, **kw: None)
    with pytest.raises(RuntimeError, match="managed_setup_tools_missing"):
        setup.ensure()
    assert not state.calls
    setup.env["PIPEWIRE_REMOTE"] = "private-test"
    with pytest.raises(RuntimeError, match="managed_setup_custom_remote"):
        setup.ensure()
    assert not (root / "config").exists()


def test_saved_manual_route_is_not_duplicated_before_daemon_loads_it(machine):
    setup, state, root = machine
    manual = root / "config/pipewire/pipewire.conf.d/90-vrct-managed.conf"
    manual.parent.mkdir(parents=True)
    manual.write_text("existing daemon configuration")
    with pytest.raises(RuntimeError, match="managed_setup_manual_config_pending"):
        setup.ensure()
    assert not state.started and not state.calls
    assert manual.read_text() == "existing daemon configuration"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Concurrent provisioning verifies Linux flock serialization")
def test_concurrent_preparation_installs_only_one_route(machine):
    from concurrent.futures import ThreadPoolExecutor

    setup, state, root = machine
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(setup.ensure) for _ in range(2)]
        for call in calls:
            call.result()
    assert len([call for call in state.calls if call[2] == "enable"]) == 1
    assert len(list((root / "config/systemd/user").glob("*.service"))) == 3


def test_partial_owned_route_can_be_completed_without_removing_endpoint(machine):
    setup, state, _ = machine
    setup.ensure()
    state.graph.pop()
    for item in state.graph:
        if item["type"].endswith(":Node"):
            item["info"]["props"]["vrct.managed.owner"] = "vrct-vox-service-v1"
    setup.ensure()
    assert len(state.graph) == 5
