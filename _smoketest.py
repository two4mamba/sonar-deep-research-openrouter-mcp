"""Local smoke test: tool registration, multi-turn message building, and (if a key is
present) a cheap live `reason` call with conversation history."""
import asyncio, os, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
from sonar_dr_openrouter_mcp import server  # noqa: E402


async def list_tools():
    tools = await server.mcp.list_tools()
    print("=== REGISTERED TOOLS ===")
    for t in tools:
        params = list((t.inputSchema or {}).get("properties", {}).keys())
        print(f"  - {t.name}: params={params}")
    return [t.name for t in tools]


def test_build_messages():
    print("\n=== UNIT: _build_messages (multi-turn) ===")
    msgs = server._build_messages(
        "And how does it compare to RAG?",
        history=[
            {"role": "user", "content": "What is MCP?"},
            {"role": "assistant", "content": "MCP is a protocol for tool use."},
        ],
    )
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"], msgs
    assert msgs[-1]["content"].startswith("And how"), msgs
    print("  OK: 3 turns assembled, new query appended last")
    for bad in ([{"role": "system", "content": "x"}], [{"role": "user", "content": ""}]):
        try:
            server._build_messages("q", bad)
            raise AssertionError("should have rejected: %r" % bad)
        except ValueError:
            pass
    print("  OK: invalid history rejected")


def test_strip_think():
    print("\n=== UNIT: <think> stripping ===")
    data = {"choices": [{"message": {"content": "<think>secret</think>\nFinal answer."}}],
            "usage": {}}
    out = server._render(data)
    assert "secret" not in out and "Final answer." in out, out
    print("  OK: <think> block removed")


def live_reason():
    print("\n=== LIVE: reason() with history (cheap) ===")
    out = server.reason(
        "Give a one-sentence definition.",
        history=[{"role": "user", "content": "Tell me about the Model Context Protocol."}],
    )
    print("  len:", len(out), "| has Sources:", "## Sources" in out,
          "| has cost:", "OpenRouter cost" in out, "| no <think>:", "<think>" not in out)
    print("  tail:", out[-300:].encode("utf-8", "replace").decode("utf-8"))


if __name__ == "__main__":
    names = asyncio.run(list_tools())
    assert set(names) == {"deep_research", "ask", "reason"}, names
    test_build_messages()
    test_strip_think()
    print("\nALL OFFLINE CHECKS PASSED")
    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            live_reason()
        except Exception as e:  # key may be revoked; offline checks already passed
            print("  LIVE test skipped/failed (key revoked?):", e)
    else:
        print("\n(skip live test: no OPENROUTER_API_KEY)")
