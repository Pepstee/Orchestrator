"""Behavioural: notifications are best-effort and never crash the caller. Telegram (DG-10b,
the first whitelisted outbound) is config-gated, operator-chat-only, and can never raise."""
from __future__ import annotations

import json

from infra.notify import _send_telegram, _telegram_config, notify


def test_notify_never_raises_and_returns_bool():
    result = notify("Orchestrator", 'a project "demo" is ready')   # quotes must not break it
    assert isinstance(result, bool)


def test_no_or_bad_config_means_no_telegram(tmp_path):
    assert _telegram_config(tmp_path / "telegram.json") is None
    (tmp_path / "telegram.json").write_text("{not json", encoding="utf-8")
    assert _telegram_config(tmp_path / "telegram.json") is None
    (tmp_path / "telegram.json").write_text(json.dumps({"token": "t"}), encoding="utf-8")
    assert _telegram_config(tmp_path / "telegram.json") is None, "chat_id required"


def test_valid_config_loads(tmp_path):
    (tmp_path / "telegram.json").write_text(
        json.dumps({"token": "123:abc", "chat_id": "42"}), encoding="utf-8")
    assert _telegram_config(tmp_path / "telegram.json") == {"token": "123:abc", "chat_id": "42"}


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_telegram_posts_to_operator_chat():
    seen = {}

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode()
        return _Resp()

    ok = _send_telegram("Orchestrator: certified!", {"token": "123:abc", "chat_id": "42"},
                        opener=opener)
    assert ok
    assert "bot123:abc/sendMessage" in seen["url"]
    assert "chat_id=42" in seen["body"] and "certified" in seen["body"]


def test_send_telegram_never_raises():
    def boom(req, timeout):
        raise OSError("network down")

    assert _send_telegram("boom", {"token": "x", "chat_id": "1"}, opener=boom) is False


def test_plainify_rewrites_for_the_phone():
    from infra.notify import _plainify

    def translator(prompt):
        assert "BG-5: guardian unhealthy" in prompt, "original message reaches the translator"
        return "Your robot manager stopped answering twice in a row - the system flagged it."

    out = _plainify("Overseer", "BG-5: guardian unhealthy — 2 pulse(s) outstanding",
                    translator=translator)
    assert out.startswith("Your robot manager")


def test_plainify_falls_back_on_any_failure():
    from infra.notify import _plainify

    def boom(prompt):
        raise RuntimeError("translator down")

    assert _plainify("T", "technical detail", translator=boom) == "T: technical detail"

    def empty(prompt):
        return "   "

    assert _plainify("T", "technical detail", translator=empty) == "T: technical detail"


def test_plain_mode_is_switchable(monkeypatch):
    from infra.notify import _plain_enabled
    monkeypatch.delenv("AGENTIC_NOTIFY_PLAIN", raising=False)
    assert _plain_enabled({}) is True, "plain speech is the default"
    assert _plain_enabled({"plain": False}) is False
    monkeypatch.setenv("AGENTIC_NOTIFY_PLAIN", "0")
    assert _plain_enabled({}) is False


def test_notify_is_mute_under_pytest(monkeypatch):
    # PYTEST_CURRENT_TEST is set right now, by definition — notify must refuse to ring.
    import infra.notify as n
    calls = []
    monkeypatch.setattr(n, "_desktop", lambda t, m: calls.append("desktop") or True)
    monkeypatch.setattr(n, "_telegram_config", lambda: {"token": "x", "chat_id": "1"})
    assert n.notify("Orchestrator", "demo is DONE") is False
    assert not calls, "no channel may fire from inside a test run (the 11 Jun phone leak)"
