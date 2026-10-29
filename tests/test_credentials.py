"""read_credentials: env wins, prompt fallback, repr redacts."""

from __future__ import annotations

import pytest

from tidemark.core.credentials import Credentials, read_credentials


def test_env_vars_used_when_set(clear_credential_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIDEMARK_USER", "alice")
    monkeypatch.setenv("TIDEMARK_PASS", "s3cret")
    c = read_credentials()
    assert c.username == "alice"
    assert c.password == "s3cret"


def test_prompt_fallback(clear_credential_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "bob")
    monkeypatch.setattr("tidemark.core.credentials.getpass.getpass", lambda _prompt: "hunter2")
    c = read_credentials(prompt_device="core")
    assert c.username == "bob"
    assert c.password == "hunter2"


def test_repr_does_not_leak_password() -> None:
    r = repr(Credentials("alice", "s3cret"))
    assert "s3cret" not in r
    assert "alice" not in r
