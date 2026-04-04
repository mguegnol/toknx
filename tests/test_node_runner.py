import os
from pathlib import Path

from toknx_node import runner


def test_build_exo_env_uses_absolute_resource_and_dashboard_paths(monkeypatch, tmp_path):
    resources_dir = (tmp_path / "resources").resolve()
    resources_dir.mkdir()

    monkeypatch.setattr(runner.Path, "home", staticmethod(lambda: Path(tmp_path)))
    monkeypatch.setattr(runner, "_find_exo_resources", lambda: str(resources_dir))
    monkeypatch.delenv("EXO_RESOURCES_DIR", raising=False)
    monkeypatch.delenv("EXO_DASHBOARD_DIR", raising=False)

    env = runner._build_exo_env()

    assert env["EXO_RESOURCES_DIR"] == str(resources_dir)
    assert os.path.isabs(env["EXO_DASHBOARD_DIR"])
    assert Path(env["EXO_DASHBOARD_DIR"]).joinpath("index.html").exists()
