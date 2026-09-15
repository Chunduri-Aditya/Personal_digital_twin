"""PLAN_FINISH P8: build the three v2 zips and check them (run as a file, never via `python -`).

Usage (project root):
  python scripts/dev/finish/build_zips.py --pytest-count N [--force] [--check-only] [--skip-pytest]
         [--report scripts/dev/finish/zips_report.json]

Zips (the 2026-09-14 v1 zips are kept):
- C:/Users/Adity/Personal_digital_twin_no_models_v2.zip: top folder Personal_digital_twin/; no files under models/
  but the empty models/, models/ollama/ and models/lmstudio/ folders; no __pycache__ or .pytest_cache; includes
  docs/REPLICATE_ON_MAC.md, .claude/skills and scripts/dev/workflows.
- C:/Users/Adity/Personal_digital_twin_claude_memory_v2.zip: memory/ (MEMORY.md and the notes).
- C:/Users/Adity/Personal_digital_twin_claude_env_v2.zip: claude_env/user-config/settings.json, claude_env/skills
  (from .claude/skills) and claude_env/skills-not-used (from docs/skills-not-used).
Never .credentials.json or .claude.json.

Checks: testzip() is None; the file count equals the files selected on disk; no secret files and no real sk-ant- keys
in any member; the project zip extracted to %TEMP% gives the same pytest count, then the copy is deleted.
Exit 0 when every check passes.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
HOME = Path(os.path.expanduser("~"))
CLAUDE_HOME = HOME / ".claude"
MEMORY = CLAUDE_HOME / "projects" / "C--Users-Adity-Personal-digital-twin" / "memory"
OUT = PROJECT.parent
ZIP_PROJECT = OUT / "Personal_digital_twin_no_models_v2.zip"
ZIP_MEMORY = OUT / "Personal_digital_twin_claude_memory_v2.zip"
ZIP_ENV = OUT / "Personal_digital_twin_claude_env_v2.zip"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv"}
SECRET_NAMES = {".credentials.json", ".claude.json"}
KEY_RE = re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}")
# Key-shaped strings containing these words are test fixtures (e.g. tests/test_clients.py's dummy "sk-ant-test..."),
# reported separately as placeholder_keys; any other match fails the check.
PLACEHOLDER_KEY_WORDS = (b"test", b"fake", b"example", b"dummy", b"xxxx", b"placeholder", b"sample")
REQUIRED_IN_PROJECT = ["docs/REPLICATE_ON_MAC.md", ".claude/skills/frontend-design/SKILL.md",
                       ".claude/skills/redesign-existing-projects/SKILL.md",
                       ".claude/skills/web-design-guidelines/SKILL.md", "scripts/dev/workflows/finish-p7-mac-guide.js"]


def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def project_entries():
    """(files: [(disk path, arcname)], dirs: [arcname]) for the project zip."""
    files, dirs = [], ["Personal_digital_twin/models/", "Personal_digital_twin/models/ollama/",
                       "Personal_digital_twin/models/lmstudio/"]
    for d, subdirs, names in os.walk(PROJECT):
        rel_dir = Path(d).relative_to(PROJECT)
        parts = rel_dir.parts
        subdirs[:] = sorted(s for s in subdirs if s not in SKIP_DIRS)
        if parts and parts[0] == "models":
            subdirs[:] = []  # never descend into the model stores
            continue
        if parts == () and "models" in subdirs:
            pass  # models/ itself is added as empty folders above
        for n in sorted(names):
            if n in SECRET_NAMES or n.endswith(".pyc"):
                continue
            p = Path(d) / n
            arc = "Personal_digital_twin/" + (rel_dir / n).as_posix()
            files.append((p, arc))
    return files, dirs


def tree_entries(src: Path, prefix: str):
    files = []
    for d, subdirs, names in os.walk(src):
        subdirs[:] = sorted(s for s in subdirs if s not in SKIP_DIRS)
        for n in sorted(names):
            if n in SECRET_NAMES:
                continue
            p = Path(d) / n
            files.append((p, prefix + p.relative_to(src).as_posix()))
    return files


def env_entries():
    files = [(CLAUDE_HOME / "settings.json", "claude_env/user-config/settings.json")]
    files += tree_entries(PROJECT / ".claude" / "skills", "claude_env/skills/")
    files += tree_entries(PROJECT / "docs" / "skills-not-used", "claude_env/skills-not-used/")
    return files


def write_zip(path: Path, files, dirs, force: bool):
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite {path} (pass --force after looking at it)")
    tmp = path.with_suffix(".zip.tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for arc in dirs:
            z.writestr(zipfile.ZipInfo(arc), b"")
        for p, arc in files:
            if arc.endswith(".sh"):
                # Shell scripts (./start.sh) keep an executable Unix mode, so unzip on the Mac can run them directly.
                info = zipfile.ZipInfo.from_file(p, arc)
                info.create_system = 3
                info.external_attr = 0o100755 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(p, "rb") as fh:
                    z.writestr(info, fh.read())
            else:
                z.write(p, arc)
    os.replace(tmp, path)


def check_zip(path: Path, expected_files: int):
    out = {"path": str(path), "bytes": path.stat().st_size}
    with zipfile.ZipFile(path) as z:
        out["testzip"] = z.testzip()
        infos = z.infolist()
        members = [i for i in infos if not i.is_dir()]
        out["files"] = len(members)
        out["dirs"] = [i.filename for i in infos if i.is_dir()]
        out["count_matches_disk"] = len(members) == expected_files
        out["secret_files"] = [i.filename for i in members if Path(i.filename).name in SECRET_NAMES]
        hits = []
        placeholders = []
        for i in members:
            if i.file_size > 50 * 1024 * 1024:
                continue
            data = z.read(i)
            for m in KEY_RE.finditer(data):
                entry = {"member": i.filename, "masked": m.group(0)[:10].decode() + "..."}
                if any(w in m.group(0).lower() for w in PLACEHOLDER_KEY_WORDS):
                    placeholders.append(entry)
                else:
                    hits.append(entry)
        out["key_hits"] = hits
        out["placeholder_keys"] = placeholders
        names = {i.filename for i in members}
        out["top_folders"] = sorted({i.filename.split("/")[0] for i in infos})
        out["_names"] = names
    out["ok"] = out["testzip"] is None and out["count_matches_disk"] and not out["secret_files"] and not out["key_hits"]
    return out


def pytest_in_copy(zip_path: Path, expected: int):
    tmp = Path(tempfile.mkdtemp(prefix="twin_zip_check_"))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        root = tmp / "Personal_digital_twin"
        env = dict(os.environ, TWIN_NO_WARM="1", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=root, env=env,
                           capture_output=True, text=True, timeout=900)
        tail = [line for line in (r.stdout or "").splitlines() if line.strip()][-1:] or [""]
        m = re.search(r"(\d+) passed", tail[0])
        f = re.search(r"(\d+) failed", tail[0])
        passed = int(m.group(1)) if m else None
        return {"extracted_to": str(tmp), "exit": r.returncode, "summary": tail[0], "passed": passed,
                "failed": int(f.group(1)) if f else 0, "matches": passed == expected and r.returncode == 0}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    force = "--force" in sys.argv
    check_only = "--check-only" in sys.argv
    expected_tests = int(_arg("--pytest-count", "0"))
    report_path = PROJECT / _arg("--report", "scripts/dev/finish/zips_report.json")
    report = {"built_at": dt.datetime.now().astimezone().isoformat(), "zips": {}}

    pfiles, pdirs = project_entries()
    mfiles = tree_entries(MEMORY, "memory/")
    efiles = env_entries()
    missing = [r for r in REQUIRED_IN_PROJECT if not (PROJECT / r).exists()]
    report["required_missing_on_disk"] = missing
    if "--list-only" in sys.argv:
        # Preview what each zip would hold (counts, sizes, largest files); writes nothing.
        for label, path, files in (("project", ZIP_PROJECT, pfiles), ("memory", ZIP_MEMORY, mfiles), ("env", ZIP_ENV, efiles)):
            sizes = sorted(((p.stat().st_size, arc) for p, arc in files), reverse=True)
            total = sum(s for s, _ in sizes)
            print(f"{label}: {len(files)} files, {total / 1e6:.1f} MB uncompressed, zip exists={path.exists()} -> {path}")
            for s, arc in sizes[:5]:
                print(f"   {s / 1e6:8.1f} MB  {arc}")
        print("empty folders in the project zip:", pdirs)
        print("required files missing on disk:", missing)
        return 0
    for label, path, files, dirs in (("project", ZIP_PROJECT, pfiles, pdirs), ("memory", ZIP_MEMORY, mfiles, []),
                                     ("env", ZIP_ENV, efiles, [])):
        if not check_only:
            write_zip(path, files, dirs, force)
            print(f"built {path} ({len(files)} files)")
        res = check_zip(path, len(files))
        names = res.pop("_names")
        if label == "project":
            res["required_present"] = {r: ("Personal_digital_twin/" + r) in names for r in REQUIRED_IN_PROJECT}
            res["model_files"] = sorted(n for n in names if n.startswith("Personal_digital_twin/models/"))[:5]
            res["pycache_members"] = sum(1 for n in names if "__pycache__" in n or ".pytest_cache" in n)
            res["ok"] = res["ok"] and all(res["required_present"].values()) and not res["model_files"] \
                and res["pycache_members"] == 0 and "Personal_digital_twin/models/ollama/" in res["dirs"] \
                and "Personal_digital_twin/models/lmstudio/" in res["dirs"] and res["top_folders"] == ["Personal_digital_twin"]
        elif label == "memory":
            res["ok"] = res["ok"] and res["top_folders"] == ["memory"] and "memory/MEMORY.md" in names
        else:
            res["ok"] = res["ok"] and "claude_env/user-config/settings.json" in names and res["top_folders"] == ["claude_env"]
        report["zips"][label] = res
        print(f"{label}: {res['files']} files, {res['bytes']:,} bytes, testzip={res['testzip']}, "
              f"count_matches_disk={res['count_matches_disk']}, secrets={len(res['secret_files'])}, "
              f"key_hits={len(res['key_hits'])}, placeholder_keys={len(res['placeholder_keys'])}, ok={res['ok']}")

    if "--skip-pytest" not in sys.argv:
        pt = pytest_in_copy(ZIP_PROJECT, expected_tests)
        report["pytest_extracted"] = pt
        print(f"pytest in extracted copy: {pt['summary']} (expected {expected_tests}) matches={pt['matches']}; "
              f"copy deleted: {not Path(pt['extracted_to']).exists()}")
    ok = all(z["ok"] for z in report["zips"].values()) and (report.get("pytest_extracted", {"matches": True})["matches"])
    report["ok"] = ok
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    print("zips:", "PASS" if ok else "FAIL", "->", report_path.relative_to(PROJECT))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
