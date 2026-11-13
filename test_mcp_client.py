
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():

    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()

            print("Connected to Araaz Delights MCP Server!")

            # Discover available tools
            tools = await session.list_tools()

            print("\nAvailable MCP tools:")
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")

            # Test connection
            result = await session.call_tool(
                "test_connection",
                arguments={},
            )

            print("\nConnection test:")
            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text)

            # Test actual availability
            availability_result = await session.call_tool(
                "check_table_availability",
                arguments={
                    "reservation_date": "2026-11-20",
                    "reservation_time": "19:00",
                    "guest_count": 2,
                },
            )

            print("\nAvailability tool result:")
            for content in availability_result.content:
                if hasattr(content, "text"):
                    print(content.text)


if __name__ == "__main__":
    asyncio.run(main())
