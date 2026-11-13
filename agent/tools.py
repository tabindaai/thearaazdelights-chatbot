"""
Agent Tools Module.

Exposes native Python functions to Google Gemini.
Each tool validates arguments using Pydantic and Guardrails, interacts with
the colleague's backend client, and synchronizes the session state and memory.
"""

from typing import Optional, Dict, Any
from agent.memory import SessionMemory, ConversationState
from agent.guardrails import Guardrails
from agent.mcp_client import call_mcp_tool
from schemas.reservation import (
    AvailabilityRequest,
    AvailabilityResponse,
    ReservationCreateRequest,
    ReservationResponse,
)
from services.restaurant_api import restaurant_api


class AgentTools:
    """Encapsulates tool implementations bound to a specific session."""

    def __init__(self, session: SessionMemory):
        self.session = session

    def update_reservation_details(
        self,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        date: Optional[str] = None,
        time: Optional[str] = None,
        guest_count: Optional[int] = None,
        special_requests: Optional[str] = None,
        confirmed_by_customer: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Record or update customer information and reservation preferences extracted from conversation.
        Call this whenever the customer shares their name, phone, date, time, guest count, or confirms booking.
        """
        draft = self.session.draft

        if name:
            draft.update_field("customer_name", name.strip())
        if phone:
            draft.update_field("customer_phone", phone.strip())
        if email:
            draft.update_field("customer_email", email.strip())
        if date:
            is_valid, msg = Guardrails.validate_reservation_date(date)
            if not is_valid:
                return {"status": "error", "message": msg}
            draft.update_field("reservation_date", date)
        if time:
            draft.update_field("reservation_time", time.strip())
        if guest_count is not None:
            is_valid, msg = Guardrails.validate_guest_count(guest_count)
            if not is_valid:
                return {"status": "error", "message": msg}
            draft.update_field("guest_count", guest_count)
        if special_requests:
            draft.update_field("special_requests", special_requests.strip())
        if confirmed_by_customer is not None:
            draft.confirmed_by_customer = confirmed_by_customer

        # Check if we are ready for customer confirmation
        if draft.has_required_booking_fields() and self.session.last_availability_result and self.session.last_availability_result.get("available"):
            self.session.set_state(ConversationState.AWAITING_CUSTOMER_CONFIRMATION)
        else:
            self.session.set_state(ConversationState.COLLECTING_DETAILS)

        return {
            "status": "success",
            "message": "Reservation draft updated successfully.",
            "current_draft": draft.model_dump(),
            "missing_fields": draft.missing_fields_for_booking(),
        }

    def check_table_availability(
        self,
        reservation_date: str,
        reservation_time: str,
        guest_count: int,
        force_recheck: bool = False,
            mcp_result: Optional[Dict[str, Any]] = None,

    ) -> Dict[str, Any]:
        """
        Check if tables are available on a specific date, time, and guest count.
        Calls the restaurant backend API (with duplicate check caching).
        """
        # 1. Validate inputs via Guardrails
        valid_date, date_err = Guardrails.validate_reservation_date(reservation_date)
        if not valid_date:
            return {"available": False, "error": date_err}

        valid_guests, guest_err = Guardrails.validate_guest_count(guest_count)
        if not valid_guests:
            return {"available": False, "error": guest_err}

        # 2. Duplicate Check Caching: Don't call backend multiple times for identical details
        current_params = {
            "date": reservation_date,
            "time": reservation_time,
            "guest_count": guest_count,
        }
        if (
            not force_recheck
            and self.session.last_checked_params == current_params
            and self.session.last_availability_result is not None
        ):
            return self.session.last_availability_result

        # 3. Update Draft
        draft = self.session.draft
        draft.update_field("reservation_date", reservation_date)
        draft.update_field("reservation_time", reservation_time)
        draft.update_field("guest_count", guest_count)

        self.session.set_state(ConversationState.CHECKING_AVAILABILITY)

       # 4. Use MCP result if provided; otherwise use the existing API.
        if mcp_result is not None:
           api_result = AvailabilityResponse.model_validate(mcp_result)
        else:
          req = AvailabilityRequest(
              restaurant_id=draft.restaurant_id,
              reservation_date=reservation_date,
              reservation_time=reservation_time,
              guest_count=guest_count,
          )
          api_result = restaurant_api.check_availability(req)

        # 5. Update session state based on backend response
        if api_result.available:
            draft.hold_token = api_result.hold_token
            avail_result = {
                "available": True,
                "message": api_result.message,
                "hold_token": api_result.hold_token,
            }
            self.session.last_checked_params = current_params
            self.session.last_availability_result = avail_result

            # If customer name is already provided, we are ready for customer confirmation
            if draft.customer_name:
                self.session.set_state(ConversationState.AWAITING_CUSTOMER_CONFIRMATION)
            else:
                self.session.set_state(ConversationState.SLOT_AVAILABLE)

            return avail_result
        else:
            self.session.set_state(ConversationState.SLOT_UNAVAILABLE)
            draft.hold_token = None
            self.session.last_checked_params = current_params
            alternatives_data = [alt.model_dump() for alt in api_result.alternatives]
            unavail_result = {
                "available": False,
                "message": api_result.message,
                "suggested_alternatives": alternatives_data,
            }
            self.session.last_availability_result = unavail_result
            return unavail_result

    def find_alternative_slots(
        self,
        reservation_date: str,
        requested_time: str,
        guest_count: int,
    ) -> Dict[str, Any]:
        """
        Find nearby alternative available slots when the requested slot is booked out.
        """
        self.session.set_state(ConversationState.SUGGESTING_ALTERNATIVES)

        return call_mcp_tool(
            "find_alternative_slots",
            {
                "restaurant_id": self.session.draft.restaurant_id,
                "reservation_date": reservation_date,
                "requested_time": requested_time,
                "guest_count": guest_count,
            },
        )

    
    def create_reservation(
        self,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        special_requests: Optional[str] = None,
        seating_preference="any",
    ) -> Dict[str, Any]:
        """
        Create a confirmed table reservation in the backend database.
        MANDATORY REQUIREMENT: Customer must have explicitly confirmed the booking details first.
        """
        # Duplicate booking guard: prevent creating multiple reservations if already booked
        if (
            self.session.state == ConversationState.RESERVATION_CONFIRMED
            and self.session.last_confirmed_reservation_id
        ):
            return {
                "status": "confirmed",
                "reservation_id": self.session.last_confirmed_reservation_id,
                "message": f"Your reservation is already confirmed (ID: {self.session.last_confirmed_reservation_id}). Duplicate booking was prevented.",
            }

        draft = self.session.draft
        if customer_name:
            draft.update_field("customer_name", customer_name)
        if customer_phone:
            draft.update_field("customer_phone", customer_phone)
        if special_requests:
            draft.update_field("special_requests", special_requests)

        # Enforce Tool Execution Guardrail Gate
        can_book, reason = Guardrails.can_execute_booking(draft, self.session.state)
        if not can_book:
            return {
                "status": "failed",
                "error": reason,
                "hint": "Ask the customer for explicit confirmation or missing details first.",
            }

        self.session.set_state(ConversationState.CREATING_RESERVATION)

        # Prepare backend booking payload (phone is optional)
        req = ReservationCreateRequest(
            hold_token=draft.hold_token,
            customer_name=draft.customer_name,
            customer_phone=draft.customer_phone,
            customer_email=draft.customer_email,
            restaurant_id=draft.restaurant_id,
            reservation_date=draft.reservation_date,
            reservation_time=draft.reservation_time,
            guest_count=draft.guest_count,
            special_requests=draft.special_requests,
            seating_preference="any",        )

        result = ReservationResponse.model_validate(
            call_mcp_tool(
                "create_reservation",
                req.model_dump(exclude_none=True),
            )
        )

        if result.status == "confirmed":
            self.session.set_state(ConversationState.RESERVATION_CONFIRMED)
            self.session.last_confirmed_reservation_id = result.reservation_id
            return {
                "status": "confirmed",
                "reservation_id": result.reservation_id,
                "details": result.details.model_dump() if result.details else {},
                "message": result.message,
            }
        else:
            self.session.set_state(ConversationState.RESERVATION_FAILED)
            return {
                "status": "failed",
                "message": result.message,
            }

    def get_reservation_details(self, reservation_id: str) -> Dict[str, Any]:
        """Look up an existing reservation through MCP."""
        return call_mcp_tool(
            "get_reservation",
            {"reservation_id": reservation_id},
        )       
    def cancel_existing_reservation(self, reservation_id: str) -> Dict[str, Any]:
        """Cancel an existing reservation through MCP."""
        self.session.set_state(ConversationState.CANCELLING_RESERVATION)
        result = call_mcp_tool(
            "cancel_reservation",
            {"reservation_id": reservation_id},
        )

        if result.get("cancelled"):
            return {
                "status": "success",
                "message": f"Reservation {reservation_id} has been cancelled.",
            }

        return {
            "status": "failed",
            "message": f"Could not cancel reservation {reservation_id}.",
        }