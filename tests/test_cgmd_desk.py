"""Tests for the client-only 0fuye desktop hub adapter and single-base hygiene."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import types

import pytest

from auto_jev import cgmd_desk

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-skill.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("jev_skill_installer_desk", INSTALL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_single_base_rule_forbids_second_watcher_scripts():
    """0fuye §1 cross-repo ban: JevHarness must never ship .ps1/.vbs/.cs pollers."""
    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO_ROOT, text=True
    ).splitlines()
    offenders = [
        rel for rel in tracked
        if Path(rel).suffix.lower() in cgmd_desk.FORBIDDEN_SECOND_WATCHER_EXTENSIONS
    ]
    assert offenders == [], f"Second-watcher scripts violate 0fuye single-base ban: {offenders}"


def test_no_heavy_trajectory_files_tracked():
    """0fuye hard rule #4: .xtc/.trr/.tpr/.gro/.edr/.edv/.cpt never enter Git."""
    tracked = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO_ROOT, text=True
    ).splitlines()
    offenders = [
        rel for rel in tracked
        if Path(rel).suffix.lower() in cgmd_desk.FORBIDDEN_TRAJECTORY_EXTENSIONS
    ]
    assert offenders == []


def test_verify_smoke_result_enforces_all_six_step2_assertions():
    valid_payload = {
        "schema": "cgmd.mailbox.result.v1",
        "id": "20261029T073120-60bd",
        "kind": "smoke",
        "status": "ok",
        "seconds": 30.78,
        "finished_at": "2026-10-29T15:32:29+08:00",
        "detail": {
            "report": {
                "ps_completed": 100,
                "accelerator": "gpu",
                "seconds_total": 22.4,
                "mdrun": {
                    "finished": True,
                    "performance_ns_per_day": 617.155,
                },
                "stages": [
                    {"stage": "grompp-md", "returncode": 0, "seconds": 0.1},
                    {"stage": "mdrun-md-gpu", "returncode": 0, "seconds": 15.32},
                ],
            }
        },
    }
    verdict = cgmd_desk.verify_smoke_result(valid_payload)
    assert verdict["all_passed"] is True
    assert verdict["performance_ns_per_day"] == pytest.approx(617.155)
    assert verdict["accelerator"] == "gpu"

    # Putting accelerator under report.progress instead of report.accelerator must fail.
    wrong_path = {
        **valid_payload,
        "detail": {
            "report": {
                **valid_payload["detail"]["report"],
                "accelerator": None,
                "progress": {"accelerator": "gpu"},
            }
        },
    }
    bad_verdict = cgmd_desk.verify_smoke_result(wrong_path)
    assert bad_verdict["all_passed"] is False
    assert bad_verdict["checks"]["result.detail.report.accelerator == 'gpu'"] is False

    # Non-zero mdrun-md-gpu stage returncode must fail.
    failed_gpu = {
        **valid_payload,
        "detail": {
            "report": {
                **valid_payload["detail"]["report"],
                "stages": [{"stage": "mdrun-md-gpu", "returncode": 1}],
            }
        },
    }
    assert cgmd_desk.verify_smoke_result(failed_gpu)["all_passed"] is False


def test_verify_origin_locked_rejects_foreign_repo(tmp_path):
    repo = tmp_path / "fake-0fuye"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/someone-else/0fuye.git"],
        cwd=repo,
        check=True,
    )
    with pytest.raises(cgmd_desk.DeskClientError, match="Refusing untrusted"):
        cgmd_desk.verify_origin_locked(repo)

    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/hukeying85-ux/0fuye.git"],
        cwd=repo,
        check=True,
    )
    assert cgmd_desk.verify_origin_locked(repo) == "https://github.com/hukeying85-ux/0fuye.git"


def test_dispatch_skips_lan_in_cloud_sandbox_and_classifies_403(monkeypatch, tmp_path):
    fake_checkout = tmp_path / "0fuye"
    fake_checkout.mkdir()

    class FakeBridgeError(RuntimeError):
        pass

    class FakeMailboxError(RuntimeError):
        pass

    bridge_called = False

    def fake_ping(*_args, **_kwargs):
        nonlocal bridge_called
        bridge_called = True
        return {"status": "ok"}

    fake_bridge = types.SimpleNamespace(BridgeError=FakeBridgeError, ping=fake_ping)
    fake_mailbox = types.SimpleNamespace(
        SCHEMA_RESULT="cgmd.mailbox.result.v1",
        MailboxError=FakeMailboxError,
        send=lambda *_a, **_kw: (_ for _ in ()).throw(
            FakeMailboxError(
                "remote: Permission to hukeying85-ux/0fuye.git denied to hukeying85-ux. "
                "The requested URL returned error: 403"
            )
        ),
        snapshot=lambda *_a, **_kw: {"done": ["20261029T075318-79cd"], "pending": []},
        read_result=lambda *_a, **_kw: {
            "id": "20261029T075318-79cd",
            "kind": "ping",
            "status": "ok",
            "summary": "DESKTOP-IEUDGS5 alive, gmx 2025.1, 1 gpu(s)",
        },
    )

    monkeypatch.setattr(cgmd_desk, "ensure_0fuye_client", lambda *_a, **_kw: fake_checkout)
    monkeypatch.setattr(cgmd_desk, "load_0fuye_modules", lambda *_a, **_kw: (fake_mailbox, fake_bridge))
    monkeypatch.setattr(cgmd_desk, "is_cloud_sandbox", lambda *_a, **_kw: True)
    monkeypatch.setattr(
        cgmd_desk,
        "_run_cmd",
        lambda *_a, **_kw: (1, '{"message":"Resource not accessible by integration","status":"403"}', ""),
    )

    result = cgmd_desk.dispatch_job("ping", lan_host="192.168.110.226")
    assert bridge_called is False
    assert result["status"] == "blocked_by_token_scope"
    assert result["diagnosis"]["arena_repo_scoped_token"] is True
    assert result["diagnosis"]["desktop_worker_fault"] is False
    assert result["diagnosis"]["user_paste_required"] is False
    assert result["latest_verified_on_mailbox"]["id"] == "20261029T075318-79cd"


def test_dispatch_lan_degrades_to_mailbox_when_not_sandboxed(monkeypatch, tmp_path):
    fake_checkout = tmp_path / "0fuye"
    fake_checkout.mkdir()

    class FakeBridgeError(RuntimeError):
        pass

    class FakeMailboxError(RuntimeError):
        pass

    fake_bridge = types.SimpleNamespace(
        BridgeError=FakeBridgeError,
        ping=lambda *_a, **_kw: (_ for _ in ()).throw(FakeBridgeError("unreachable")),
    )
    fake_mailbox = types.SimpleNamespace(
        SCHEMA_RESULT="cgmd.mailbox.result.v1",
        MailboxError=FakeMailboxError,
        send=lambda *_a, **_kw: "20261029T080000-abcd",
        wait=lambda *_a, **_kw: {
            "id": "20261029T080000-abcd",
            "kind": "ping",
            "status": "ok",
            "summary": "DESKTOP-IEUDGS5 alive, gmx 2025.1, 1 gpu(s)",
        },
    )

    monkeypatch.setattr(cgmd_desk, "ensure_0fuye_client", lambda *_a, **_kw: fake_checkout)
    monkeypatch.setattr(cgmd_desk, "load_0fuye_modules", lambda *_a, **_kw: (fake_mailbox, fake_bridge))
    monkeypatch.setattr(cgmd_desk, "is_cloud_sandbox", lambda *_a, **_kw: False)

    result = cgmd_desk.dispatch_job("ping", lan_host="192.168.110.226")
    assert result["status"] == "ok"
    assert result["transport"] == "hub_mailbox"
    assert result["id"] == "20261029T080000-abcd"


def test_latest_outbox_by_kind_sorts_by_iso_finished_at_over_lexical_id(monkeypatch, tmp_path):
    records = {
        "20261029T075318-79cd": {
            "id": "20261029T075318-79cd",
            "kind": "ping",
            "status": "ok",
            "finished_at": "2026-10-29T15:53:57+08:00",
        },
        "selftest-20261029T132102": {
            "id": "selftest-20261029T132102",
            "kind": "ping",
            "status": "ok",
            "finished_at": "2026-10-29T13:21:07+08:00",
        },
    }
    fake_mailbox = types.SimpleNamespace(
        snapshot=lambda *_a, **_kw: {"done": sorted(records.keys()), "pending": []},
        read_result=lambda _repo, jid, **_kw: records.get(jid),
    )
    monkeypatch.setattr(cgmd_desk, "load_0fuye_modules", lambda *_a, **_kw: (fake_mailbox, None))
    latest = cgmd_desk.latest_outbox_by_kind(tmp_path, "ping")
    assert latest is not None
    assert latest["id"] == "20261029T075318-79cd"


def test_dispatch_supports_peer_write_repo_and_reads_0fuye_outbox(monkeypatch, tmp_path):
    desk_checkout = tmp_path / "0fuye"
    peer_checkout = tmp_path / "JevHarness"
    desk_checkout.mkdir()
    peer_checkout.mkdir()

    seen: dict[str, str] = {}

    class FakeBridgeError(RuntimeError):
        pass

    class FakeMailboxError(RuntimeError):
        pass

    def fake_send(repo, kind, *_a, **_kw):
        seen["write_repo"] = repo
        return "20261029T083000-beef"

    def fake_wait(repo, job_id, *_a, **_kw):
        seen["read_repo"] = repo
        return {"id": job_id, "kind": "ping", "status": "ok"}

    fake_bridge = types.SimpleNamespace(BridgeError=FakeBridgeError)
    fake_mailbox = types.SimpleNamespace(
        SCHEMA_RESULT="cgmd.mailbox.result.v1",
        MailboxError=FakeMailboxError,
        send=fake_send,
        wait=fake_wait,
    )

    monkeypatch.setattr(cgmd_desk, "ensure_0fuye_client", lambda *_a, **_kw: desk_checkout)
    monkeypatch.setattr(cgmd_desk, "load_0fuye_modules", lambda *_a, **_kw: (fake_mailbox, fake_bridge))
    monkeypatch.setattr(cgmd_desk, "is_cloud_sandbox", lambda *_a, **_kw: True)

    result = cgmd_desk.dispatch_job("ping", write_repo=peer_checkout)
    assert result["status"] == "ok"
    assert seen["write_repo"] == str(peer_checkout.resolve())
    assert seen["read_repo"] == str(desk_checkout.resolve())


def test_install_skill_supports_cgmd_desk_and_all(tmp_path):
    installer = _load_installer()
    assert "cgmd-desk" in installer.available_skills()
    project = tmp_path / "proj"
    project.mkdir()
    rc = installer.main(["--skill", "all", "--target", "both", "--scope", "project", "--project", str(project)])
    assert rc == 0
    for client_dir in (".agents", ".claude"):
        for skill_name in ("jev-harness", "cgmd-desk"):
            assert (project / client_dir / "skills" / skill_name / "SKILL.md").is_file()
