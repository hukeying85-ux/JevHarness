"""Tests for auto_jev.desktop_hub, repaired desktop-base scripts, and skill installation."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import threading

import pytest

from auto_jev import desktop_hub

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-skill.py"
DESKTOP_BASE_DIR = REPO_ROOT / "skills" / "desktop-hub" / "desktop-base"


def _load_installer():
    spec = importlib.util.spec_from_file_location("jev_skill_installer_ext", INSTALL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return cp.stdout.strip()


def test_desktop_base_scripts_are_pure_ascii_and_free_of_legacy_bugs():
    checked = list(DESKTOP_BASE_DIR.glob("*.ps1")) + list(DESKTOP_BASE_DIR.glob("*.cs"))
    assert len(checked) >= 3
    for path in checked:
        raw = path.read_bytes()
        non_ascii = [b for b in raw if b > 0x7F]
        assert not non_ascii, f"{path.name} contains non-ASCII bytes"

    repaired_ps1 = (DESKTOP_BASE_DIR / "hub-watch-desktop.ps1").read_text(encoding="ascii")
    assert desktop_hub.audit_watcher_script_issues(repaired_ps1) == []

    silent_cs = (DESKTOP_BASE_DIR / "ArenaSilentRun.cs").read_text(encoding="ascii")
    assert "isLongRunningLoop" in silent_cs
    assert "p.WaitForExit();" in silent_cs


def test_audit_detects_all_legacy_watcher_bugs():
    legacy_snippet = """
    param(
        [string]$BaseDirName = 'leanrea-626378d6-leanrea'
    )
    $script:ActiveRepoNames = @('goutoujunshi', 'leanrea', 'skills')
    $candidates = @('E:\\hermes\\git\\cmd\\git.exe', 'C:\\Program Files\\Git\\cmd\\git.exe')
    """
    issues = desktop_hub.audit_watcher_script_issues(legacy_snippet)
    issue_ids = {item["id"] for item in issues}
    assert issue_ids == {
        "self-evict-basedir",
        "isolated-local-credentials",
        "missing-jevharness-seed",
        "missing-f-drive-git-python",
    }


def test_install_all_skills_copies_jev_harness_and_desktop_hub(tmp_path):
    installer = _load_installer()
    project = tmp_path / "workspace"
    project.mkdir()
    rc = installer.main(["--skill", "all", "--target", "both", "--scope", "project", "--project", str(project)])
    assert rc == 0
    for client_dir in (".agents", ".claude"):
        for skill in ("jev-harness", "desktop-hub"):
            installed = project / client_dir / "skills" / skill / "SKILL.md"
            assert installed.is_file()


def test_hub_task_requires_explicit_allow_exec():
    safe = desktop_hub.build_hub_task_payload(
        note="copy artifact only",
        copy_files=[{"source": "results/a.json", "target": "C:\\0github\\results\\a.json"}],
    )
    assert safe["status"] == "pending"
    assert "powershell" not in safe

    with pytest.raises(desktop_hub.DesktopHubError, match="allow_exec"):
        desktop_hub.build_hub_task_payload(powershell=["Get-Date"])

    authorized = desktop_hub.build_hub_task_payload(powershell=["Get-Date"], allow_exec=True)
    assert authorized["powershell"] == ["Get-Date"]


def test_gmx_argv_allowlist_and_metacharacter_rejection():
    desktop_hub.validate_gmx_argv(["--version"])
    desktop_hub.validate_gmx_argv(["solvate", "-cs", "spc216.gro", "-box", "2.5"])
    with pytest.raises(desktop_hub.DesktopHubError, match="allowlist"):
        desktop_hub.validate_gmx_argv(["rm", "-rf", "/"])
    with pytest.raises(desktop_hub.DesktopHubError, match="metacharacters"):
        desktop_hub.validate_gmx_argv(["--version", "; whoami"])


def test_lan_bridge_client_roundtrip():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"schema": "cgmd.mailbox.result.v1", "status": "ok", "path": self.path}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            body = json.dumps({
                "schema": "cgmd.mailbox.result.v1",
                "status": "ok",
                "kind": req["kind"],
                "args": req["args"],
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        probe = desktop_hub.probe_lan_candidates(["127.0.0.1"], port=port)
        assert probe["connected"] is True
        assert probe["health"]["status"] == "ok"

        res = desktop_hub.lan_job("127.0.0.1", "gmx", {"argv": ["--version"]}, port=port)
        assert res["status"] == "ok"
        assert res["args"]["argv"] == ["--version"]
    finally:
        server.shutdown()
        server.server_close()


def test_base_handshake_and_receipt_verification_over_git(tmp_path):
    remote = tmp_path / "origin.git"
    remote.mkdir()
    _git(remote, "init", "--bare")

    work = tmp_path / "JevHarness"
    work.mkdir()
    _git(work, "init", "-b", "arena/test-branch")
    _git(work, "config", "user.name", "Test")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "remote", "add", "origin", str(remote))

    hs = desktop_hub.write_handshake(work, round_num=1, note="roundtrip test")
    assert hs.is_file()
    _git(work, "add", "results/status/handshake.json")
    _git(work, "commit", "-m", "queue handshake")
    source_sha = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "origin", "arena/test-branch")

    # Simulate desktop git-sync-hub cloning, writing hub_sync_receipt.json, and pushing back.
    desk = tmp_path / "desk-clone"
    _git(tmp_path, "clone", "-b", "arena/test-branch", str(remote), str(desk))
    _git(desk, "config", "user.name", "git-sync-hub (DESKTOP-IEUDGS5)")
    _git(desk, "config", "user.email", "hub@local")
    receipt_path = desk / "results" / "status" / "hub_sync_receipt.json"
    receipt_path.write_text(
        json.dumps({
            "status": "synced",
            "host": "DESKTOP-IEUDGS5",
            "repo": "JevHarness",
            "branch": "arena/test-branch",
            "source_commit": source_sha,
            "synced_at_utc": "2026-10-29T07:40:00Z",
            "local_results_dir": "C:\\0github\\results\\JevHarness-test-branch",
        }),
        encoding="utf-8",
    )
    _git(desk, "add", "results/status/hub_sync_receipt.json")
    _git(desk, "commit", "-m", "hub(DESKTOP-IEUDGS5): exec & sync")
    _git(desk, "push", "origin", "arena/test-branch")

    waited = desktop_hub.wait_for_base_receipt(
        work,
        expected_source_sha=source_sha,
        timeout=5,
        interval=1,
        pull_on_receipt=True,
    )
    assert waited["status"] == "ok"
    assert waited["verified_live_in_session"] is True
    assert waited["receipt"]["host"] == "DESKTOP-IEUDGS5"

    base_state = desktop_hub.read_base_status(work)
    assert base_state["has_receipt"] is True
    assert base_state["receipt_commit_verified_in_git"] is True
    assert base_state["host"] == "DESKTOP-IEUDGS5"


def test_probe_0fuye_and_branch_lock_guard(tmp_path, monkeypatch):
    remote_0fuye = tmp_path / "0fuye.git"
    remote_0fuye.mkdir()
    _git(remote_0fuye, "init", "--bare")

    src = tmp_path / "0fuye-src"
    src.mkdir()
    _git(src, "init", "-b", "arena/32cd826e-0fuye")
    _git(src, "config", "user.name", "Desk")
    _git(src, "config", "user.email", "desk@example.com")
    _git(src, "remote", "add", "origin", str(remote_0fuye))

    status_dir = src / "results" / "status"
    status_dir.mkdir(parents=True)
    (status_dir / "hub_heartbeat.json").write_text(
        json.dumps({"schema": "cgmd.heartbeat.v1", "at": "2026-10-29T15:30:00+08:00", "host": "DESKTOP-IEUDGS5"}),
        encoding="utf-8",
    )
    (status_dir / "gmx_smoke.json").write_text(
        json.dumps({
            "schema": "cgmd.gmxsmoke.v1",
            "status": "ok",
            "ps_completed": 100,
            "stages": [{"stage": "mdrun-md-gpu", "stderr_tail": ["Performance:      576.012        0.042"]}],
        }),
        encoding="utf-8",
    )
    _git(src, "add", ".")
    _git(src, "commit", "-m", "initial status")
    _git(src, "push", "origin", "arena/32cd826e-0fuye")

    job_id = desktop_hub.mailbox_send(src, "ping", note="unit test")
    assert job_id

    telemetry = desktop_hub.probe_0fuye_remote(repo_url=str(remote_0fuye), branch="arena/32cd826e-0fuye")
    assert telemetry["host"] == "DESKTOP-IEUDGS5"
    assert telemetry["smoke_summary"]["ns_per_day"] == pytest.approx(576.012)
    assert telemetry["mailbox_queue"]["pending"] == [job_id]

    # Branch lock guard blocks cross-branch pushes when JEV_LOCKED_BRANCH is active.
    monkeypatch.setenv("JEV_LOCKED_BRANCH", "arena/f5038599-jevharness")
    with pytest.raises(desktop_hub.DesktopHubError, match="JEV_LOCKED_BRANCH"):
        desktop_hub.mailbox_send(src, "ping")
