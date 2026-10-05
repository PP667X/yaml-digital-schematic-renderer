from pathlib import Path
import subprocess

import pytest

import install


@pytest.mark.parametrize("layout,dev", [(False, False), (True, False), (False, True), (True, True)])
def test_install_plan_uses_local_python_and_optional_extras(tmp_path, layout, dev):
    python = install.venv_python(tmp_path / ".venv")
    commands = install.install_commands(python, layout=layout, dev=dev)
    assert all(command[0] == str(python) for command in commands)
    assert commands[0][1:5] == ["-m", "pip", "install", "-e"]
    assert ("layout" in commands[0][-1]) == layout
    assert ("test" in commands[0][-1]) == dev
    npm = [command for command in commands if "from nodejs_wheel import npm" in command[-1]]
    assert bool(npm) == layout
    if npm:
        assert "'ci'" in npm[0][-1] and "'--ignore-scripts'" in npm[0][-1]


def test_installer_preserves_conflicting_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "ROOT", tmp_path)
    folder = tmp_path / ".venv"
    folder.mkdir()
    marker = folder / "personal.txt"
    marker.write_text("keep", encoding="utf-8")
    assert install.main([]) == 1
    assert marker.read_text(encoding="utf-8") == "keep"


def existing_venv(tmp_path):
    folder = tmp_path / ".venv"
    python = install.venv_python(folder)
    python.parent.mkdir(parents=True)
    python.touch()
    (folder / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")


def test_installer_reuses_venv_and_runs_from_project_root(tmp_path, monkeypatch):
    existing_venv(tmp_path)
    monkeypatch.setattr(install, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(install.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    monkeypatch.setenv("PIP_TARGET", "unwanted-target")
    assert install.main([]) == 0
    assert len(calls) == 2
    for _, kwargs in calls:
        assert kwargs["cwd"] == tmp_path and kwargs["check"]
        assert kwargs["env"]["PIP_REQUIRE_VIRTUALENV"] == "true"
        assert "PIP_TARGET" not in kwargs["env"]


def test_installer_returns_failure_when_dependency_install_fails(tmp_path, monkeypatch):
    existing_venv(tmp_path)
    monkeypatch.setattr(install, "ROOT", tmp_path)

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(install.subprocess, "run", fail)
    assert install.main([]) == 1
