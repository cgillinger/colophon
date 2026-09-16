"""A fresh database must survive several workers booting at once.

Gunicorn starts its workers simultaneously, and every one of them runs the
schema block in create_app() against the same SQLite file. Each step there is
check-then-act — create_all()'s checkfirst, ensure_*'s "does this column
exist" — so on an empty database two workers could both conclude a table was
missing, and the loser died with "table library_items already exists".
Gunicorn reports that as "Worker failed to boot" and gives up, so the first
start against a new data dir failed with nothing but a traceback to go on.

The pin is test_schema_block_waits_for_another_process: it holds the lock and
proves create_app() waits for it. Racing real processes (the test below it)
reproduces the original crash only sometimes, which is precisely why the
serialisation has to be asserted directly rather than sampled.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_BOOT = """
import sys, time
sys.path.insert(0, {repo!r})
time.sleep(max(0.0, float(sys.argv[1]) - time.time()))
from app import create_app
create_app()
"""


def _env(data_dir, library_dir):
    return dict(
        os.environ,
        COLOPHON_DATA_DIR=str(data_dir),
        COLOPHON_LIBRARY_DIR=str(library_dir),
        COLOPHON_SECRET_KEY="test-schema-lock",
        COLOPHON_LOG_LEVEL="ERROR",
    )


def _boot(data_dir, library_dir, start_at):
    return subprocess.Popen(
        [sys.executable, "-c", _BOOT.format(repo=str(REPO_ROOT)), str(start_at)],
        env=_env(data_dir, library_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_schema_block_waits_for_another_process(tmp_path):
    """create_app() must not touch the schema while another process holds the lock."""
    import fcntl

    data_dir = tmp_path / "data"
    library_dir = tmp_path / "books"
    data_dir.mkdir()
    library_dir.mkdir()

    held = open(data_dir / ".schema.lock", "w")
    fcntl.flock(held.fileno(), fcntl.LOCK_EX)

    proc = _boot(data_dir, library_dir, time.time())
    try:
        time.sleep(6)
        assert proc.poll() is None, (
            "create_app() ran the schema block while another process held the "
            "lock — nothing serialises the migrations, so simultaneous workers "
            "can still collide on a fresh database.\n"
            + (proc.stderr.read() or "")[-800:]
        )
    finally:
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)
        held.close()

    code = proc.wait(timeout=120)
    assert code == 0, (proc.stderr.read() or "")[-800:]
    assert (data_dir / "colophon.db").exists()


def test_concurrent_boots_on_a_fresh_database_all_succeed(tmp_path):
    """End-to-end: eight workers, one empty data dir, no failed boots."""
    data_dir = tmp_path / "data"
    library_dir = tmp_path / "books"
    data_dir.mkdir()
    library_dir.mkdir()

    start_at = time.time() + 2.0
    procs = [_boot(data_dir, library_dir, start_at) for _ in range(8)]
    results = [(p.wait(timeout=120), p.stderr.read()) for p in procs]

    failed = [err for code, err in results if code != 0]
    assert not failed, (
        f"{len(failed)} of {len(procs)} boots failed against an empty data dir:\n"
        + "\n".join(err.strip()[-800:] for err in failed)
    )
    assert (data_dir / "colophon.db").exists()


def test_schema_lock_releases_and_is_reusable(tmp_path):
    """The lock must not be held past the block, or the next boot hangs."""
    from app import _schema_lock

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    for _ in range(3):
        with _schema_lock(str(data_dir)):
            pass

    assert (data_dir / ".schema.lock").exists()


def test_schema_lock_survives_an_unwritable_data_dir(tmp_path):
    """A lock we cannot take is not a reason to refuse to start."""
    from app import _schema_lock

    unwritable = tmp_path / "nope"
    unwritable.mkdir()
    unwritable.chmod(0o500)
    try:
        entered = False
        with _schema_lock(str(unwritable)):
            entered = True
        assert entered
    finally:
        unwritable.chmod(0o700)
