"""
Conversation Memory & State Management.

Maintains conversation history, extracted reservation drafts, and the finite
state machine (FSM) across turns for each user session.
Designed to be in-memory for the MVP, with an interface ready to be backed
by persistent databases or colleague APIs later.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ConversationState(str, Enum):
    """Finite State Machine states representing the reservation conversation lifecycle."""
    START = "START"
    COLLECTING_DETAILS = "COLLECTING_DETAILS"
    READY_TO_CHECK = "READY_TO_CHECK"
    CHECKING_AVAILABILITY = "CHECKING_AVAILABILITY"
    SLOT_AVAILABLE = "SLOT_AVAILABLE"
    SLOT_UNAVAILABLE = "SLOT_UNAVAILABLE"
    SUGGESTING_ALTERNATIVES = "SUGGESTING_ALTERNATIVES"
    AWAITING_CUSTOMER_CONFIRMATION = "AWAITING_CUSTOMER_CONFIRMATION"
    CREATING_RESERVATION = "CREATING_RESERVATION"
    RESERVATION_CONFIRMED = "RESERVATION_CONFIRMED"
    RESERVATION_FAILED = "RESERVATION_FAILED"
    MODIFYING_RESERVATION = "MODIFYING_RESERVATION"
    CANCELLING_RESERVATION = "CANCELLING_RESERVATION"


class ReservationDraft(BaseModel):
    """Holds accumulated reservation details extracted across conversation turns."""
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    restaurant_id: str = "rest_01"
    reservation_date: Optional[str] = None       # Format: YYYY-MM-DD
    reservation_time: Optional[str] = None       # Format: HH:MM
    guest_count: Optional[int] = None
    special_requests: Optional[str] = None
    hold_token: Optional[str] = None
    confirmed_by_customer: bool = False

    def is_ready_for_availability_check(self) -> bool:
        """Determines if enough information exists to query table availability."""
        return bool(self.reservation_date and self.reservation_time and self.guest_count)

    def has_required_booking_fields(self) -> bool:
        """Determines if mandatory booking fields (name, date, time, guests) are present. Phone is optional."""
        return bool(
            self.customer_name
            and self.reservation_date
            and self.reservation_time
            and self.guest_count
        )

    def is_ready_for_booking(self) -> bool:
        """Determines if all mandatory fields (phone is optional) and explicit confirmation are present."""
        return bool(self.has_required_booking_fields() and self.confirmed_by_customer)

    def missing_fields_for_booking(self) -> List[str]:
        """Returns human-readable list of mandatory information still required from customer."""
        missing = []
        if not self.customer_name:
            missing.append("your name")
        if not self.reservation_date:
            missing.append("the reservation date")
        if not self.reservation_time:
            missing.append("the preferred time")
        if not self.guest_count:
            missing.append("the number of guests")
        return missing

    def update_field(self, field: str, value: Any) -> bool:
        """
        Updates a specific field if the new value is non-empty.
        Crucial safety: If critical details (date, time, guests) change,
        invalidates old confirmation and hold tokens to prevent stale bookings.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            return False

        if hasattr(self, field):
            current_val = getattr(self, field)
            if current_val != value:
                setattr(self, field, value)
                # Invalidate previous confirmations if core booking criteria changed
                if field in ("reservation_date", "reservation_time", "guest_count"):
                    self.confirmed_by_customer = False
                    self.hold_token = None
                return True
        return False


class SessionMemory:
    """Encapsulates all session-specific context, history, and current state."""

    def __init__(self, session_id: str):
        self.session_id: str = session_id
        self.state: ConversationState = ConversationState.START
        self.draft: ReservationDraft = ReservationDraft()
        self.history: List[Dict[str, Any]] = []
        self.last_availability_result: Optional[Dict[str, Any]] = None
        self.last_checked_params: Optional[Dict[str, Any]] = None
        self.last_confirmed_reservation_id: Optional[str] = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = datetime.now(timezone.utc)

    def add_user_message(self, text: str) -> None:
        """Record customer message into session history."""
        self.history.append({"role": "user", "parts": [{"text": text}]})
        self.updated_at = datetime.now(timezone.utc)

    def add_model_message(self, text: str) -> None:
        """Record model response into session history."""
        self.history.append({"role": "model", "parts": [{"text": text}]})
        self.updated_at = datetime.now(timezone.utc)

    def set_state(self, new_state: ConversationState) -> None:
        """Transition conversation state."""
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)

    def invalidate_availability(self) -> None:
        """Invalidates cached availability and hold tokens when booking criteria change."""
        self.last_checked_params = None
        self.last_availability_result = None
        self.draft.hold_token = None
        self.draft.confirmed_by_customer = False

    def reset(self) -> None:
        """Clear conversation context and draft to start fresh."""
        self.state = ConversationState.START
        self.draft = ReservationDraft()
        self.history = []
        self.last_availability_result = None
        self.last_checked_params = None
        self.last_confirmed_reservation_id = None
        self.updated_at = datetime.now(timezone.utc)


class MemoryManager:
    """
    Manages in-memory storage for active sessions.
    Provides session retrieval, creation, and garbage collection hooks.
    """

    def __init__(self):
        self._sessions: Dict[str, SessionMemory] = {}

    def get_or_create(self, session_id: str) -> SessionMemory:
        """Retrieve existing session or create a fresh one."""
        if not session_id or not session_id.strip():
            session_id = "default_session"
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionMemory(session_id=session_id)
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> bool:
        """Reset a specific session."""
        if session_id in self._sessions:
            self._sessions[session_id].reset()
            return True
        return False

    def session_exists(self, session_id: str) -> bool:
        return session_id in self._sessions


# Global singleton instance of memory manager
memory_manager = MemoryManager()
