import os

from clipbot.config import Config
from clipbot.localkeys import (apply_keys, check_password, hash_password, load_stored_keys,
                               save_keys)
from clipbot.state import State


def test_password_hash():
    h = hash_password("motdepasse")
    assert check_password(h, "motdepasse") and not check_password(h, "autre")
    assert not check_password("garbage", "x")


def test_keys_saved_and_applied(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config()
    cfg.data_dir = tmp_path
    state = State(cfg.db_path)
    changed = save_keys(state, cfg, {"TWITCH_CLIENT_ID": " abc ", "ANTHROPIC_API_KEY": "sk-1",
                                     "TWITCH_CLIENT_SECRET": ""})
    assert cfg.twitch_client_id == "abc" and os.environ["ANTHROPIC_API_KEY"] == "sk-1"
    assert len(changed) == 2
    # un champ vide garde la valeur existante
    save_keys(state, cfg, {"TWITCH_CLIENT_ID": ""})
    assert state.get_settings()["keys"]["TWITCH_CLIENT_ID"] == "abc"

    fresh = Config()
    fresh.data_dir = tmp_path
    load_stored_keys(fresh)  # nouvelle session : les clés reviennent
    assert fresh.twitch_client_id == "abc"
    apply_keys(fresh, state)
