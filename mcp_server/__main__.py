"""`python -m mcp_server`: stdio by default, HTTP when `MCP_TRANSPORT=streamable-http`."""

import os

from mcp_server.server import mcp

if os.environ.get("MCP_TRANSPORT") == "streamable-http":
    mcp.run(
        "streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8002")),
    )
else:
    mcp.run()
