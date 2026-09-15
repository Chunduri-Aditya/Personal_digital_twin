"""Tests for twin.audit (one JSON line per model-backed request, request text reduced to its sha256) and for the
Status tab safeguards built on it (docs/PLAN_UNIFIED.md 3.6): the audit tail and redaction report handlers, the
reflections note and the sources freshness in status_markdown, the rebuild handler's RedactionRequired /
LeakError messages, and scripts/delete_twin.ps1 (run on a tmp copy through powershell.exe, the one subprocess in
the suite because the script itself is under test).

AUDIT_PATH is read through the module attribute at call time, so the tests point it at a tmp file.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from twin import audit, clients, config, gpu, index, redact
from twin import profile as profile_mod
from twin.config import EXAMPLE_PROFILE_PATH, EXAMPLE_PROFILE_V2_PATH
from twin.gpu import MANAGER
from twin.pipelines import reflect
from twin.ui import state
from twin.ui import status as status_ui

ROOT = Path(__file__).resolve().parent.parent
DELETE_SCRIPT = ROOT / "scripts" / "delete_twin.ps1"
SECRET = "my exact home address is 12 Harbour Road and my salary is 41k"


@pytest.fixture
def path(monkeypatch, tmp_path: Path) -> Path:
    p = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_PATH", p)
    return p


def test_record_writes_one_json_line_with_sha_and_no_text(path: Path):
    entry = audit.record("ask", "interview", SECRET, ["Identity", "Decisions/D-01"], ["llama32_1b", "stheno_q4"],
                         True, extra={"intent": "about_me"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    on_disk = json.loads(lines[0])
    assert on_disk == entry
    assert set(entry) == {"ts", "date", "tab", "condition", "request_sha", "chunk_ids", "model_keys", "ok", "extra"}
    assert entry["request_sha"] == hashlib.sha256(SECRET.encode("utf-8")).hexdigest()
    assert entry["request_sha"] == audit.request_sha(SECRET)
    assert SECRET not in lines[0] and "Harbour" not in lines[0] and "41k" not in lines[0]
    assert entry["tab"] == "ask" and entry["condition"] == "interview"
    assert entry["chunk_ids"] == ["Identity", "Decisions/D-01"] and entry["model_keys"] == ["llama32_1b", "stheno_q4"]
    assert entry["ok"] is True and entry["extra"] == {"intent": "about_me"}
    today = date.today().isoformat()
    assert entry["date"] == today and entry["ts"].startswith(today) and "T" in entry["ts"]
    assert len(entry["ts"]) >= 19


def test_record_defaults_and_coercion(path: Path):
    e = audit.record("decide", "persona", None, None, None, 0)
    assert e["request_sha"] == hashlib.sha256(b"").hexdigest()
    assert e["chunk_ids"] == [] and e["model_keys"] == [] and e["ok"] is False and e["extra"] == {}
    e2 = audit.record("", None, "", ("a", 1), ("qwen3_8k",), "yes")
    assert e2["tab"] == "" and e2["condition"] == "" and e2["chunk_ids"] == ["a", "1"] and e2["ok"] is True
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_record_creates_parent_directory(monkeypatch, tmp_path: Path):
    p = tmp_path / "deep" / "er" / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_PATH", p)
    audit.record("see", "interview", "x", [], [], True)
    assert p.exists() and len(audit.tail()) == 1


def test_tail_order_and_limit(path: Path):
    assert audit.tail() == []                      # missing file
    for i in range(5):
        audit.record("ask", "interview", f"q{i}", [], [], True, extra={"i": i})
    rows = audit.tail(3)
    assert [r["extra"]["i"] for r in rows] == [2, 3, 4], "oldest first, newest last"
    assert [r["extra"]["i"] for r in audit.tail(50)] == [0, 1, 2, 3, 4]
    assert [r["extra"]["i"] for r in audit.tail()] == [0, 1, 2, 3, 4]
    assert audit.tail(0) == [] and audit.tail(-1) == []


def test_tail_skips_blank_and_malformed_lines(path: Path):
    audit.record("ask", "interview", "a", [], [], True, extra={"i": 0})
    with path.open("a", encoding="utf-8") as f:
        f.write("\n{not json\n[1, 2]\n")
    audit.record("ask", "interview", "b", [], [], True, extra={"i": 1})
    assert [r["extra"]["i"] for r in audit.tail()] == [0, 1]


def _line(day: date) -> str:
    return json.dumps({"ts": f"{day.isoformat()}T10:00:00+00:00", "date": day.isoformat(), "tab": "ask",
                       "condition": "interview", "request_sha": "0" * 64, "chunk_ids": [], "model_keys": [],
                       "ok": True, "extra": {}})


def test_counts_per_day_window_and_ordering(path: Path):
    today = date.today()
    yesterday = today - timedelta(days=1)
    old = today - timedelta(days=20)
    lines = [_line(old), _line(today), _line(yesterday), _line(today), "not json", json.dumps({"ts": "", "date": "??"})]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert audit.counts_per_day(14) == [(yesterday.isoformat(), 1), (today.isoformat(), 2)]
    assert audit.counts_per_day(1) == [(today.isoformat(), 2)]
    assert audit.counts_per_day(30) == [(old.isoformat(), 1), (yesterday.isoformat(), 1), (today.isoformat(), 2)]
    assert audit.counts_per_day() == audit.counts_per_day(14)
    # entries without a date fall back to the ts prefix
    path.write_text(json.dumps({"ts": f"{today.isoformat()}T09:00:00", "tab": "ask"}) + "\n", encoding="utf-8")
    assert audit.counts_per_day(14) == [(today.isoformat(), 1)]


def test_counts_per_day_empty(path: Path):
    assert audit.counts_per_day() == []


def test_clear_removes_file_and_is_idempotent(path: Path):
    audit.record("ask", "interview", "x", [], [], True)
    assert path.exists()
    audit.clear()
    assert not path.exists()
    audit.clear()                                  # no error when already gone
    assert audit.tail() == [] and audit.counts_per_day() == []


# ===========================================================================================================
# Status tab safeguards (twin/ui/status.py)
# ===========================================================================================================
FIXED_STATUS = {"ollama_ps": [], "ollama_tags": [], "lms_models": [], "lms_v1_ids": [], "gpu": "",
                "active_tab": None, "active_key": None, "tab_overrides": {}, "busy": False, "busy_key": None}


def _boom(*_a, **_k):
    raise AssertionError("a model call was attempted")


@pytest.fixture
def ui(monkeypatch, tmp_path: Path, path: Path):
    """GET-only fakes (any chat/embed/warm/stop fails the test), tmp audit/redaction/reflections paths, the
    Mara profile as state.PROFILE. Returns the tmp paths."""
    monkeypatch.setattr(MANAGER, "status", lambda: dict(FIXED_STATUS))
    monkeypatch.setattr(clients.ollama, "ps", lambda: [])
    monkeypatch.setattr(clients.ollama, "tags", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v0", lambda: [])
    monkeypatch.setattr(clients.lms, "models_v1", lambda: [])
    monkeypatch.setattr(clients.lms, "loaded", lambda: [])
    monkeypatch.setattr(gpu, "gpu_line", lambda: "")
    for obj, names in ((clients.ollama, ("chat", "embed", "warm", "stop")),
                       (clients.lms, ("chat", "embed", "unload_all"))):
        for n in names:
            monkeypatch.setattr(obj, n, _boom)
    monkeypatch.setattr(index, "build_all", _boom)
    monkeypatch.setattr(index, "rebuild_digest", _boom)
    # sources_state() must never read the real data/interview_transcript*.md files (the RedactionRequired test
    # overrides this with a raising fake)
    monkeypatch.setattr(index, "resolve_transcript_source", lambda no_redact=False, quiet=False: None)
    report = tmp_path / "redaction_report.json"
    reflections = tmp_path / "reflections.md"
    monkeypatch.setattr(redact, "REDACTION_REPORT_PATH", report)
    monkeypatch.setattr(reflect, "REFLECTIONS_PATH", reflections)
    monkeypatch.setattr(state, "PROFILE", profile_mod.load_profile(EXAMPLE_PROFILE_V2_PATH))
    monkeypatch.setattr(state, "PROFILE_ERROR", "")
    return SimpleNamespace(audit=path, report=report, reflections=reflections, tmp=tmp_path)


def test_audit_tail_handler_rows_and_counts(ui):
    rows, counts = status_ui.audit_tail_handler()
    assert rows == [] and "(no audit entries yet)" in counts
    audit.record("ask", "interview", SECRET, ["Identity", "Decisions/D-01"], ["llama32_1b", "stheno_q4"], True)
    audit.record("decide", "persona", "later question", [], ["qwen3_8k"], False)
    rows, counts = status_ui.audit_tail_handler()
    assert len(rows) == 2 and all(len(r) == len(status_ui.AUDIT_HEADERS) for r in rows)
    newest, oldest = rows
    assert newest[1:] == ["decide", "persona", audit.request_sha("later question")[:12], "0", "qwen3_8k", False]
    assert oldest[1:] == ["ask", "interview", audit.request_sha(SECRET)[:12], "2: Identity, Decisions/D-01",
                          "llama32_1b, stheno_q4", True]
    assert len(newest[0]) == 19 and newest[0][10] == " "                       # "YYYY-MM-DD HH:MM:SS"
    assert SECRET not in json.dumps(rows) and "Harbour" not in json.dumps(rows)
    assert f"{date.today().isoformat()}: 2" in counts and "2 requests" in counts
    # the tail is capped at AUDIT_ROWS entries, newest first
    for i in range(status_ui.AUDIT_ROWS + 5):
        audit.record("ask", "interview", f"q{i}", [], [], True)
    rows, _ = status_ui.audit_tail_handler()
    assert len(rows) == status_ui.AUDIT_ROWS
    assert rows[0][3] == audit.request_sha(f"q{status_ui.AUDIT_ROWS + 4}")[:12]


def test_redaction_report_handler(ui):
    md = status_ui.redaction_report_handler()
    assert "(no redaction report yet)" in md and "twin.redact" in md
    assert status_ui.redaction_report_summary() == "(no redaction report yet)"
    rep = {"source": "data\\interview_transcript.md", "source_sha": "192272d138840af3598ceff0", "output":
           "data\\interview_transcript.redacted.md", "turns": 60, "llm": True,
           "counts": {"email": 1, "profile-url": 0, "phone": 0, "id-number": 0, "address": 0, "names_heuristic": 0,
                      "names_llm": 1},
           "replacements": ["[email]", "[my older brother]", "[email]"], "redacted_at": "2026-09-14T02:08:25-07:00"}
    ui.report.write_text(json.dumps(rep), encoding="utf-8")
    md = status_ui.redaction_report_handler()
    assert "**Redaction report**" in md and "`data\\interview_transcript.redacted.md`" in md
    assert "turns: 60, llm pass: yes, source sha 192272d13884, at 2026-09-14T02:08:25-07:00" in md
    assert "counts: email 1, profile-url 0, phone 0, id-number 0, address 0, names_heuristic 0, names_llm 1" in md
    assert "tags used: `[email]` x2, `[my older brother]` x1" in md
    summary = status_ui.redaction_report_summary()
    assert summary.startswith("turns 60, llm pass yes; counts: email 1") and "tags: [email] x2, [my older brother] x1" in summary
    ui.report.write_text("{not json", encoding="utf-8")
    assert "(no redaction report yet)" in status_ui.redaction_report_handler()


def test_status_markdown_reflections_note_both_cases_and_missing(ui, monkeypatch):
    monkeypatch.setattr(index, "is_stale_sources", lambda key, prof=None, transcript_path=None: False)
    md = status_ui.status_markdown()
    assert "**Reflections:** no draft yet" in md
    ui.reflections.write_text("<!-- sha: 1f20244cbdb70b74 -->\n## Psychologist\nintroverted.\n\n## Demographer\n"
                              "urban freelancer.\n", encoding="utf-8")
    # Mara has # Expert reflections: the draft is not indexed
    md = status_ui.status_markdown()
    assert "profile already has # Expert reflections; the draft is not indexed" in md
    assert "draft 1f20244c, 2 lenses" in md
    # Ari (v1) has no such section: review and paste
    monkeypatch.setattr(state, "PROFILE", profile_mod.load_profile(EXAMPLE_PROFILE_PATH))
    md = status_ui.status_markdown()
    assert "reflections draft 1f20244c (2 lenses): review and paste into # Expert reflections" in md
    assert "**Profile:** Ari" in md and "sources (profile + transcript + reflections): fresh" in md


def test_status_markdown_sources_freshness(ui, monkeypatch):
    stale = {"gemma"}
    monkeypatch.setattr(index, "is_stale_sources", lambda key, prof=None, transcript_path=None: key in stale)
    assert "sources (profile + transcript + reflections): STALE (gemma)" in status_ui.status_markdown()
    stale.clear()
    assert "sources (profile + transcript + reflections): fresh" in status_ui.status_markdown()

    def redaction_required(*_a, **_k):
        raise index.RedactionRequired("data\\interview_transcript.md has no up-to-date redacted copy")

    monkeypatch.setattr(index, "resolve_transcript_source", redaction_required)
    md = status_ui.status_markdown()
    assert "sources (profile + transcript + reflections): redaction required (`python -m twin.redact" in md
    assert status_ui.sources_state().startswith("redaction required")
    monkeypatch.setattr(state, "PROFILE", None)
    assert status_ui.sources_state() == "unknown (no profile)"


def test_rebuild_handler_shows_redaction_required_and_leak_errors(ui, monkeypatch):
    calls: list[tuple] = []
    prof = state.PROFILE
    monkeypatch.setattr(profile_mod, "load_profile", lambda path=None: prof)
    monkeypatch.setattr(state, "load_app_profile", lambda: None)
    monkeypatch.setattr(index, "is_stale_sources", lambda key, p=None, transcript_path=None: False)

    def raise_redaction(*a, **k):
        calls.append((a, k))
        raise index.RedactionRequired("data\\interview_transcript.md changed: run python -m twin.redact first")

    monkeypatch.setattr(index, "build_all", raise_redaction)
    md, header = status_ui.rebuild_index_handler()
    assert calls == [((prof, True), {"with_reflections": True})]
    assert "**Last action:** Rebuild stopped (RedactionRequired): data\\interview_transcript.md changed" in md
    assert "Traceback" not in md and header.startswith("## Digital twin")
    assert "Redaction report: (no redaction report yet)" in md

    def raise_leak(*a, **k):
        raise index.LeakError("Q-03 is 0.71 contained in Interview/T-051")

    monkeypatch.setattr(index, "build_all", raise_leak)
    md, _ = status_ui.rebuild_index_handler()
    assert "Rebuild stopped (LeakError): Q-03 is 0.71 contained in Interview/T-051" in md

    # success: build_all(prof, True, with_reflections=True) and the refreshed redaction report in the note
    def ok_build(profile, with_digest, force=False, with_reflections=False, transcript_path=None, no_redact=False):
        ui.report.write_text(json.dumps({"turns": 3, "llm": False, "counts": {"email": 2}, "replacements": ["[email]"],
                                         "output": "x.redacted.md", "source_sha": "abcdef123456789", "redacted_at": "t"}),
                             encoding="utf-8")
        calls.append(("ok", with_digest, with_reflections))

    monkeypatch.setattr(index, "build_all", ok_build)
    md, _ = status_ui.rebuild_index_handler()
    assert calls[-1] == ("ok", True, True)
    assert "Rebuilt nomic, gemma and lms_nomic indexes, chunks.json, reflections draft and digest" in md
    assert "Redaction report: turns 3, llm pass no; counts: email 2; tags: [email] x1; output `x.redacted.md`; source sha abcdef123456" in md
    # any other exception still becomes the generic error line
    monkeypatch.setattr(index, "build_all", _boom)
    md, _ = status_ui.rebuild_index_handler()
    assert "**Error:** `AssertionError: a model call was attempted`" in md
    # the switch still short-circuits before any build
    monkeypatch.setenv("TWIN_NO_WARM", "1")
    md, _ = status_ui.rebuild_index_handler()
    assert "skipped: TWIN_NO_WARM=1" in md


def test_status_build_wires_audit_and_redaction_endpoints(ui):
    import gradio as gr
    from twin.ui import frame
    demo = frame.build_app()
    fns = {fn.api_name: fn for fn in demo.fns.values() if fn.api_visibility != "private"}
    assert "audit_tail" in fns and "redaction_report" in fns
    assert fns["audit_tail"].concurrency_id != "gpu" and fns["redaction_report"].concurrency_id != "gpu"
    assert fns["audit_tail"].inputs == [] and len(fns["audit_tail"].outputs) == 2
    assert isinstance(fns["audit_tail"].outputs[0], gr.Dataframe) and isinstance(fns["audit_tail"].outputs[1], gr.Markdown)
    assert fns["redaction_report"].inputs == [] and isinstance(fns["redaction_report"].outputs[0], gr.Markdown)
    parts = demo.twin_parts["status"]
    assert parts["audit"].headers == status_ui.AUDIT_HEADERS
    ids = {b.elem_id for b in demo.blocks.values() if getattr(b, "elem_id", None)}
    assert {"status-safeguards", "status-audit", "status-redaction"} <= ids
    # the phase-1 endpoints keep their signatures
    assert fns["rebuild_index"].inputs == [] and len(fns["rebuild_index"].outputs) == 2
    assert fns["status"].inputs == [] and len(fns["status"].outputs) == 2


# ===========================================================================================================
# scripts/delete_twin.ps1 (the script under test runs through powershell.exe on a tmp data dir)
# ===========================================================================================================
DELETE_TARGETS = [
    "twin_profile.md", "interview_transcript.md", "interview_transcript.redacted.md", "redaction_report.json",
    "index_nomic.npz", "index_gemma.npz", "index_lms_nomic.npz", "chunks.json", "digest.md", "reflections.md",
    "eval_results.json", "audit.jsonl", "telemetry.jsonl", "probes.json", "items/self_answers.json",
    "items/self_answers_retest.json", "items/twin_answers.json", "items/scores.json",
]
KEPT_FILES = [
    "twin_profile.example.md", "twin_profile.example.v2.md", "interview_transcript.example.md",
    "interview_transcript.example.redacted.md", "items/bank.json", "items/self_answers.example.json",
    "items/self_answers_retest.example.json", "unrelated_note.txt",
]


def _powershell() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell")


def _run_delete(data_dir: Path, confirm: bool) -> subprocess.CompletedProcess:
    args = [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(DELETE_SCRIPT), "-DataDir", str(data_dir)]
    if confirm:
        args.append("-Confirm")
    return subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=str(ROOT))


@pytest.mark.skipif(_powershell() is None, reason="powershell.exe not available")
def test_delete_twin_script_dry_run_then_confirm(tmp_path: Path):
    data_dir = tmp_path / "data_test"
    for rel in DELETE_TARGETS + KEPT_FILES:
        p = data_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    before = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if p.is_file())

    dry = _run_delete(data_dir, confirm=False)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "dry run" in dry.stdout and "would remove" in dry.stdout
    assert f"{len(DELETE_TARGETS)} file(s) would be removed" in dry.stdout
    assert "removed 18 files" not in dry.stdout and "  removing" not in dry.stdout
    assert "Onboarding" not in dry.stdout
    after_dry = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*") if p.is_file())
    assert after_dry == before, "the dry run must remove nothing"

    real = _run_delete(data_dir, confirm=True)
    assert real.returncode == 0, real.stdout + real.stderr
    assert f"removed {len(DELETE_TARGETS)} files" in real.stdout
    assert "the app now opens on Onboarding (no data\\twin_profile.md)" in real.stdout
    left = sorted(str(p.relative_to(data_dir)).replace("\\", "/") for p in data_dir.rglob("*") if p.is_file())
    assert left == sorted(KEPT_FILES)
    for rel in DELETE_TARGETS:
        assert not (data_dir / rel).exists(), rel
    # idempotent: a second confirmed run removes nothing and still exits 0
    again = _run_delete(data_dir, confirm=True)
    assert again.returncode == 0 and "removed 0 files" in again.stdout
    # a missing data dir is an error, not a silent no-op
    missing = _run_delete(tmp_path / "nope", confirm=True)
    assert missing.returncode == 1 and "data dir not found" in missing.stdout


@pytest.mark.skipif(_powershell() is None, reason="powershell.exe not available")
def test_delete_twin_script_never_names_example_files():
    text = DELETE_SCRIPT.read_text(encoding="utf-8")
    assert ".example" not in text.split("$targets")[1].split(")")[0]
    assert "bank.json" not in text.split("$targets")[1].split(")")[0]
    assert "param(" in text and "[switch]$Confirm" in text and '[string]$DataDir = "data"' in text
