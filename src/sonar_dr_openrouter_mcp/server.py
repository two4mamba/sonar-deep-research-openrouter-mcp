"""MCP server exposing Perplexity Sonar models (incl. Deep Research) via OpenRouter.

Why OpenRouter instead of Perplexity's own API: OpenRouter accepts Alipay / WeChat /
USDC / dual-currency cards, which removes the payment barrier that blocks many users
from Perplexity's native API. The model and pricing are identical.

Tools:
  - deep_research : full Sonar Deep Research agent (multi-step retrieval + synthesis),
                    returns a citation-backed Markdown report. Slow (minutes), costs
                    roughly $0.15-$1.30 per call.
  - ask           : quick cited answer via Sonar Pro. Fast and cheap; use for lookups.
  - reason        : step-by-step reasoning + web search via Sonar Reasoning Pro.

All tools accept an optional `history` for multi-turn conversations.
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEP_RESEARCH_MODEL = "perplexity/sonar-deep-research"
ASK_MODEL = "perplexity/sonar-pro"
REASON_MODEL = "perplexity/sonar-reasoning-pro"

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)

mcp = FastMCP("sonar-deep-research-openrouter")


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Get a key at https://openrouter.ai/keys "
            "and pass it to the server via the OPENROUTER_API_KEY environment variable."
        )
    return key


def _build_messages(query: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Combine optional prior turns with the new user query into a messages array.

    `history` is a list of {"role": "user"|"assistant", "content": "..."} items from
    earlier in the conversation. The new `query` is appended as the final user turn.
    """
    messages: list[dict[str, str]] = []
    for i, turn in enumerate(history or []):
        if not isinstance(turn, dict):
            raise ValueError(f"history[{i}] must be an object with 'role' and 'content'.")
        role = turn.get("role")
        content = turn.get("content")
        if role not in ("user", "assistant"):
            raise ValueError(f"history[{i}].role must be 'user' or 'assistant', got {role!r}.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"history[{i}].content must be a non-empty string.")
        messages.append({"role": role, "content": content})
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string.")
    messages.append({"role": "user", "content": query})
    return messages


def _format_citations(message: dict[str, Any], data: dict[str, Any]) -> str:
    """Build a Markdown '## Sources' block from the response's citations.

    Primary source is message['annotations'] (OpenRouter-normalized url_citation
    objects). Falls back to a top-level 'citations' list of bare URLs so nothing is
    silently dropped.
    """
    sources: list[str] = []
    seen: set[str] = set()
    for ann in message.get("annotations") or []:
        if not isinstance(ann, dict):
            continue
        uc = ann.get("url_citation") or {}
        url = uc.get("url")
        if url and url not in seen:
            seen.add(url)
            title = (uc.get("title") or url).strip()
            sources.append(f"[{len(sources) + 1}] {title} — {url}")
    if not sources:
        for url in data.get("citations") or []:
            if isinstance(url, str) and url not in seen:
                seen.add(url)
                sources.append(f"[{len(sources) + 1}] {url}")
    if not sources:
        return ""
    return "\n\n## Sources\n" + "\n".join(sources)


def _call_openrouter(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/",
        "X-Title": "sonar-deep-research-openrouter-mcp",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(OPENROUTER_URL, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Request timed out after {timeout:.0f}s. Deep Research can take several "
            "minutes; retry or lower reasoning_effort to 'low'."
        ) from exc

    if resp.status_code == 401:
        raise RuntimeError("OpenRouter rejected the key (401). Check OPENROUTER_API_KEY.")
    if resp.status_code == 402:
        raise RuntimeError(
            "Insufficient OpenRouter credits (402). Top up at https://openrouter.ai/credits."
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _render(data: dict[str, Any]) -> str:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = (message.get("content") or "").strip()
    content = _THINK_RE.sub("", content).strip()  # drop any <think>...</think> blocks
    if not content:
        return "The model returned no content. Try rephrasing the query."
    report = content + _format_citations(message, data)
    usage = data.get("usage") or {}
    cost = usage.get("cost")
    if cost is not None:
        report += f"\n\n---\n*OpenRouter cost: ${cost:.4f} · tokens: {usage.get('total_tokens', '?')}*"
    return report


@mcp.tool()
def deep_research(
    query: str,
    reasoning_effort: str = "medium",
    search_mode: str = "web",
    search_recency_filter: str | None = None,
    search_domain_filter: list[str] | None = None,
    search_context_size: str = "medium",
    history: list[dict[str, str]] | None = None,
) -> str:
    """Run Perplexity Sonar Deep Research (via OpenRouter) and return a citation-backed Markdown report.

    This is an autonomous deep-research agent: it plans, runs many web searches, reads
    sources, and synthesizes a long report with inline citations. It is SLOW (often
    1-5 minutes) and COSTS roughly $0.15-$1.30 per call. Use it for serious research
    questions, not quick lookups (use `ask` for those).

    Args:
        query: The research question or topic. Be specific; richer prompts yield better reports.
        reasoning_effort: 'low' | 'medium' (default) | 'high'. Higher = more sources, deeper,
            slower, costlier.
        search_mode: 'web' (default) or 'academic' (bias toward peer-reviewed sources).
            NOTE: via OpenRouter 'academic' is accepted but may not be strictly enforced.
        search_recency_filter: optional 'day' | 'week' | 'month' | 'year' to restrict freshness.
        search_domain_filter: optional list of domains, e.g. ["arxiv.org", "nature.com"].
            CAVEAT: unreliable via OpenRouter (has returned reports with no citations); leave
            unset if you need guaranteed sources.
        search_context_size: 'low' | 'medium' (default) | 'high' — how much web context to pull.
        history: optional prior conversation turns ([{"role","content"}, ...]) for follow-ups.

    Returns:
        A Markdown report ending with a '## Sources' list and a cost footer.
    """
    if reasoning_effort not in ("low", "medium", "high"):
        raise ValueError("reasoning_effort must be 'low', 'medium', or 'high'.")
    if search_context_size not in ("low", "medium", "high"):
        raise ValueError("search_context_size must be 'low', 'medium', or 'high'.")

    payload: dict[str, Any] = {
        "model": DEEP_RESEARCH_MODEL,
        "messages": _build_messages(query, history),
        "reasoning_effort": reasoning_effort,
        "web_search_options": {"search_context_size": search_context_size},
    }
    if search_mode == "academic":
        payload["search_mode"] = "academic"
    if search_recency_filter:
        payload["search_recency_filter"] = search_recency_filter
    if search_domain_filter:
        payload["search_domain_filter"] = search_domain_filter

    return _render(_call_openrouter(payload, timeout=600.0))


@mcp.tool()
def ask(
    query: str,
    search_recency_filter: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Quick, cited answer via Perplexity Sonar Pro (via OpenRouter). Fast and cheap.

    Use for factual lookups and short questions where full Deep Research is overkill.

    Args:
        query: The question.
        search_recency_filter: optional 'day' | 'week' | 'month' | 'year'.
        history: optional prior conversation turns ([{"role","content"}, ...]) for follow-ups.

    Returns:
        A concise Markdown answer ending with a '## Sources' list.
    """
    payload: dict[str, Any] = {
        "model": ASK_MODEL,
        "messages": _build_messages(query, history),
    }
    if search_recency_filter:
        payload["search_recency_filter"] = search_recency_filter
    return _render(_call_openrouter(payload, timeout=120.0))


@mcp.tool()
def reason(
    query: str,
    search_recency_filter: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Step-by-step reasoning with web search via Perplexity Sonar Reasoning Pro (via OpenRouter).

    Use for multi-step problems that need chained reasoning over fresh sources — harder than
    a simple `ask`, but far cheaper/faster than full `deep_research`. The model's internal
    <think> trace is stripped; you get the final answer plus sources.

    Args:
        query: The problem or question to reason through.
        search_recency_filter: optional 'day' | 'week' | 'month' | 'year'.
        history: optional prior conversation turns ([{"role","content"}, ...]) for follow-ups.

    Returns:
        A Markdown answer ending with a '## Sources' list.
    """
    payload: dict[str, Any] = {
        "model": REASON_MODEL,
        "messages": _build_messages(query, history),
    }
    if search_recency_filter:
        payload["search_recency_filter"] = search_recency_filter
    return _render(_call_openrouter(payload, timeout=180.0))


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
