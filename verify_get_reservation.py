
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

RESERVATION_ID = os.getenv("RESERVATION_ID")

if not RESERVATION_ID:
    raise RuntimeError("Please set RESERVATION_ID in your environment.")

async def main():

    print(f"Connecting to: {MCP_SERVER_URL}")

    async with streamablehttp_client(
        MCP_SERVER_URL
    ) as (read, write, _):

        async with ClientSession(read, write) as session:

            await session.initialize()

            print("\nConnected to Araaz Delights MCP Server!")

            print("\nRetrieving original reservation...")

            result = await session.call_tool(
                "get_reservation",
                arguments={
                    "reservation_id": RESERVATION_ID
                }
            )

            if result.isError:
                print("\nReservation retrieval failed.")

            else:
                print("\nReservation retrieval result:")

                for content in result.content:
                    if hasattr(content, "text"):
                        print(content.text)


if __name__ == "__main__":
    asyncio.run(main())
