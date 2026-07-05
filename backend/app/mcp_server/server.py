from mcp.server.fastmcp import FastMCP

from app.mcp_server.tools import register_tools

mcp = FastMCP("citepilot")

register_tools(mcp)

if __name__ == "__main__":
    # stdio transport: mcp client launches this process and speaks over stdin/out
    mcp.run() 