import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from arena_api import store
from arena_api.import_logs import main

type SampleLog = Callable[..., dict[str, Any]]


def write(folder: Path, name: str, log: dict[str, Any]) -> None:
    (folder / f"{name}.json").write_text(json.dumps(log), encoding="utf-8")


def test_imports_valid_logs_under_a_prefix_and_reports_the_rest(
    database: str, sample_log: SampleLog, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "sim_0001", sample_log("alice", "bob"))
    write(tmp_path, "sim_0002", sample_log("carol", "dave"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    code = main([str(tmp_path), "--prefix", "gate-"])

    assert code == 0
    assert [s.id for s in store.list_finished()] == ["gate-sim_0001", "gate-sim_0002"]
    out = capsys.readouterr().out
    assert "imported 2" in out and "skipped 1" in out and "broken" in out


def test_importing_twice_adds_nothing(
    database: str, sample_log: SampleLog, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "sim_0001", sample_log())

    main([str(tmp_path)])
    main([str(tmp_path)])

    assert len(store.list_finished()) == 1
    assert "already there 1" in capsys.readouterr().out


def test_a_missing_folder_is_an_error(
    database: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "absent")]) == 1
    assert "not a folder" in capsys.readouterr().err
