# NOTICE

This repository is a **Windows-targeted fork** of [`darco81/sdet-brain`](https://github.com/darco81/sdet-brain) — the canonical Mac/Apple Silicon RAG mózg brand by Dariusz Kowalski.

## Relationship

| Repo | Purpose | Platform |
|---|---|---|
| `darco81/sdet-brain` (upstream) | Apple Silicon flagship with MLX provider + Qwen3-Next-80B LLM digest | macOS (M-series) |
| `darco81/sdet-brain-win` (this) | Stripped Windows + CUDA variant for 4 GB VRAM target | Windows |

Both repositories are maintained by the same author. This fork exists because the upstream architecture is MLX-heavy and tuned for 64 GB unified memory, while this fork targets a budget gaming PC (RTX 3050 4 GB VRAM, 32 GB RAM, AMD 9800X3D) and uses Ollama for embeddings + fastembed for reranker.

## What was stripped from upstream

- `src/sdet_brain/embeddings/mlx_provider.py` — MLX-specific, Apple Silicon only
- `src/sdet_brain/llm/` — LLM router (Qwen3-Next-80B doesn't fit 4 GB VRAM)
- `scripts/daily.sh`, `scripts/healthcheck.sh`, `scripts/digest.py` — bash + macOS-specific
- launchd plist examples
- `mlx-embeddings`, `mlx-lm` dependencies in `pyproject.toml`

## What was added or replaced

- `src/sdet_brain/embeddings/ollama_provider.py` — Ollama HTTP API wrapper for embeddings
- `scripts/daily.py` — cross-OS Python script (psutil + httpx)
- `scripts/windows-task-scheduler.xml` — Task Scheduler import template
- Claude Code + Claude Desktop MCP config examples for Windows

## Upstream sync workflow

```bash
git fetch upstream
git merge upstream/main
# Conflicts on mlx_provider.py / llm/ / scripts/daily.sh:
# resolve as "deleted by us" — we intentionally don't want those back
```

Only fixes touching cross-platform parts (server, MCP, Qdrant client, ingest pipeline) need real review. Provider-layer divergence is intentional.

## License

Same `LICENSE` as upstream — Source-Available (TBD), Copyright (c) 2026 Dariusz Kowalski. See `LICENSE` for full terms.

## Contact

`darecki9k@gmail.com`
