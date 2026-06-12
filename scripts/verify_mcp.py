"""Verify the MCP server module imports cleanly and tools register."""
import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from mcp_server.server import mcp


async def main():
    print(f"MCP server name: {mcp.name}")
    tools = await mcp.list_tools()
    print(f"Registered tools ({len(tools)}):")
    for t in tools:
        first_line = (t.description or "").splitlines()[0] if t.description else ""
        print(f"  - {t.name}")
        print(f"      {first_line}")


asyncio.run(main())
