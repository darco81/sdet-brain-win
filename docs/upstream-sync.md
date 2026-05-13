# Upstream sync workflow

This repo is a **one-way downstream fork** of
[`darco81/sdet-brain`](https://github.com/darco81/sdet-brain) (the
Apple Silicon flagship). Bug fixes and improvements that touch
cross-platform code (server, MCP, Qdrant, ingest pipeline) should
flow from upstream into this fork; provider-layer divergence is
intentional and stays here.

## One-time setup

```powershell
cd C:\Users\<USER>\dev\sdet-brain-win
git remote add upstream https://github.com/darco81/sdet-brain.git
git remote -v
# origin    git@...:<owner>/sdet-brain-win.git   (fetch)
# origin    git@...:<owner>/sdet-brain-win.git   (push)
# upstream  https://github.com/darco81/sdet-brain.git  (fetch)
# upstream  https://github.com/darco81/sdet-brain.git  (push)
```

## Pulling upstream changes

```powershell
# Make sure your working tree is clean.
git status

# Fetch and merge upstream/main into local main.
git checkout main
git fetch upstream
git merge upstream/main

# Now rebase your feature branch on top of new main.
git checkout windows-port
git rebase main
```

## Resolving expected conflicts

The strip commit deleted several upstream files. When upstream
modifies any of them, you'll see merge/rebase conflicts marked
**"deleted by us"**.

Resolve every such conflict the same way — keep it deleted:

```powershell
git rm src/sdet_brain/embeddings/mlx_provider.py
git rm src/sdet_brain/llm/router.py
# ... etc for each "deleted by us" file
git rebase --continue
```

The full list of files this fork intentionally doesn't carry:

```
src/sdet_brain/embeddings/mlx_provider.py
src/sdet_brain/llm/                                  (entire dir)
src/sdet_brain/server/tools/multi_query.py
src/sdet_brain/server/tools/query_rewrite.py
src/sdet_brain/server/tools/summarize_results.py
src/sdet_brain/server/chat/                          (entire dir)
src/sdet_brain/server/routes/chat.py
src/sdet_brain/cli/chat_repl.py
scripts/daily.sh
scripts/healthcheck.sh
scripts/digest.py
tests/llm/                                            (entire dir)
tests/embeddings/test_mlx_provider.py
tests/server/test_{chat,llm_tools,multi_query}.py
tests/cli/test_chat_repl.py
```

## What to actually merge

Cherry-pick rather than full-merge when in doubt. Good candidates:

* Server route bug fixes (e.g. `routes/health.py`, `routes/ingest.py`).
* Qdrant client patches (`storage/qdrant_client.py`).
* Ingest pipeline improvements (`ingestion/pipeline.py`,
  `ingestion/chunker.py`).
* MCP tool fixes that don't depend on LLM (`server/tools/search.py`,
  `server/tools/list_sources.py`, `server/tools/ingest.py`,
  `server/tools/get_chunk_neighbors.py`, `server/tools/domain/*`).
* fastembed reranker / sparse embedder updates.
* Tests for any of the above.

Skip:

* Anything under `embeddings/mlx_provider.py` or `llm/`.
* `chat/` REPL surface.
* MLX-specific scripts.
* Settings fields named `mlx_*` or `llm_*` (they no longer exist here).

## When the merge gets large

If upstream and downstream diverge significantly (e.g. a v0.6.0 with
big refactors), a clean **3-way replay** is often nicer than a giant
merge commit:

1. `git checkout main` → up to date with `upstream/main`.
2. `git checkout -b windows-port-vN` (fresh branch).
3. `git cherry-pick <strip-commit>` from the previous Windows port.
4. `git cherry-pick <ollama-provider-commit>`, etc.
5. Resolve any new conflicts caused by upstream renames.

Push `windows-port-vN` as the new active branch and retire
`windows-port-vM`.

## Releasing after a sync

After a successful merge or replay, bump the version and tag:

```powershell
# Edit pyproject.toml: version = "0.1.0.dev1" → "0.1.1.dev0" (or whatever)
# Edit CHANGELOG.md to add the new entry.
git commit -am "chore: bump to 0.1.0-win.1 after upstream vX.Y.Z sync"
git tag v0.1.0-win.1
git push --tags
```
