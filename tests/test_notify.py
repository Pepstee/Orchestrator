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

    ok = _send_telegram("Orchestrator", "certified!", {"token": "123:abc", "chat_id": "42"},
                        opener=opener)
    assert ok
    assert "bot123:abc/sendMessage" in seen["url"]
    assert "chat_id=42" in seen["body"] and "certified" in seen["body"]


def test_send_telegram_never_raises():
    def boom(req, timeout):
        raise OSError("network down")

    assert _send_telegram("t", "m", {"token": "x", "chat_id": "1"}, opener=boom) is False
