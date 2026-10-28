"""Version checks fail before installing anything or altering an incompatible environment."""
import hashlib

import pytest

import launcher


@pytest.fixture
def launcher_env(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "VENV", tmp_path / ".venv")
    monkeypatch.setattr(launcher, "REQS", tmp_path / "requirements.txt")
    launcher.REQS.write_text("streamlit>=1.66,<2\n", encoding="utf-8")
    monkeypatch.setattr(launcher.subprocess, "check_call", lambda *args, **kwargs: pytest.fail("Must not install dependencies"))
    return launcher.venv_python()


@pytest.mark.parametrize("version", [(3, 10), (3, 11)])
def test_old_host_python_is_rejected_before_creating_environment(launcher_env, monkeypatch, version):
    monkeypatch.setattr(launcher.sys, "version_info", version)
    monkeypatch.setattr(launcher.venv, "create", lambda *args, **kwargs: pytest.fail("Must not create an environment"))
    with pytest.raises(SystemExit, match="Python 3.12 or newer is required"):
        launcher.ensure_env()
    assert not launcher_env.exists()


@pytest.mark.parametrize("version", ["3.11", "3.12", "3.13"])
def test_existing_environment_must_also_use_supported_python(launcher_env, monkeypatch, version):
    monkeypatch.setattr(launcher.sys, "version_info", (3, 12))
    launcher_env.parent.mkdir(parents=True)
    launcher_env.touch()
    stamp = launcher.VENV / ".requirements.sha1"
    stamp.write_text(hashlib.sha1(launcher.REQS.read_bytes()).hexdigest())
    checks = []

    def interpreter_version(args, **kwargs):
        checks.append(args)
        return version + "\n"

    monkeypatch.setattr(launcher.subprocess, "check_output", interpreter_version)
    if version == "3.11":
        with pytest.raises(SystemExit, match=r"existing \.venv uses Python 3.11.*Recreate \.venv"):
            launcher.ensure_env()
    else:
        launcher.ensure_env()
    assert checks[0][:2] == [str(launcher_env), "-c"]
    assert launcher_env.exists()
