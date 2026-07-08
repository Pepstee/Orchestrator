"""Auth failures fail FAST and loudly — never loop as transient (HANDOFF §4 hardening TODO).

The pre-fix behaviour: an expired `claude login` surfaced as a non-zero CLI exit, fell through
_fail_provider's default branch as RateLimited (transient), and the dispatcher requeued it all
night. These tests pin the fix at both layers of the single taxonomy (L1):

  - infra.llm._fail_provider: recognisable auth wording raises RuntimeError (hard), notifies
    once, and the message tells the operator exactly what to run;
  - infra.triage.classify: the emitted cause (and the CLI's own auth wordings) classify
    PERMANENT, so the failure ladder fails fast instead of burning the retry budget;
  - the pre-existing contracts are preserved: rate-limit wording and the opaque bare exit
    (the usage-cap signature) both stay TRANSIENT.
"""
from __future__ import annotations

import pytest

import infra.llm as llm
from infra.llm import RateLimited, _fail_provider
from infra.triage import ErrorClass, classify, is_transient_cause


@pytest.fixture()
def captured_notify(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(llm, "notify", lambda title, msg: calls.append((title, msg)))
    return calls


def test_401_raises_hard_and_notifies(captured_notify):
    with pytest.raises(RuntimeError) as exc:
        _fail_provider("claude", 1, 'API Error: 401 {"type":"authentication_error"}')
    assert not isinstance(exc.value, RateLimited)
    assert "claude login" in str(exc.value)
    assert len(captured_notify) == 1
    assert "auth" in captured_notify[0][1].lower()


def test_oauth_expired_raises_hard(captured_notify):
    with pytest.raises(RuntimeError) as exc:
        _fail_provider("claude", 1, "OAuth token has expired. Please run /login.")
    assert not isinstance(exc.value, RateLimited)


def test_auth_cause_classifies_permanent():
    # The exact shape _fail_provider emits, as it lands in AgentResult.cause via safe_main.
    cause = "claude auth error (exited 1): 401 unauthorized — run `claude login` to re-authenticate"
    cls, _why = classify(cause)
    assert cls is ErrorClass.PERMANENT
    assert not is_transient_cause(cause)


def test_cli_auth_wordings_classify_permanent():
    for cause in (
        "authentication_error: invalid bearer token",
        "OAuth token has expired",
        "please run /login",
        "not logged in",
    ):
        cls, _why = classify(cause)
        assert cls is ErrorClass.PERMANENT, cause


def test_rate_limit_still_transient(captured_notify):
    with pytest.raises(RateLimited):
        _fail_provider("claude", 1, "5-hour limit reached ∙ resets 5am")
    assert captured_notify == []  # limits back off silently; only auth notifies


def test_opaque_exit_still_transient(captured_notify):
    # A bare `claude exited 1` with no diagnostic output is the usage-cap signature —
    # it must remain transient (the guarantee that once stranded a whole night's work).
    with pytest.raises(RateLimited):
        _fail_provider("claude", 1, "")
    assert captured_notify == []
