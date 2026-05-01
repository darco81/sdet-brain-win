"""Tests for the chat REPL parser + helpers (T5-01)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdet_brain.cli import chat_repl as repl


@pytest.fixture
def state() -> repl.ReplState:
    return repl.ReplState()


@pytest.fixture(autouse=True)
def _redirect_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point ~/.sdet-brain at a temp dir so save/load doesn't pollute home."""
    monkeypatch.setattr(repl, "HOME_DIR", tmp_path)
    monkeypatch.setattr(repl, "CONVERSATIONS_DIR", tmp_path / "conversations")


def test_parse_command_blank_line_is_noop(state: repl.ReplState) -> None:
    res = repl.parse_command("   ", state)
    assert res.send_to_llm is None
    assert res.output == ""


def test_parse_command_plain_text_passes_through(state: repl.ReplState) -> None:
    res = repl.parse_command("co planujemy?", state)
    assert res.send_to_llm == "co planujemy?"


def test_parse_command_help_returns_help_text(state: repl.ReplState) -> None:
    res = repl.parse_command("/help", state)
    assert "/save" in res.output
    assert "/quit" in res.output


def test_parse_command_clear_resets_state(state: repl.ReplState) -> None:
    state.messages.append({"role": "user", "content": "x"})
    state.last_sources.append({"n": 1})
    res = repl.parse_command("/clear", state)
    assert state.messages == []
    assert state.last_sources == []
    assert "cleared" in res.output


def test_parse_command_sources_when_empty(state: repl.ReplState) -> None:
    res = repl.parse_command("/sources", state)
    assert "no sources" in res.output


def test_parse_command_sources_renders_structured(state: repl.ReplState) -> None:
    state.last_sources = [
        {"n": 1, "source_path": "/a/b.md", "score": 0.521, "snippet": "hello"},
        {"n": 2, "source_path": "/c/d.md", "score": 0.4, "snippet": ""},
    ]
    res = repl.parse_command("/sources", state)
    assert "[1] /a/b.md" in res.output
    assert "score=0.521" in res.output
    assert "hello" in res.output
    assert "[2] /c/d.md" in res.output


def test_parse_command_save_requires_name(state: repl.ReplState) -> None:
    res = repl.parse_command("/save", state)
    assert "usage" in res.output


def test_parse_command_save_then_load_round_trip(state: repl.ReplState) -> None:
    state.messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    state.last_sources = [{"n": 1, "source_path": "/x.md"}]

    save_res = repl.parse_command("/save my-chat", state)
    assert "saved" in save_res.output

    state.clear()
    assert state.messages == []

    load_res = repl.parse_command("/load my-chat", state)
    assert "loaded" in load_res.output
    assert state.messages[0]["content"] == "hello"
    assert state.last_sources[0]["source_path"] == "/x.md"


def test_parse_command_load_missing_file(state: repl.ReplState) -> None:
    res = repl.parse_command("/load nope", state)
    assert "no saved" in res.output


def test_parse_command_quit_signals_exit(state: repl.ReplState) -> None:
    res = repl.parse_command("/quit", state)
    assert res.should_exit is True


def test_parse_command_unknown_slash(state: repl.ReplState) -> None:
    res = repl.parse_command("/whatever", state)
    assert "unknown command" in res.output


def test_format_sources_omits_score_when_missing() -> None:
    out = repl._format_sources([{"n": 1, "source_path": "/x.md"}])
    assert "[1] /x.md" in out
    assert "score=" not in out
