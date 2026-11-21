"""
Persistent Unified MCP Client Bridge for The Araaz Delights.

Connects to both:
1. Restaurant MCP Server (port 8001) - table availability, booking, modifications
2. Google Calendar MCP Server (port 8002) - calendar event creation, reminders, updates, cancellations

Maintains persistent Streamable HTTP sessions in a background event loop and routes
tool executions to the appropriate server transparently.
"""

import asyncio
import atexit
import json
import logging
import os
import socket
import threading
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("mcp_client")
logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv()

RESTAURANT_MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8001/mcp"
)

CALENDAR_MCP_SERVER_URL = os.getenv(
    "CALENDAR_MCP_SERVER_URL",
    "http://127.0.0.1:8002/mcp"
)

# Registry of tools routed to the Google Calendar MCP server
CALENDAR_TOOLS: Set[str] = {
    "test_calendar_connection",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
}


def _is_server_reachable(url: str, timeout: float = 0.2) -> bool:
    """Quick non-blocking probe to verify if the MCP server port is accepting TCP connections."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


class MCPClient:
    """
    Unified MCP Client connecting to both the Restaurant MCP Server and the
    Google Calendar MCP Server.
    
    Routes tool calls based on tool name:
    - Calendar tools -> Calendar MCP Server (port 8002)
    - Reservation tools -> Restaurant MCP Server (port 8001)
    """

    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None

        # Persistent sessions for both servers
        self.restaurant_session: Optional[ClientSession] = None
        self.calendar_session: Optional[ClientSession] = None

        # AsyncExitStacks to manage lifecycle
        self._restaurant_stack: Optional[AsyncExitStack] = None
        self._calendar_stack: Optional[AsyncExitStack] = None

        self.ready = threading.Event()
        self.startup_error = None
        self.stop_event: Optional[asyncio.Event] = None

        self.lock = threading.Lock()

    async def _connect_restaurant_async(self) -> Optional[ClientSession]:
        """Establish connection to the Restaurant MCP Server."""
        if not _is_server_reachable(RESTAURANT_MCP_SERVER_URL):
            logger.info(
                f"Restaurant MCP server port is not open at {RESTAURANT_MCP_SERVER_URL}. "
                "Backend direct database fallback will handle reservation requests."
            )
            self.restaurant_session = None
            return None

        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(RESTAURANT_MCP_SERVER_URL, timeout=1.0)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._restaurant_stack = stack
            self.restaurant_session = session
            logger.info(f">>> Connected to Restaurant MCP server: {RESTAURANT_MCP_SERVER_URL}")
            return session
        except BaseException as exc:
            self._restaurant_stack = None
            self.restaurant_session = None
            try:
                await stack.aclose()
            except BaseException:
                pass
            logger.warning(
                f"Could not connect to Restaurant MCP server at {RESTAURANT_MCP_SERVER_URL}: {type(exc).__name__}. "
                "Ensure 'python mcp_server.py' is running on port 8001."
            )
            return None

    async def _connect_calendar_async(self) -> Optional[ClientSession]:
        """Establish connection to the Calendar MCP Server."""
        if not _is_server_reachable(CALENDAR_MCP_SERVER_URL):
            logger.info(
                f"Calendar MCP server not currently reachable at {CALENDAR_MCP_SERVER_URL} (port closed). "
                "Calendar features will remain offline until 'python calendar_mcp_server.py' is started."
            )
            self.calendar_session = None
            return None

        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(CALENDAR_MCP_SERVER_URL, timeout=1.0)
            )
            session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._calendar_stack = stack
            self.calendar_session = session
            logger.info(f">>> Connected to Calendar MCP server: {CALENDAR_MCP_SERVER_URL}")
            return session
        except BaseException as exc:
            self._calendar_stack = None
            self.calendar_session = None
            try:
                await stack.aclose()
            except BaseException:
                pass
            logger.info(
                f"Calendar MCP server not currently reachable at {CALENDAR_MCP_SERVER_URL}: {type(exc).__name__}. "
                "Calendar features will remain offline until 'python calendar_mcp_server.py' is started."
            )
            return None

    async def _run_client(self):
        """Keep the background MCP client loop running until shutdown."""
        # Connect to Restaurant MCP server
        try:
            await self._connect_restaurant_async()
        except BaseException as exc:
            logger.warning(f"Error during restaurant MCP connection: {exc}")
            self.restaurant_session = None

        # Connect to Calendar MCP server (optional, fault-isolated)
        try:
            await self._connect_calendar_async()
        except BaseException as exc:
            logger.warning(f"Error during calendar MCP connection: {exc}")
            self.calendar_session = None

        # Mark client as ready to handle calls
        self.ready.set()

        # Wait until stop_event is signalled
        if self.stop_event:
            await self.stop_event.wait()

        # Clean shutdown
        if self._restaurant_stack:
            try:
                await self._restaurant_stack.aclose()
            except BaseException:
                pass
        if self._calendar_stack:
            try:
                await self._calendar_stack.aclose()
            except BaseException:
                pass

        self.restaurant_session = None
        self.calendar_session = None
        self._restaurant_stack = None
        self._calendar_stack = None
        logger.info(">>> MCP connections closed gracefully.")

    def _worker(self):
        """Run the persistent MCP client on its own background event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()

        try:
            self.loop.run_until_complete(self._run_client())
        except Exception as exc:
            self.startup_error = exc
            logger.error(f"MCP client worker encountered error: {exc}")
        finally:
            self.restaurant_session = None
            self.calendar_session = None
            self.ready.set()
            if self.loop and not self.loop.is_closed():
                self.loop.close()

    def _start(self):
        """Start the background MCP thread if not already running."""
        # Fast exit without blocking if neither MCP server port is reachable
        if not _is_server_reachable(RESTAURANT_MCP_SERVER_URL) and not _is_server_reachable(CALENDAR_MCP_SERVER_URL):
            self.ready.set()
            return

        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.ready.clear()
                self.startup_error = None
                self.thread = threading.Thread(
                    target=self._worker,
                    daemon=True,
                    name="MCPClientWorkerThread",
                )
                self.thread.start()

        if not self.ready.wait(timeout=2):
            logger.warning("MCP client initialization timed out. Direct database fallback will be used.")

        if self.startup_error:
            logger.warning(f"MCP client startup error ({self.startup_error}). Direct database fallback will be used.")

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: dict
    ) -> Dict[str, Any]:
        """Execute a tool using the appropriate MCP session."""
        is_calendar = tool_name in CALENDAR_TOOLS

        if is_calendar:
            session = self.calendar_session
            if session is None:
                return {
                    "success": False,
                    "error": (
                        f"Google Calendar MCP server is not available at {CALENDAR_MCP_SERVER_URL}. "
                        "Make sure 'python calendar_mcp_server.py' is running on port 8002."
                    ),
                    "calendar_unavailable": True,
                }
        else:
            session = self.restaurant_session
            if session is None:
                raise RuntimeError(
                    f"Restaurant MCP session is not available at {RESTAURANT_MCP_SERVER_URL}. "
                    "Make sure 'python mcp_server.py' is running on port 8001."
                )

        result = await session.call_tool(tool_name, arguments=arguments)

        if result.isError:
            error_details = "\n".join(
                content.text
                for content in result.content
                if hasattr(content, "text")
            )
            if is_calendar:
                return {"success": False, "error": f"MCP tool '{tool_name}' failed: {error_details}"}
            raise RuntimeError(f"MCP tool '{tool_name}' execution failed: {error_details}")

        for content in result.content:
            if hasattr(content, "text"):
                try:
                    return json.loads(content.text)
                except json.JSONDecodeError:
                    return {"result": content.text}

        if result.structuredContent is not None:
            return result.structuredContent

        if is_calendar:
            return {"success": False, "error": "Calendar MCP server returned no readable result."}
        raise RuntimeError("MCP server returned no readable result.")

    def call_tool(
        self,
        tool_name: str,
        arguments: dict
    ) -> dict:
        """
        Synchronous interface for chatbot tools to invoke an MCP tool on either server.
        """
        self._start()

        if self.loop is None or not self.loop.is_running():
            raise RuntimeError("MCP client background event loop is not running.")

        is_calendar = tool_name in CALENDAR_TOOLS
        if is_calendar and self.calendar_session is None:
            return {
                "success": False,
                "error": f"Google Calendar MCP server is not available at {CALENDAR_MCP_SERVER_URL}.",
                "calendar_unavailable": True,
            }
        if not is_calendar and self.restaurant_session is None:
            raise RuntimeError(
                f"Restaurant MCP session is not available at {RESTAURANT_MCP_SERVER_URL}."
            )

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_async(tool_name, arguments),
            self.loop,
        )

        return future.result(timeout=5)

    # -------------------------------------------------------------------------
    # Convenience methods for Google Calendar operations
    # -------------------------------------------------------------------------

    def create_calendar_event(
        self,
        session_id: str,
        customer_name: str,
        customer_email: str,
        reservation_date: str,
        reservation_time: str,
        guest_count: int,
        reservation_id: str,
        special_requests: str = "",
        seating_preference: str = "any",
    ) -> dict:
        """Create a Google Calendar event for a confirmed reservation with 3-hr reminder."""
        try:
            return self.call_tool(
                "create_calendar_event",
                {
                    "session_id": session_id,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "reservation_date": reservation_date,
                    "reservation_time": reservation_time,
                    "guest_count": guest_count,
                    "reservation_id": reservation_id,
                    "special_requests": special_requests,
                    "seating_preference": seating_preference,
                },
            )
        except Exception as exc:
            logger.warning(f"Calendar event creation failed: {exc}")
            return {"success": False, "error": str(exc), "calendar_unavailable": True}

    def update_calendar_event(
        self,
        session_id: str,
        event_id: str,
        reservation_date: str = "",
        reservation_time: str = "",
        guest_count: int = 0,
        special_requests: str = "",
        seating_preference: str = "",
    ) -> dict:
        """Update an existing Google Calendar event when a reservation is modified."""
        try:
            return self.call_tool(
                "update_calendar_event",
                {
                    "session_id": session_id,
                    "event_id": event_id,
                    "reservation_date": reservation_date,
                    "reservation_time": reservation_time,
                    "guest_count": guest_count,
                    "special_requests": special_requests,
                    "seating_preference": seating_preference,
                },
            )
        except Exception as exc:
            logger.warning(f"Calendar event update failed: {exc}")
            return {"success": False, "error": str(exc), "calendar_unavailable": True}

    def delete_calendar_event(
        self,
        session_id: str,
        event_id: str,
    ) -> dict:
        """Delete a Google Calendar event when a reservation is cancelled."""
        try:
            return self.call_tool(
                "delete_calendar_event",
                {
                    "session_id": session_id,
                    "event_id": event_id,
                },
            )
        except Exception as exc:
            logger.warning(f"Calendar event deletion failed: {exc}")
            return {"success": False, "error": str(exc), "calendar_unavailable": True}

    def is_calendar_available(self) -> bool:
        """Check if the Calendar MCP server is reachable."""
        try:
            result = self.call_tool("test_calendar_connection", {})
            return bool(result)
        except Exception:
            return False

    def close(self):
        """Gracefully close both persistent MCP connections."""
        if (
            self.thread is not None
            and self.thread.is_alive()
            and self.loop is not None
            and self.stop_event is not None
        ):
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.thread.join(timeout=10)


# Single shared MCP client instance for the entire application
mcp_client = MCPClient()

# Register shutdown hook
atexit.register(mcp_client.close)


def call_mcp_tool(
    tool_name: str,
    arguments: dict
) -> dict:
    """
    Unified function used by the chatbot code to call tools on either MCP server.
    """
    return mcp_client.call_tool(
        tool_name,
        arguments
    )
