import asyncio
from importlib.resources import files
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ux_guardian.cli import app
from ux_guardian.report.models import Report
from ux_guardian.report.render import render
from ux_guardian.run import replay_pipeline


@pytest.mark.parametrize(("name", "count"), [("m2_clean", 0), ("m2_mobile_overlay", 1)])
def test_recorded_checks_replay_and_snapshot(
    name: str,
    count: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ux_guardian import run

    def no_live_call(*args, **kwargs):
        raise AssertionError("Fixture replay must not acquire evidence")

    monkeypatch.setattr(run, "run_checks", no_live_call)
    monkeypatch.setattr(run, "fetch_precheck", no_live_call)
    resource = files("ux_guardian.fixtures").joinpath(name + ".json")
    saved = Report.model_validate_json(resource.read_text(encoding="utf-8"))
    assert len(saved.check_results) == 12 and len(saved.fetch.pages) == 6
    assert not saved.fetch.service_error and not saved.fetch.flags
    assert not saved.runs and saved.cost.total_usd == 0
    report = asyncio.run(replay_pipeline(preview_url=saved.preview_url, pr=1, template=saved))
    assert len(report.findings) == count
    if count:
        assert report.findings[0].severity == "P1"
        assert "mobile" in report.findings[0].title
    assert render(saved) == (Path("tests") / "snapshots" / (name + ".md")).read_text(
        encoding="utf-8"
    )
    fixture = tmp_path / "fixture.json"
    fixture.write_text(saved.model_dump_json(by_alias=True), encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--preview-url",
            "https://offline.invalid",
            "--pr",
            "3",
            "--dry-run",
            "--checks-fixture",
            str(fixture),
            "--output",
            str(tmp_path / "report"),
        ],
    )
    assert result.exit_code == 0, result.output
    replay = Report.model_validate_json((tmp_path / "report" / "report.json").read_text())
    assert len(replay.findings) == count
    assert not replay.runs
