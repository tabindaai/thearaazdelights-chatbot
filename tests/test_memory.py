"""
Unit Tests for Conversation Memory & State Management.

Covers:
- Storing extracted customer details
- Gradual multi-turn detail collection
- Retaining customer name without asking again
- Detail update & invalidating stale confirmation when core parameters change
- Session reset
"""

import pytest
from agent.memory import MemoryManager, SessionMemory, ConversationState, ReservationDraft


def test_session_creation():
    """Verify fresh session initializes with START state and blank draft."""
    mgr = MemoryManager()
    session = mgr.get_or_create("test_session_1")
    assert session.session_id == "test_session_1"
    assert session.state == ConversationState.START
    assert session.draft.customer_name is None
    assert session.draft.is_ready_for_booking() is False


def test_gradual_information_collection():
    """Verify details accumulate over multiple turns without data loss, and phone is optional."""
    draft = ReservationDraft()

    # Turn 1: Customer gives name
    draft.update_field("customer_name", "Tabinda")
    assert draft.customer_name == "Tabinda"
    assert "the reservation date" in draft.missing_fields_for_booking()
    # Phone number is optional, so it is NOT in missing mandatory fields
    assert "your contact phone number" not in draft.missing_fields_for_booking()

    # Turn 2: Customer provides party size and date
    draft.update_field("guest_count", 4)
    draft.update_field("reservation_date", "2026-11-10")
    assert draft.guest_count == 4
    assert draft.reservation_date == "2026-11-10"
    assert draft.customer_name == "Tabinda"  # Still remembered!

    # Turn 3: Customer provides time
    draft.update_field("reservation_time", "19:30")
    assert "your email address" in draft.missing_fields_for_booking()

    # Turn 4: Customer provides email address
    draft.update_field("customer_email", "tabinda@example.com")
    assert len(draft.missing_fields_for_booking()) == 0  # All mandatory fields present without phone!

    # Customer optionally provides phone
    draft.update_field("customer_phone", "+1234567890")
    assert draft.customer_phone == "+1234567890"

    # All fields present, but not confirmed yet
    assert draft.confirmed_by_customer is False
    assert draft.is_ready_for_booking() is False


def test_stale_confirmation_invalidation_on_change():
    """
    CRITICAL SAFETY TEST:
    If a customer previously confirmed a booking, but then changes the time or date,
    the confirmation MUST be invalidated so a stale reservation is not booked.
    """
    draft = ReservationDraft(
        customer_name="Tabinda",
        customer_email="tabinda@example.com",
        customer_phone="+1234567890",
        reservation_date="2026-11-10",
        reservation_time="19:30",
        guest_count=4,
        confirmed_by_customer=True,
        hold_token="HOLD-12345",
    )
    assert draft.is_ready_for_booking() is True

    # Customer changes time to 21:00
    draft.update_field("reservation_time", "21:00")

    # Confirmation and hold token must be wiped!
    assert draft.confirmed_by_customer is False
    assert draft.hold_token is None
    assert draft.is_ready_for_booking() is False


def test_session_reset():
    """Verify session reset returns state to clean slate."""
    mgr = MemoryManager()
    session = mgr.get_or_create("reset_test")
    session.draft.update_field("customer_name", "Fayaz")
    session.set_state(ConversationState.SLOT_AVAILABLE)
    assert session.draft.customer_name == "Fayaz"

    mgr.reset_session("reset_test")
    assert session.draft.customer_name is None
    assert session.state == ConversationState.START

