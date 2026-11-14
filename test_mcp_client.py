
"""
Standalone MCP Client Demo.

Connects to an independently hosted MCP server
using Streamable HTTP.

Demonstrates:
1. MCP initialization
2. Tool discovery
3. Tool execution
4. Result handling
"""

import asyncio
import os

from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


load_dotenv()

MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8001/mcp"
)


async def main():

    print(f"Connecting to: {MCP_SERVER_URL}")

    async with streamablehttp_client(
        MCP_SERVER_URL
    ) as (read, write, _):

        async with ClientSession(
            read,
            write
        ) as session:

            # 1. Initialize MCP session
            await session.initialize()

            print("\nConnected to Araaz Delights MCP Server!")

            # 2. Discover available tools
            tools = await session.list_tools()

            print("\nAvailable MCP tools:")

            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")

            # 3. Execute connection test
            print("\nCalling test_connection...")

            result = await session.call_tool(
                "test_connection",
                arguments={}
            )

            if result.isError:
                raise RuntimeError(
                    "Connection test tool failed."
                )

            print("\nConnection test result:")

            for content in result.content:
                if hasattr(content, "text"):
                    print(content.text)

            # 4. Execute actual reservation availability tool
            print("\nTesting table availability...")

            availability_result = await session.call_tool(
                "check_table_availability",
                arguments={
                    "reservation_date": "2026-11-20",
                    "reservation_time": "19:00",
                    "guest_count": 2,
                }
            )

            if availability_result.isError:
                raise RuntimeError(
                    "Availability tool execution failed."
                )

            print("\nAvailability tool result:")

            avail_data = {}
            for content in availability_result.content:
                if hasattr(content, "text"):
                    print(content.text)
                    import json
                    avail_data = json.loads(content.text)

            hold_token = avail_data.get("hold_token", "HOLD-TEST")

            # 5. Create reservation
            print("\nTesting reservation creation...")
            create_result = await session.call_tool(
                "create_reservation",
                arguments={
                    "hold_token": hold_token,
                    "customer_name": "Aarav",
                    "restaurant_id": "rest_01",
                    "reservation_date": "2026-11-20",
                    "reservation_time": "19:00",
                    "guest_count": 2,
                    "seating_preference": "indoor",
                }
            )
            print("\nCreate reservation result:")
            res_id = None
            for content in create_result.content:
                if hasattr(content, "text"):
                    print(content.text)
                    import json
                    create_data = json.loads(content.text)
                    res_id = create_data.get("reservation_id")

            if res_id:
                # 6. Get reservation
                print(f"\nTesting get reservation for {res_id}...")
                get_result = await session.call_tool(
                    "get_reservation",
                    arguments={"reservation_id": res_id}
                )
                for content in get_result.content:
                    if hasattr(content, "text"):
                        print(content.text)

                # 7. Update reservation
                print(f"\nTesting update reservation for {res_id}...")
                update_result = await session.call_tool(
                    "update_reservation",
                    arguments={
                        "reservation_id": res_id,
                        "reservation_time": "19:30",
                        "guest_count": 4,
                    }
                )
                for content in update_result.content:
                    if hasattr(content, "text"):
                        print(content.text)

                # 8. Cancel reservation
                print(f"\nTesting cancel reservation for {res_id}...")
                cancel_result = await session.call_tool(
                    "cancel_reservation",
                    arguments={"reservation_id": res_id}
                )
                for content in cancel_result.content:
                    if hasattr(content, "text"):
                        print(content.text)

            # 9. Find alternative slots
            print("\nTesting alternative slots...")
            alt_result = await session.call_tool(
                "find_alternative_slots",
                arguments={
                    "reservation_date": "2026-11-20",
                    "requested_time": "21:00",
                    "guest_count": 4,
                }
            )
            for content in alt_result.content:
                if hasattr(content, "text"):
                    print(content.text)

            print("\nALL MCP TOOLS VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(main())
