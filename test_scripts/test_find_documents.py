"""find_on_pc for documents: newest first, separator-blind names, no stale files.

Runs against a temp folder and a temp index — never the real machine index.
"""

import os
import time

import pytest

from core import machine_index as mi


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(mi, "DB_PATH", str(tmp_path / "index.db"))
    monkeypatch.setattr(mi, "all_user_folders", lambda: {"documents": str(docs)})
    monkeypatch.setattr(mi, "_data_drives", lambda: [])

    def make(name: str, age_days: float):
        p = docs / name
        p.write_text("x")
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
        return str(p)
    return make


def run(what, kind=None):
    return mi.find_on_pc({"what": what, **({"kind": kind} if kind else {})}, None)


def test_newest_first_with_dates(sandbox):
    old = sandbox("resume.pdf", 400)
    new = sandbox("resume 2026.pdf", 30)
    out = run("resume", "document")
    assert out.index(new) < out.index(old)
    assert "newest first" in out
    assert "don't ask him to confirm" not in out


def test_separator_blind_match(sandbox):
    cv = sandbox("Ihan Full Stack Developer.pdf", 60)
    assert cv in run("fullstack developer", "document")
    cv2 = sandbox("FullStack_Engineer_CV.docx", 10)
    assert cv2 in run("full stack", "document")


def test_more_words_beat_newer_partial_match(sandbox):
    real = sandbox("FREYA CONSTITUTION v1.2.pdf", 50)
    sandbox("freya_memory.db", 0)          # newest, one word, not a document
    sandbox("report_v2.txt", 1)            # newer, one word
    out = run("Freya Constitution.v2", "document")
    assert out.splitlines()[1].endswith(real)
    assert "freya_memory.db" not in out


def test_indexed_but_deleted_file_is_dropped(sandbox):
    gone = sandbox("notes.pdf", 5)
    run("notes", "document")          # live search indexes it
    os.remove(gone)
    assert gone not in run("notes", "document")


def test_apps_keep_single_answer(sandbox):
    conn = mi._db()
    mi._add(conn, "app", "Blender", r"C:\Program Files\Blender\blender.exe", "shortcut")
    conn.commit()
    conn.close()
    assert "That's the one" in run("blender")
