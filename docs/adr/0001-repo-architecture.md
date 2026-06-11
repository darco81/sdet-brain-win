# ADR 0001 — Two repos vs single repo with platform extras

- Status: **Accepted** (interim) — 2026-06-11
- Context owner: Dariusz Kowalski

## Context

`sdet-brain` (macOS / Apple Silicon flagship) and `sdet-brain-win`
(Windows + CUDA, 4 GB VRAM) are maintained as two repositories by the
same author. `sdet-brain-win` is described in `NOTICE.md` and
`docs/upstream-sync.md` as a "one-way downstream fork" that pulls
cross-platform fixes from upstream via `git merge upstream/main`.

A 2026-06-10 review found that **mechanism is impossible**: after the
pre-publication PII history rewrite, `windows-port` shares **zero git
history** with upstream `main`:

```
git merge-base windows-port upstream/main   # exit 1, no common ancestor
git merge upstream/main                      # "refusing to merge unrelated histories"
```

So every "sync" has in practice been a manual re-implementation. The
cost is real: one hardening cycle was written twice (~25 duplicated
tests), and the fork lagged a purely cross-platform upstream feature
(the `search` CLI) by three weeks.

The platform split is also smaller than the two-repo overhead implies.
Both `pyproject.toml` files already gate platform deps behind
environment markers (`mlx-* ; sys_platform == 'darwin' and
platform_machine == 'arm64'`, `windows-toasts ; sys_platform ==
'win32'`), and both provider layers are factory registries
(`embeddings/factory._BUILDERS`, `ocr/factory`). The machinery for a
single repo with conditional provider registration already exists.

## Options

### Option A — Collapse into one repo with platform extras
- One codebase; MLX providers + LLM router + chat behind an optional
  `[llm]`/`[mlx]` extra and try-import registration; Ollama provider,
  `daily.py`, Task Scheduler XML, UTF-8 stdio guard live alongside.
- Pros: no sync problem at all; one CI matrix (macOS + Windows legs);
  one CHANGELOG; the review's recommended end-state and the cheaper
  current-standard architecture.
- Cons: **irreversible, outward-facing brand work** — archive the
  public `sdet-brain-win` repo, update `NOTICE.md`, portfolio entries,
  and any links; reconcile two version/tag namespaces. This is a brand
  decision, not just a code change.

### Option B — Keep two repos, fix the sync mechanism
- Replace the impossible merge/rebase recipe with **patch-port**
  (`git diff vX..vY -- <shared paths> | git apply --3way`), regenerate
  the strip list from the real tree-diff, and add an explicit
  *upstreaming* rule so cross-platform fixes land upstream first.
- Pros: low risk, reversible, immediately makes sync real; no brand or
  portfolio churn.
- Cons: ongoing two-repo maintenance; shared files must stay
  byte-identical or ports conflict.

## Decision

**Adopt Option B now.** Rewrite `docs/upstream-sync.md` and `NOTICE.md`
around patch-port, regenerate the strip list, and add the upstreaming
rule. This delivers a working sync mechanism today without any
irreversible action.

**Option A (single repo) is the recommended long-term direction**, but
its execution — archiving a public repo and rewiring brand/portfolio
assets — is **gated on the owner's explicit sign-off** and is out of
scope for an autopilot code change. Revisit when brand bandwidth allows.

## Consequences

- `docs/upstream-sync.md` now documents the patch-port workflow that
  actually works against disjoint histories.
- Shared modules (`server/`, `storage/`, `ingestion/`,
  `embeddings/factory`, `embeddings/sparse_embedder`,
  `embeddings/reranker`, `ocr/factory`, `ocr/ollama_provider`) are
  treated as byte-identical-to-upstream surfaces; the strip list is the
  exclusion filter.
- Cross-platform fixes are PR'd upstream first, then ported down — never
  landed downstream-only (the win fork currently carries three such
  downstream-only improvements: `init_collections` startup retry, the
  UTF-8 stdio guard, and factory close-on-failed-health-check; these
  should be upstreamed).
