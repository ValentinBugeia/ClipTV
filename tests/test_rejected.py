"""« À publier » = dernière recherche ; « Rejetés » limité aux 10 plus récents."""

import time

from clipbot.config import Config
from clipbot.state import AUTO_REJECT, State


def make_state(tmp_path):
    cfg = Config()
    cfg.data_dir = tmp_path
    return State(cfg.db_path)


def test_new_search_archives_pending(tmp_path):
    state = make_state(tmp_path)
    state.record("a", "nico", "rendered")
    state.record("b", "nico", "published")
    assert state.archive_pending() == 1
    assert state.get("a")["status"] == "rejected" and state.get("a")["error"] == AUTO_REJECT
    assert state.get("b")["status"] == "published"


def test_trim_rejected_keeps_ten_newest(tmp_path):
    state = make_state(tmp_path)
    downloads = tmp_path / "dl"
    downloads.mkdir()
    for i in range(13):
        out = tmp_path / f"c{i}.mp4"
        out.write_bytes(b"x")
        out.with_suffix(".ass").write_text("")
        (downloads / f"c{i}.mp4").write_bytes(b"x")
        state.record(f"c{i}", "nico", "rejected", output_path=str(out))
        state.conn.execute("UPDATE clips SET updated_at=? WHERE clip_id=?",
                           (int(time.time()) - 100 + i, f"c{i}"))
    state.conn.commit()
    assert state.trim_rejected(downloads) == 3
    assert len(state.list("rejected")) == 10
    for i in range(3):  # les 3 plus anciens : fichiers supprimés, jamais reproposés
        assert state.get(f"c{i}")["status"] == "purged" and state.is_done(f"c{i}")
        assert not (tmp_path / f"c{i}.mp4").exists()
        assert not (tmp_path / f"c{i}.ass").exists()
        assert not (downloads / f"c{i}.mp4").exists()
    assert (tmp_path / "c3.mp4").exists() and (downloads / "c12.mp4").exists()
    assert state.trim_rejected(downloads) == 0
