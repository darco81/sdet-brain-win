"""Tests for the saved-query templates layer (T5-03)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sdet_brain.cli.templates import (
    QueryTemplate,
    TemplateError,
    discover_templates,
    find_template,
    format_output,
    render_query,
)
from sdet_brain.cli.templates_cli import _parse_kv


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "voice-check.yaml",
        """\
        name: voice-check
        description: voice samples
        tool: search_voice_samples
        args:
          limit: 10
        query_template: "{{topic}} opener tone"
        default_args:
          topic: self-deprecating
        output_format: markdown
        """,
    )
    _write(
        tmp_path,
        "decision-history.yaml",
        """\
        name: decision-history
        description: decisions
        tool: search_decisions
        args:
          limit: 10
        query_template: "{{topic}} decision rationale"
        default_args:
          topic: deploy strategy
        """,
    )
    return tmp_path


# --- discovery + load ---------------------------------------------------


def test_discover_lists_yaml_templates(templates_dir: Path) -> None:
    locs = discover_templates(extra_dirs=[templates_dir])
    names = sorted(loc.template.name for loc in locs)
    assert "voice-check" in names
    assert "decision-history" in names


def test_discover_skips_malformed_files(templates_dir: Path) -> None:
    (templates_dir / "broken.yaml").write_text(
        "tool: search\n# missing required fields\n", encoding="utf-8"
    )
    locs = discover_templates(extra_dirs=[templates_dir])
    # broken file dropped - no template named "broken" surfaces
    assert all(loc.template.name != "broken" for loc in locs)
    # the valid ones we just wrote are still present
    names = {loc.template.name for loc in locs}
    assert {"voice-check", "decision-history"}.issubset(names)


def test_find_template_returns_location(templates_dir: Path) -> None:
    loc = find_template("voice-check", extra_dirs=[templates_dir])
    assert loc.template.tool == "search_voice_samples"
    assert loc.path.name == "voice-check.yaml"


def test_find_template_raises_for_unknown(templates_dir: Path) -> None:
    with pytest.raises(TemplateError):
        find_template("does-not-exist", extra_dirs=[templates_dir])


# --- rendering -----------------------------------------------------------


def test_render_query_uses_default_args() -> None:
    tpl = QueryTemplate(
        name="t",
        tool="search",
        query_template="hello {{topic}}",
        default_args={"topic": "world"},
    )
    assert render_query(tpl) == "hello world"


def test_render_query_overrides_default() -> None:
    tpl = QueryTemplate(
        name="t",
        tool="search",
        query_template="hello {{topic}}",
        default_args={"topic": "world"},
    )
    assert render_query(tpl, topic="brain") == "hello brain"


def test_render_query_missing_variable_raises() -> None:
    tpl = QueryTemplate(name="t", tool="search", query_template="x {{missing}}")
    with pytest.raises(TemplateError):
        render_query(tpl)


# --- output format ------------------------------------------------------


def test_format_output_markdown_passthrough() -> None:
    assert format_output("markdown", "# title") == "# title"


def test_format_output_json_envelopes() -> None:
    out = format_output("json", "body", sources=["a", "b"])
    assert '"body"' in out and '"sources"' in out


def test_format_output_unknown_raises() -> None:
    with pytest.raises(TemplateError):
        format_output("xml", "body")  # type: ignore[arg-type]


# --- CLI helpers --------------------------------------------------------


def test_parse_kv_splits_pairs() -> None:
    assert _parse_kv(["a=1", "b=hello world"]) == {"a": "1", "b": "hello world"}


def test_parse_kv_rejects_missing_equals() -> None:
    with pytest.raises(SystemExit):
        _parse_kv(["bad-arg"])


# --- pre-shipped templates --------------------------------------------


def test_pre_shipped_templates_load_and_render() -> None:
    """The four `examples/templates/*.yaml` must parse and render."""
    locs = discover_templates()
    by_name = {loc.template.name: loc for loc in locs}
    expected = {"voice-check", "series-status", "decision-history", "wcag-fact-check"}
    assert expected.issubset(by_name.keys()), f"missing: {expected - set(by_name)}"
    for name in expected:
        tpl = by_name[name].template
        rendered = render_query(tpl)  # uses default_args
        assert rendered.strip()
