"""
Google Calendar MCP Server for Araaz Delights Restaurant Chatbot.

This server exposes Google Calendar operations as MCP tools so that the
restaurant AI agent can create, update, and delete calendar events on behalf
of authenticated customers.  It follows the exact same FastMCP / Streamable-
HTTP pattern used by the existing mcp_server.py but listens on port 8002 so
the two servers can run side-by-side.

Tools exposed:
  - test_calendar_connection  – health-check
  - create_calendar_event     – add a reservation event to a customer's calendar
  - update_calendar_event     – patch an existing event when details change
  - delete_calendar_event     – remove an event when a reservation is cancelled
"""

from dotenv import load_dotenv
load_dotenv()

import logging
from mcp.server.fastmcp import FastMCP

from services.calendar_service import calendar_service  # noqa: E402  (singleton)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("calendar_mcp_server")

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("Araaz Delights Calendar Server", host="0.0.0.0", port=8002)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def test_calendar_connection() -> str:
    """Test that the Calendar MCP server is running."""
    logger.info("test_calendar_connection called")
    return "Araaz Delights Calendar MCP server is working!"


@mcp.tool()
def create_calendar_event(
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
    """
    Create a Google Calendar event for a confirmed restaurant reservation.

    Args:
        session_id: The customer session ID with authorized Google Calendar access.
        customer_name: Full name of the guest.
        customer_email: Customer's email address from the reservation.
        reservation_date: Date in YYYY-MM-DD format.
        reservation_time: Time in HH:MM 24-hour format.
        guest_count: Number of guests.
        reservation_id: The confirmed restaurant reservation ID.
        special_requests: Any special requests or dietary notes (optional).
        seating_preference: Seating preference such as indoor or outdoor (optional).

    Returns:
        dict with keys 'success', 'event_id', 'event_link' on success,
        or 'success' and 'error' on failure.
    """
    logger.info(
        "create_calendar_event called | session=%s reservation_id=%s date=%s time=%s guests=%d",
        session_id,
        reservation_id,
        reservation_date,
        reservation_time,
        guest_count,
    )

    reservation_data = {
        "customer_name": customer_name,
        "customer_email": customer_email,
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "guest_count": guest_count,
        "reservation_id": reservation_id,
        "special_requests": special_requests,
        "seating_preference": seating_preference,
    }

    result = calendar_service.create_reservation_event(session_id, reservation_data)
    logger.info("create_calendar_event result: %s", result)
    return result


@mcp.tool()
def update_calendar_event(
    session_id: str,
    event_id: str,
    reservation_date: str = "",
    reservation_time: str = "",
    guest_count: int = 0,
    special_requests: str = "",
    seating_preference: str = "",
) -> dict:
    """
    Update an existing Google Calendar event when reservation details change.

    Args:
        session_id: The customer session ID with authorized Google Calendar access.
        event_id: The Google Calendar event ID to update.
        reservation_date: New date in YYYY-MM-DD format (optional).
        reservation_time: New time in HH:MM format (optional).
        guest_count: New party size (optional, 0 means unchanged).
        special_requests: Updated special requests (optional).
        seating_preference: Updated seating preference (optional).

    Returns:
        dict with keys 'success' and 'event_id' on success,
        or 'success' and 'error' on failure.
    """
    logger.info(
        "update_calendar_event called | session=%s event_id=%s",
        session_id,
        event_id,
    )

    # Only include fields that carry a meaningful value.
    reservation_data: dict = {}
    if reservation_date:
        reservation_data["reservation_date"] = reservation_date
    if reservation_time:
        reservation_data["reservation_time"] = reservation_time
    if guest_count:  # 0 means "unchanged"
        reservation_data["guest_count"] = guest_count
    if special_requests:
        reservation_data["special_requests"] = special_requests
    if seating_preference:
        reservation_data["seating_preference"] = seating_preference

    result = calendar_service.update_reservation_event(session_id, event_id, reservation_data)
    logger.info("update_calendar_event result: %s", result)
    return result


@mcp.tool()
def delete_calendar_event(session_id: str, event_id: str) -> dict:
    """
    Delete a Google Calendar event when a reservation is cancelled.

    Args:
        session_id: The customer session ID with authorized Google Calendar access.
        event_id: The Google Calendar event ID to delete.

    Returns:
        dict with key 'success' on success, or 'success' and 'error' on failure.
    """
    logger.info(
        "delete_calendar_event called | session=%s event_id=%s",
        session_id,
        event_id,
    )

    result = calendar_service.delete_reservation_event(session_id, event_id)
    logger.info("delete_calendar_event result: %s", result)
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting Araaz Delights Calendar MCP server on port 8002 …")
    mcp.run(transport="streamable-http")
