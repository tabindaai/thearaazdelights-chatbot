
"""
MCP Server for The Araaz Delights.

Exposes restaurant reservation operations to AI clients.
"""

from mcp.server.fastmcp import FastMCP
from schemas.reservation import (
    AvailabilityRequest,
    ReservationCreateRequest,
)
from services.restaurant_api import restaurant_api

mcp = FastMCP("Araaz Delights Reservation Server")


@mcp.tool()
def test_connection() -> str:
    """Test the MCP server connection."""
    return "Araaz Delights MCP server is working!"


@mcp.tool()
def check_table_availability(
    reservation_date: str,
    reservation_time: str,
    guest_count: int,
) -> dict:
    """
    Check restaurant table availability for a date, time, and party size.

    Args:
        reservation_date: Reservation date in YYYY-MM-DD format.
        reservation_time: Reservation time in HH:MM 24-hour format.
        guest_count: Number of guests, between 1 and 20.
    """
    request = AvailabilityRequest(
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        guest_count=guest_count,
    )

    result = restaurant_api.check_availability(request)

    return result.model_dump()


@mcp.tool()
def create_reservation(
    hold_token: str,
    customer_name: str,
    restaurant_id: str,
    reservation_date: str,
    reservation_time: str,
    guest_count: int,
    seating_preference: str = "any",
    customer_phone: str = "",
    customer_email: str = "",
    special_requests: str = "",
) -> dict:
    """Create a confirmed restaurant reservation."""

    request = ReservationCreateRequest(
        hold_token=hold_token,
        customer_name=customer_name,
        customer_phone=customer_phone or None,
        customer_email=customer_email or None,
        restaurant_id=restaurant_id,
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        guest_count=guest_count,
        seating_preference=seating_preference,
        special_requests=special_requests or None,
    )

    result = restaurant_api.create_reservation(request)
    return result.model_dump()


@mcp.tool()
def get_reservation(reservation_id: str) -> dict:
    """Retrieve an existing reservation using its ID."""

    details = restaurant_api.get_reservation(reservation_id)

    if details:
        return {
            "found": True,
            "details": details.model_dump(),
        }

    return {
        "found": False,
        "message": f"No reservation found with ID {reservation_id}.",
    }


@mcp.tool()
def cancel_reservation(reservation_id: str) -> dict:
    """Cancel an existing restaurant reservation."""

    success = restaurant_api.cancel_reservation(reservation_id)

    return {
        "cancelled": success,
        "reservation_id": reservation_id,
    }


@mcp.tool()
def find_alternative_slots(
    reservation_date: str,
    requested_time: str,
    guest_count: int,
    restaurant_id: str = "rest_01",
) -> dict:
    """Find alternative available reservation time slots."""

    alternatives = restaurant_api.get_alternatives(
        restaurant_id=restaurant_id,
        reservation_date=reservation_date,
        requested_time=requested_time,
        guest_count=guest_count,
    )

    return {
        "alternatives": [
            alternative.model_dump()
            for alternative in alternatives
        ]
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
