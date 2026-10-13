"""The acceptance checker must catch the problems it exists to catch."""
from src import acceptance


def test_scanner_finds_machine_specific_paths_and_secrets(tmp_path, monkeypatch):
    bad = tmp_path / "src"
    bad.mkdir()
    (bad / "x.py").write_text('path = "C:\\\\Users\\\\Student\\\\Desktop\\\\data.csv"\npassword = "hunter2hunter2"\n')
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n")
    assert acceptance.a3()[0] == "fail"
    assert acceptance.a4()[0] == "fail"


def test_scanner_accepts_placeholders_and_container_paths(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text('p = "/opt/pipeline"\nPOSTGRES_PASSWORD = os.environ["X"]\n')
    (tmp_path / ".env.example").write_text("POSTGRES_PASSWORD=change_me\n")
    (tmp_path / ".gitignore").write_text(".env\n")
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    assert acceptance.a3()[0] == "pass"
    assert acceptance.a4()[0] == "pass"


def test_unpinned_or_old_xgboost_is_rejected(tmp_path, monkeypatch):
    for n in ("Dockerfile", "docker-compose.yml"):
        (tmp_path / n).write_text("x")
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    (tmp_path / "requirements.txt").write_text("pandas==2.3.3\nxgboost==3.2.0\n")
    status, msg = acceptance.a5()
    assert status == "fail" and "0.75087" in msg
    (tmp_path / "requirements.txt").write_text("pandas\nxgboost==3.4.1\n")
    assert acceptance.a5()[0] == "fail"
    (tmp_path / "requirements.txt").write_text("pandas==2.3.3\nxgboost==3.4.1\n")
    assert acceptance.a5()[0] == "pass"
