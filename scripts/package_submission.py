"""Build a private reviewer ZIP from the working tree and read-only demo snapshots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
DATABASE = Path("runtime/phase3/screening.sqlite3")
METER = Path("runtime/prospect-pipeline-usage.sqlite3")
EXPORTS = ("orders.csv", "products.csv", "crm_accounts.csv", "public_agencies.csv")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".css", ".toml", ".json",
                   ".md", ".txt", ".woff2", ".svg", ".png", ".yml", ".yaml"}
ROOT_FILES = {".env.example", ".gitignore", "README.md", "pyproject.toml", "requirements.lock", "app.py"}
# These one-time historical checks require the author's original machine and baseline.
LOCAL_AUDITS = {"verify_screening_preservation.py", "verify_screening_http.py"}
PRIVATE_MARKERS = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|/Users/[^/\s]+/|/private/tmp/")
EMAIL = re.compile(r"[\w.%+-]+@([\w.-]+\.[a-z]{2,})", re.I)


def source_paths():
    paths = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT
    ).split(b"\0")
    for encoded in paths:
        if not encoded:
            continue
        path = Path(os.fsdecode(encoded))
        if path == Path("frontend/AGENTS.md") or any(
            part.startswith(".next") or part in {"__pycache__", ".pytest_cache", "node_modules", "coverage", "playwright-report", "test-results"}
            for part in path.parts[:-1]
        ):
            continue
        if path.parts[0] == "scripts" and path.name in LOCAL_AUDITS:
            continue
        if path.parts[0] == "docs":
            if path.as_posix() not in {"docs/prospect-pipeline-rehearsal.md", "docs/clearline-diagnostics-design-document.pdf"}:
                continue
        elif str(path) not in ROOT_FILES and (path.parts[0] not in
                {"src", "views", "tests", "frontend", ".streamlit", "scripts"}
                or path.suffix not in SOURCE_SUFFIXES):
            continue
        source = ROOT / path
        if not source.exists():  # A locally deleted tracked file must stay deleted.
            continue
        if source.is_symlink() or source.resolve() != source:
            raise ValueError(f"Review linked source before packaging: {path}")
        yield path


def snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst, pages=2048)


def prepare_database(path):
    with closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA foreign_keys=ON")
        # Leave the business decisions, aggregate usage, drafts and source citations in place.
        con.execute("""DELETE FROM events WHERE kind IN
            ('model_output','evidence_retrieved','rate_headers','validated_portfolio_import','demo_baseline_prepared')""")
        con.execute("DELETE FROM worker_state")
        # Historical delivery remains visible. A reviewer must supply their own authorization
        # before a subsequent internal request; never authorize a redacted recipient.
        for iid, version, email in con.execute(
                "SELECT inquiry_id, version, recipient FROM internal_draft_versions").fetchall():
            if email.endswith("@example.invalid"):
                continue
            if not con.execute("SELECT 1 FROM internal_deliveries WHERE inquiry_id=? AND version=?",
                               (iid, version)).fetchone():
                raise ValueError("Review a private unsent internal draft before sharing a new snapshot.")
            con.execute("""UPDATE internal_draft_versions SET recipient=?, verification_evidence=?
                           WHERE inquiry_id=? AND version=?""",
                        ("redacted@example.invalid", "Private recipient withheld in the reviewer copy.", iid, version))
        con.execute("DELETE FROM internal_recipients WHERE recipient NOT LIKE '%@example.invalid'")
        con.commit()
        con.execute("VACUUM")  # Expel discarded bytes from the copy, including unused SQLite pages.
        if con.execute("PRAGMA foreign_key_check").fetchone() or con.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Reviewer snapshot failed its SQLite integrity checks.")


def verify_demo_text(path):
    # Inspect logical records as text, including JSON inside SQLite; binary ZIP scanning misses them.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as con:
        for statement in con.iterdump():
            if PRIVATE_MARKERS.search(statement) or any(
                domain.lower() not in {"example.invalid", "example.org", "example.com", "example.net"}
                for domain in EMAIL.findall(statement)
            ):
                raise ValueError(f"Private path, contact or credential-like content in {path.name}; review before sharing.")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".zip" or output.is_relative_to(ROOT):
        parser.error("Choose a new ZIP path outside the checkout.")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.exists():
        parser.error("Choose a new filename to preserve the previous candidate.")
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        stage = Path(folder) / "package"
        for path in source_paths():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        (stage / "data").mkdir()
        for name in EXPORTS:
            shutil.copyfile(args.data_dir / name, stage / "data" / name)
        snapshot(ROOT / DATABASE, stage / DATABASE)
        prepare_database(stage / DATABASE)
        verify_demo_text(stage / DATABASE)
        snapshot(ROOT / METER, stage / METER)
        verify_demo_text(stage / METER)
        files = sorted(p for p in stage.rglob("*") if p.is_file())
        manifest = {"base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    "files_sha256": {str(p.relative_to(stage)): sha256(p) for p in files}}
        listing = stage / "SUBMISSION-MANIFEST.json"
        listing.write_text(json.dumps(manifest, indent=2) + "\n")
        archive = Path(folder) / "candidate.zip"
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as writer:
            for file in [*files, listing]:
                writer.write(file, file.relative_to(stage))
        with zipfile.ZipFile(archive) as reader:
            if reader.testzip():
                raise ValueError("ZIP integrity check failed.")
        os.link(archive, output)  # Publish locally only after verification; never replace an existing file.
    print(output)


if __name__ == "__main__":
    main()
