"""
Unit Tests for Table Availability and Alternative Slot Proposals.

Covers:
- Checking table availability via backend integration / mock
- Handling booked-out slots
- Returning alternative suggested slots
- Verification that agent does not invent availability
"""

import pytest
from schemas.reservation import AvailabilityRequest
from services.restaurant_api import RestaurantAPIClient
from agent.tools import AgentTools
from agent.memory import SessionMemory, ConversationState


def test_slot_available_flow():
    """Verify standard available time slot returns available=True and hold_token."""
    client = RestaurantAPIClient(use_mock=True)
    req = AvailabilityRequest(
        restaurant_id="rest_01",
        reservation_date="2026-11-10",
        reservation_time="19:00",
        guest_count=4,
        seating_preference="indoor",
    )
    result = client.check_availability(req)
    assert result.available is True
    assert result.hold_token is not None
    assert len(result.alternatives) == 0


def test_slot_unavailable_returns_alternatives():
    """
    Verify that when a slot is full (simulated at 21:00 / 9 PM in mock backend),
    the system reports available=False and returns valid alternative slots.
    """
    client = RestaurantAPIClient(use_mock=True)
    req = AvailabilityRequest(
        restaurant_id="rest_01",
        reservation_date="2026-11-10",
        reservation_time="21:00",
        guest_count=4,
    )
    result = client.check_availability(req)
    assert result.available is False
    assert result.hold_token is None
    assert len(result.alternatives) > 0
    # Verify structure of alternative suggestions
    first_alt = result.alternatives[0]
    assert first_alt.date == "2026-11-10"
    assert first_alt.time in ["19:30", "21:45"]


def test_tool_check_availability_updates_state():
    """Verify tool execution transitions session state from START -> CHECKING -> SLOT_AVAILABLE."""
    from datetime import date, timedelta
    target_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")

    session = SessionMemory(session_id="avail_test")
    tools = AgentTools(session)

    res = tools.check_table_availability(
        reservation_date=target_date,
        reservation_time="18:30",
        guest_count=2,
        seating_preference="outdoor",
        mcp_result={
            "available": True,
            "hold_token": "HOLD-TEST-123",
            "message": "Table available for 2 guests.",
            "alternatives": [],
        },
    )

    assert res["available"] is True
    assert session.state == ConversationState.SLOT_AVAILABLE
    assert session.draft.reservation_date == target_date
    assert session.draft.guest_count == 2
    assert session.draft.seating_preference == "outdoor"


def test_capacity_limit_makes_slot_unavailable():
    """
    Verify capacity tracking:
    If Tabinda books the full capacity (20 guests) at 16:00,
    John requesting the same slot receives available=False and alternative suggestions.
    """
    client = RestaurantAPIClient(use_mock=True)

    # 1. Tabinda books table for 20 guests at 16:00
    from schemas.reservation import ReservationCreateRequest
    booking_req = ReservationCreateRequest(
        customer_name="Tabinda",
        customer_email="tabinda@example.com",
        reservation_date="2026-11-15",
        reservation_time="16:00",
        guest_count=20,
        hold_token="HOLD-TABINDA-20",
    )
    booked = client.create_reservation(booking_req)
    assert booked.status == "confirmed"

    # 2. John asks for a table at the exact same date and time (16:00)
    check_req = AvailabilityRequest(
        restaurant_id="rest_01",
        reservation_date="2026-11-15",
        reservation_time="16:00",
        guest_count=4,
    )
    john_check = client.check_availability(check_req)

    # 3. Should now be unavailable because 20 seats are already booked!
    assert john_check.available is False
    assert "fully booked" in john_check.message
    assert len(john_check.alternatives) > 0

