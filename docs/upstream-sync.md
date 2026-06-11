# Upstream sync workflow

This repo is a **downstream fork** of
[`darco81/sdet-brain`](https://github.com/darco81/sdet-brain) (the
Apple Silicon flagship). Cross-platform fixes (server, MCP, Qdrant,
ingest pipeline, sparse/reranker) flow from upstream into this fork;
provider-layer divergence is intentional and stays here.

> **Important:** the two repos have **disjoint git histories**. The
> pre-publication PII history rewrite removed the common ancestor, so
> `git merge upstream/main` fails with *"refusing to merge unrelated
> histories"* and **does not work**. Sync is done by **patch-port**, not
> merge/rebase. See [`adr/0001-repo-architecture.md`](adr/0001-repo-architecture.md).

## One-time setup

Clone both repos as siblings:

```
dev/
├── sdet-brain/        # upstream (read-only mirror; pull, never push)
└── sdet-brain-win/    # this fork
```

```powershell
cd ..\sdet-brain
git pull            # keep the upstream mirror current
```

## Porting an upstream change

Pick the upstream range to port (e.g. the last synced tag → the new
tag), diff it for the **shared paths only**, and 3-way-apply it here:

```powershell
cd ..\sdet-brain-win

# Diff upstream across the range, restricted to cross-platform surfaces,
# then apply with 3-way merge so local context is respected.
git -C ..\sdet-brain diff vX.Y.Z..vA.B.C -- `
  src/sdet_brain/server `
  src/sdet_brain/storage `
  src/sdet_brain/ingestion `
  src/sdet_brain/embeddings/factory.py `
  src/sdet_brain/embeddings/sparse_embedder.py `
  src/sdet_brain/embeddings/reranker.py `
  src/sdet_brain/ocr/factory.py `
  src/sdet_brain/ocr/protocol.py `
  src/sdet_brain/ocr/prompts.py `
  src/sdet_brain/config.py `
  tests/server tests/storage tests/ingestion tests/ocr `
  | git apply --3way --reject
```

Resolve any `*.rej` hunks by hand (they appear where this fork already
diverges), then run the gates:

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest -q
```

For a single targeted fix, port one file:

```powershell
git -C ..\sdet-brain diff <sha>~1..<sha> -- src/sdet_brain/storage/qdrant_client.py `
  | git apply --3way
```

## Files this fork intentionally does NOT carry

Regenerate this list any time with:

```powershell
# mac-only src + tests = the strip surface
git -C ..\sdet-brain ls-files src tests > ..\mac.txt
git ls-files src tests > .\win.txt
# diff mac.txt against win.txt; mac-only entries are the strip surface
```

As of 2026-06-11 (regenerated from the real tree diff):

```
# MLX / Apple-Silicon only
src/sdet_brain/embeddings/mlx_provider.py
src/sdet_brain/ocr/mlx_vlm_provider.py
tests/embeddings/test_mlx_provider.py
tests/ocr/test_mlx_vlm_provider.py

# Local LLM router + chat (Qwen3-Next-80B doesn't fit 4 GB VRAM)
src/sdet_brain/llm/                       (entire dir: __init__, factory, mlx_provider, protocol, router)
src/sdet_brain/server/chat/               (entire dir: __init__, models, pipeline, prompt_template)
src/sdet_brain/server/routes/chat.py
src/sdet_brain/server/tools/multi_query.py
src/sdet_brain/server/tools/query_rewrite.py
src/sdet_brain/server/tools/summarize_results.py
src/sdet_brain/cli/chat_repl.py
src/sdet_brain/cli/templates.py
src/sdet_brain/cli/templates_cli.py
tests/llm/                                (entire dir)
tests/server/test_chat.py
tests/server/test_llm_tools.py
tests/server/test_multi_query.py
tests/cli/test_chat_repl.py
tests/cli/test_templates.py

# macOS scripts (replaced by Windows equivalents)
scripts/daily.sh, scripts/healthcheck.sh, scripts/digest.py, launchd plists
```

**Port candidates (NOT intentionally stripped — just not synced yet):**

```
src/sdet_brain/cli/search_cli.py    # pure cross-platform; port it
src/sdet_brain/cli/main_cli.py      # dispatcher for the search subcommand
tests/cli/test_search_cli.py
```

## Upstreaming (downstream → upstream)

Cross-platform fixes must land **upstream first**, then be ported down —
never downstream-only. This fork currently carries three improvements
that should be upstreamed:

- `server/app.py` — `init_collections` startup retry with backoff.
- `server/mcp_stdio.py` — UTF-8 stdio guard (also valuable on upstream).
- `embeddings/factory.py` — close provider client on failed health-check.

Keep shared modules **byte-identical to upstream** except where a line is
platform-functional; cosmetic drift (docstring rewording, function
reordering) guarantees future port conflicts.

## Releasing after a sync

Use a PEP 440-compatible version (see the release-hygiene task):

```powershell
# pyproject.toml: version = "0.2.1+win.0"   (local label; sorts == 0.2.1)
# CHANGELOG.md: add the entry.
git commit -am "chore: release 0.2.2+win.0 after upstream vA.B.C port"
git tag v0.2.2-win.0
git push origin v0.2.2-win.0
```
