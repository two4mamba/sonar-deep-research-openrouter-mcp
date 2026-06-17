# Sonar Deep Research (via OpenRouter) — MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes **Perplexity Sonar Deep Research** — plus **Sonar Pro** (`ask`) and **Sonar Reasoning Pro** (`reason`) — to any MCP client (Claude Code, Claude Desktop, Cursor, …) **through [OpenRouter](https://openrouter.ai)** instead of Perplexity's own API.

---

## What it does

Gives your AI assistant three research tools backed by Perplexity's Sonar models:

| Tool | Model | Use for | Speed / cost* |
|------|-------|---------|---------------|
| `deep_research` | `perplexity/sonar-deep-research` | Serious research: plans, runs many web searches, reads sources, writes a long citation-backed report | Slow (1–5 min), ~$0.15–$1.30/call |
| `ask` | `perplexity/sonar-pro` | Quick cited factual answers | Fast, ~$0.005–$0.02/call |
| `reason` | `perplexity/sonar-reasoning-pro` | Multi-step reasoning over fresh sources (harder than `ask`, cheaper than `deep_research`) | Medium, ~$0.005–$0.02/call |

All tools return Markdown ending in a `## Sources` list (from the response's `url_citation` annotations) and an OpenRouter cost footer. Every tool accepts an optional `history` for multi-turn follow-ups.

*Observed costs as of 2026-06; depend on `reasoning_effort` and number of searches.

## Why this exists (background)

Perplexity's native API requires an international credit card — a hard payment barrier for many users (notably in mainland China). **OpenRouter resells the exact same `perplexity/sonar-deep-research` model at the same token price, but accepts Alipay, WeChat Pay, USDC, and dual-currency cards.** This server is the bridge: identical model and report quality, no Perplexity billing account needed.

It is a practical **drop-in for the deep-research / cited-Q&A use case** of the official Perplexity MCP. See [Scope & limitations](#scope--limitations).

## Requirements

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended runner) — or pip
- Python deps (installed automatically by `uv`/pip): `mcp>=1.2`, `httpx>=0.27`
- An **OpenRouter API key** with a few dollars of credit

## 1. Get an OpenRouter API key

1. Sign up at <https://openrouter.ai> (Google login works).
2. Add credit at <https://openrouter.ai/credits> via **Alipay / WeChat / card / USDC** (no minimum; start with $5).
3. Create a key at <https://openrouter.ai/keys> — it looks like `sk-or-v1-...`.

## 2. Install & configure

You can run it three ways. Pick one, then [configure your API key](#3-configure-your-api-key).

**A. From PyPI via `uvx` (after the package is published):**
```bash
claude mcp add sonar-dr -s user \
  -e OPENROUTER_API_KEY=sk-or-v1-YOURKEY \
  -- uvx sonar-deep-research-openrouter-mcp
```

**B. Directly from GitHub (no clone needed, once the repo is public):**
```bash
claude mcp add sonar-dr -s user \
  -e OPENROUTER_API_KEY=sk-or-v1-YOURKEY \
  -- uvx --from git+https://github.com/two4mamba/sonar-deep-research-openrouter-mcp sonar-dr-mcp
```

**C. From a local clone (works today, before publishing):**
```bash
git clone https://github.com/two4mamba/sonar-deep-research-openrouter-mcp
claude mcp add sonar-dr -s user \
  -e OPENROUTER_API_KEY=sk-or-v1-YOURKEY \
  -- uvx --from /path/to/sonar-deep-research-openrouter-mcp sonar-dr-mcp
```
(`uvx --from <path|git-url> sonar-dr-mcp` builds the package in an isolated env and runs its `sonar-dr-mcp` console entry point — no global install, no `cwd` flag needed.)

**D. Claude Desktop** — add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "sonar-dr": {
      "command": "uvx",
      "args": ["sonar-deep-research-openrouter-mcp"],
      "env": { "OPENROUTER_API_KEY": "sk-or-v1-YOURKEY" }
    }
  }
}
```

> After adding, **restart / open a new session** for the tools to load. Verify with `claude mcp list` — you want `sonar-dr ... ✓ Connected`.

## 3. Configure your API key

The server reads the key from the **`OPENROUTER_API_KEY`** environment variable. Three ways to provide it, in increasing order of safety:

1. **Inline in `claude mcp add`** — the `--env OPENROUTER_API_KEY=...` shown above. Simplest; the key is stored in plaintext in `~/.claude.json`.
2. **Edit the config file** — open `~/.claude.json`, find the `sonar-dr` server entry, and set/replace its `env.OPENROUTER_API_KEY` value. Use this to rotate the key later.
3. **System/user environment variable (recommended, keeps the key out of config files):**
   - macOS/Linux: add `export OPENROUTER_API_KEY=sk-or-v1-...` to your shell profile.
   - Windows (PowerShell, persistent): `setx OPENROUTER_API_KEY "sk-or-v1-..."` then restart the terminal.
   - Then register the server **without** `--env`:
     ```bash
     claude mcp add sonar-dr -s user -- uvx sonar-deep-research-openrouter-mcp
     ```
   The MCP process inherits Claude Code's environment, so the server picks the key up automatically. To change keys, just update the environment variable.

> If the key is missing the server returns a clear error: *"OPENROUTER_API_KEY is not set…"*. A revoked/invalid key surfaces as a `401`.

## 4. Usage / how to trigger

Once connected (and after a session restart), the tools are available to the assistant. You can trigger them two ways:

**Let the assistant choose** — just ask naturally; Claude picks the right tool from the descriptions:
- *"Do deep research on the 2024–2026 trends in solid-state batteries and write a sourced report."* → `deep_research`
- *"Quick: what's the latest stable Python version?"* → `ask`
- *"Reason through whether RAG or long-context is better for our use case, citing recent sources."* → `reason`

**Ask for a tool explicitly** — *"Use the sonar-dr deep_research tool with reasoning_effort=high on …"*

**Multi-turn follow-up** — the assistant can pass earlier turns via `history`, e.g. after an `ask` you say *"now go deeper on point 3"* and it calls `deep_research` with the prior exchange as context.

### `deep_research` parameters
- `query` (required) — the research question. Be specific.
- `reasoning_effort` — `low` | `medium` (default) | `high`. Higher = more sources, deeper, slower, costlier.
- `search_mode` — `web` (default) | `academic`. See caveat below.
- `search_recency_filter` — `day` | `week` | `month` | `year`.
- `search_domain_filter` — list of domains, e.g. `["arxiv.org", "nature.com"]`. See caveat below.
- `search_context_size` — `low` | `medium` (default) | `high`.
- `history` — optional prior turns `[{"role","content"}, ...]`.

`ask` and `reason` accept `query`, `search_recency_filter`, and `history`.

## Scope & limitations

Replicates the **deep-research, cited Q&A (`ask`), and reasoning (`reason`)** capabilities of the official Perplexity MCP, including multi-turn. It does **not** replicate:

- The official MCP's standalone **Search API** tool (`/search` ranked results) — that endpoint **does not exist on OpenRouter** and cannot be proxied. Use a dedicated search MCP (Exa/Tavily) for raw ranked results.

### Verified behavior (tested 2026-06, real OpenRouter calls)
- ✅ `deep_research`, `ask`, `reason` all work end-to-end; citations render into `## Sources`; `<think>` traces are stripped.
- ⚠️ **`search_domain_filter` is unreliable via OpenRouter.** Restricting to `["arxiv.org"]` returned a full report but **zero citations**. Leave it unset if you need guaranteed sources. (Upstream OpenRouter↔Perplexity passthrough limitation, not a bug here.)
- ⚠️ **`search_mode: "academic"` is accepted but not strictly enforced** via OpenRouter (non-academic sources have appeared). Treat it as a soft hint.

## Cost notes

OpenRouter bills `sonar-deep-research` at $2/M input + $8/M output tokens, plus reasoning/citation tokens and $5/1000 searches. Observed: a `low`-effort deep research call ≈ **$0.19**; an `ask`/`reason` call ≈ **$0.006–$0.01**. `deep_research` is not for high-frequency use.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `OPENROUTER_API_KEY is not set` | Provide the key (see [§3](#3-configure-your-api-key)). |
| `401` from OpenRouter | Key invalid/revoked — create a new one. |
| `402` insufficient credits | Top up at <https://openrouter.ai/credits>. |
| Server not `Connected` in `claude mcp list` | Ensure `uv` is installed and on PATH; re-run the add command. |
| Tools don't appear | Restart / open a new Claude Code session. |
| Request times out | `deep_research` is slow; retry or use `reasoning_effort="low"`. |

## Development

```bash
uv run --no-project --with mcp --with httpx --python 3.11 python _smoketest.py   # offline + (with key) live checks
uv build                                                                          # build wheel/sdist
```

## License

Apache-2.0. See [LICENSE](./LICENSE).

## Acknowledgements

Built with the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Not affiliated with Perplexity or OpenRouter.
