"""A slow start must leave a record that survives the next start, without private data."""

from collections import namedtuple
import json
from pathlib import Path

import pytest

import startup_timing
import utils


@pytest.fixture
def timing(monkeypatch, tmp_path):
    monkeypatch.setenv("VRCT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(startup_timing, "_stages", [])
    monkeypatch.setattr(startup_timing, "_slow_getters", [])
    monkeypatch.setattr(startup_timing, "_system_before", None)
    monkeypatch.setattr(startup_timing, "_finished", False)
    monkeypatch.setattr(utils, "printLog", lambda *args: None)
    return tmp_path / "logs" / "startup_timing.log"


def stage_names():
    return [row[0] for row in startup_timing._stages]


def test_mark_records_wall_and_cpu_seconds(timing):
    startup_timing.mark("first")
    name, wall, cpu = startup_timing._stages[0]
    assert name == "first" and wall >= 0 and cpu >= 0


def test_known_log_lines_end_stages_and_others_do_not(timing):
    startup_timing.note("Init Translation Engine Status")
    startup_timing.note("Start check DeepL_API")
    startup_timing.note({"not": "a string"})
    assert stage_names() == ["check_model_weights"]


def test_every_init_stage_line_is_still_logged_by_the_controller():
    source = (Path(startup_timing.__file__).parent / "controller.py").read_text(encoding="utf-8")
    for line in startup_timing._STAGE_ENDED_BY:
        assert f'printLog("{line}")' in source


def test_only_slow_getters_are_kept(timing, monkeypatch):
    monkeypatch.setattr(startup_timing, "_SLOW_GETTER_SECONDS", 0)
    assert startup_timing.timed("/get/data/slow", lambda value: value)(1) == 1
    monkeypatch.setattr(startup_timing, "_SLOW_GETTER_SECONDS", 60)
    startup_timing.timed("/get/data/quick", lambda: None)()
    assert [row[0] for row in startup_timing._slow_getters] == ["/get/data/slow"]


def test_a_failing_getter_still_raises(timing):
    def failing():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        startup_timing.timed("/get/data/broken", failing)()


def test_finish_appends_one_line_per_start_and_stops_recording(timing, monkeypatch):
    timing.parent.mkdir()
    timing.write_text('{"earlier": true}\n', encoding="utf-8")
    startup_timing.mark("import_config")
    startup_timing.finish()
    startup_timing.finish()
    startup_timing.mark("too_late")
    lines = timing.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[1])
    assert [row[0] for row in record["stages"]] == ["import_config", "collect_settings"]
    assert "too_late" not in stage_names()


def test_the_record_holds_no_paths(timing, tmp_path):
    startup_timing.mark("import_config")
    startup_timing.finish()
    text = timing.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "\\\\") not in text
    assert set(json.loads(text)) == {"at", "total", "cpu", "before_python", "system_busy_percent",
                                     "stages", "slow_getters"}


def test_busy_percent_comes_from_system_cpu_times(timing, monkeypatch):
    Times = namedtuple("Times", "user idle")
    monkeypatch.setattr(startup_timing, "_system_before", Times(user=100, idle=100))
    monkeypatch.setattr(startup_timing, "_systemTimes", lambda: Times(user=170, idle=130))
    assert startup_timing._systemBusyPercent() == 70.0


def test_finish_does_not_fail_the_start(timing, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    logged = []
    monkeypatch.setattr(utils, "openTraceLog", broken)
    monkeypatch.setattr(utils, "errorLogging", lambda: logged.append(True))
    startup_timing.finish()
    assert logged == [True]
