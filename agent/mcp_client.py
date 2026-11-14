
"""
Persistent MCP Client Bridge.

Connects to an independently hosted Araaz Delights
MCP server through Streamable HTTP.
"""

import asyncio
import atexit
import json
import logging
import os
import threading
from contextlib import AsyncExitStack

from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("mcp_client")
logger.setLevel(logging.INFO)


# Load environment variables from .env
load_dotenv()

MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8001/mcp"
)


class MCPClient:

    def __init__(self):
        self.loop = None
        self.thread = None
        self.session = None

        self.ready = threading.Event()
        self.startup_error = None
        self.stop_event = None

        self.lock = threading.Lock()

    async def _run_client(self):
        """Keep the HTTP MCP connection open until shutdown."""

        async with AsyncExitStack() as stack:

            # Connect to the independently running MCP server.
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(MCP_SERVER_URL)
            )

            # Create an MCP session over the HTTP connection.
            self.session = await stack.enter_async_context(
                ClientSession(read, write)
            )

            # Initialize the MCP protocol session.
            await self.session.initialize()

            print(
                f">>> Connected to MCP server: {MCP_SERVER_URL}"
            )

            # Tell the main thread that MCP is ready.
            self.ready.set()

            # Keep the connection alive.
            await self.stop_event.wait()

        self.session = None
        print(">>> MCP connection closed.")

    def _worker(self):
        """Run the MCP client on its own background event loop."""

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.stop_event = asyncio.Event()

        try:
            self.loop.run_until_complete(
                self._run_client()
            )

        except Exception as exc:
            self.startup_error = exc
            logger.warning(
                f"Could not connect to Araaz Delights MCP server at {MCP_SERVER_URL}: {type(exc).__name__}. "
                "Ensure 'python mcp_server.py' is running on port 8001 for MCP tools."
            )

        finally:
            self.session = None
            self.ready.set()

            if self.loop and not self.loop.is_closed():
                self.loop.close()

    def _start(self):
        """Start the background MCP client if it is not running."""

        with self.lock:

            if self.thread is None or not self.thread.is_alive():

                self.ready.clear()
                self.startup_error = None

                self.thread = threading.Thread(
                    target=self._worker,
                    daemon=True,
                )

                self.thread.start()

        if not self.ready.wait(timeout=30):
            raise TimeoutError(
                "MCP server connection timed out."
            )

        if self.startup_error:
            raise RuntimeError(
                "Could not establish MCP connection."
            ) from self.startup_error

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict
    ):
        """Execute a tool using the existing MCP session."""

        if self.session is None:
            raise RuntimeError(
                "MCP session is not available."
            )

        result = await self.session.call_tool(
            tool_name,
            arguments=arguments,
        )

        if result.isError:
            error_details = "\n".join(
                content.text
                for content in result.content
                if hasattr(content, "text")
            )

            raise RuntimeError(
                f"MCP tool '{tool_name}' execution failed: "
                f"{error_details}"
            )

        for content in result.content:
            if hasattr(content, "text"):

                try:
                    return json.loads(content.text)

                except json.JSONDecodeError:
                    return {"result": content.text}

        # Support tools that return structured content.
        if result.structuredContent is not None:
            return result.structuredContent

        raise RuntimeError(
            "MCP server returned no readable result."
        )

    def call_tool(
        self,
        tool_name: str,
        arguments: dict
    ) -> dict:
        """Synchronous interface for existing chatbot tools."""

        self._start()

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(
                tool_name,
                arguments
            ),
            self.loop,
        )

        return future.result(timeout=60)

    def close(self):
        """Gracefully close the persistent MCP connection."""

        if (
            self.thread is not None
            and self.thread.is_alive()
            and self.loop is not None
            and self.stop_event is not None
        ):
            self.loop.call_soon_threadsafe(
                self.stop_event.set
            )

            self.thread.join(timeout=10)


# One shared MCP client for this application process.
mcp_client = MCPClient()

# Close the connection when the Python process exits.
atexit.register(mcp_client.close)


def call_mcp_tool(
    tool_name: str,
    arguments: dict
) -> dict:
    """Function used by the existing chatbot code."""

    return mcp_client.call_tool(
        tool_name,
        arguments
    )
