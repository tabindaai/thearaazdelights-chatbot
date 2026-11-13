
"""
Persistent MCP Client Bridge.

Starts the Araaz Delights MCP server once and keeps the
connection open for multiple tool calls.
"""

import asyncio
import atexit
import json
import sys
import threading
from pathlib import Path
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


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
        """Keep the MCP connection open until shutdown."""

        project_root = Path(__file__).resolve().parent.parent
        server_file = project_root / "mcp_server.py"

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(server_file)],
        )

        async with AsyncExitStack() as stack:

            read, write = await stack.enter_async_context(
                stdio_client(server_params)
            )

            self.session = await stack.enter_async_context(
                ClientSession(read, write)
            )

            await self.session.initialize()

            print(">>> Persistent MCP connection established.")

            # Tell the main thread that MCP is ready.
            self.ready.set()

            # Keep the connection alive.
            await self.stop_event.wait()

        print(">>> MCP connection closed.")

    def _worker(self):
        """Run the MCP client on its own background event loop."""

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.stop_event = asyncio.Event()

        try:
            self.loop.run_until_complete(self._run_client())

        except Exception as exc:
            self.startup_error = exc
            print(f">>> MCP client error: {exc}")

        finally:
            self.ready.set()
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
            raise TimeoutError("MCP server startup timed out.")

        if self.startup_error:
            raise RuntimeError(
                "Could not establish MCP connection."
            ) from self.startup_error

    async def _call_tool_async(self, tool_name: str, arguments: dict):
        """Execute a tool using the existing MCP session."""

        if self.session is None:
            raise RuntimeError("MCP session is not available.")

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
                return json.loads(content.text)

        raise RuntimeError("MCP server returned no readable result.")

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Synchronous interface for the existing chatbot tools."""

        self._start()

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(tool_name, arguments),
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
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.thread.join(timeout=10)


# One shared MCP client for this application process.
mcp_client = MCPClient()

# Close the MCP connection when the Python process exits.
atexit.register(mcp_client.close)


def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Function used by the existing chatbot code."""

    return mcp_client.call_tool(tool_name, arguments)
