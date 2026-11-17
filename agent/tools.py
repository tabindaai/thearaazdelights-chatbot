
"""
Agent Tools Module.

Exposes native Python functions to Google Gemini.
Each tool validates arguments using Pydantic and Guardrails,
communicates with the restaurant backend exclusively through MCP,
and synchronizes session state and memory.
"""

from typing import Optional, Dict, Any

from agent.memory import SessionMemory, ConversationState
from agent.guardrails import Guardrails
from agent.mcp_client import call_mcp_tool

from schemas.reservation import (
    AvailabilityResponse,
    ReservationCreateRequest,
    ReservationResponse,
)


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
        seating_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record or update customer information and reservation preferences.
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

        if seating_preference:
            seating_preference = seating_preference.strip().lower()

            if seating_preference not in ("indoor", "outdoor", "any"):
                return {
                    "status": "error",
                    "message": (
                        "Seating preference must be indoor, outdoor, or any."
                    ),
                }

            draft.update_field("seating_preference", seating_preference)

        # Check whether we are ready for customer confirmation.
        if (
            draft.has_required_booking_fields()
            and self.session.last_availability_result
            and self.session.last_availability_result.get("available")
        ):
            self.session.set_state(
                ConversationState.AWAITING_CUSTOMER_CONFIRMATION
            )
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
        seating_preference: Optional[str] = None,
        mcp_result: Optional[Dict[str, Any]] = None,
        force_recheck: bool = False,
    ) -> Dict[str, Any]:
        """
        Check table availability exclusively through the MCP server.
        """

        # 1. Validate inputs.
        valid_date, date_err = Guardrails.validate_reservation_date(
            reservation_date
        )
        if not valid_date:
            return {"available": False, "error": date_err}

        valid_guests, guest_err = Guardrails.validate_guest_count(guest_count)
        if not valid_guests:
            return {"available": False, "error": guest_err}

        # 2. Avoid duplicate availability calls for identical details.
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

        # 3. Update reservation draft.
        draft = self.session.draft
        draft.update_field("reservation_date", reservation_date)
        draft.update_field("reservation_time", reservation_time)
        draft.update_field("guest_count", guest_count)

        if seating_preference:
            draft.update_field(
                "seating_preference",
                seating_preference.strip().lower(),
            )

        self.session.set_state(ConversationState.CHECKING_AVAILABILITY)

        # 4. Communicate exclusively through MCP.
        try:
            if mcp_result is None:
                mcp_result = call_mcp_tool(
                    "check_table_availability",
                    {
                        "reservation_date": reservation_date,
                        "reservation_time": reservation_time,
                        "guest_count": guest_count,
                    },
                )

            api_result = AvailabilityResponse.model_validate(mcp_result)

        except Exception as exc:
            draft.hold_token = None
            self.session.set_state(ConversationState.COLLECTING_DETAILS)

            return {
                "available": False,
                "status": "error",
                "error": "Could not check availability through the MCP server.",
                "details": str(exc),
            }

        # 5. Update session state using the MCP response.
        if api_result.available:
            draft.hold_token = api_result.hold_token

            avail_result = {
                "available": True,
                "message": api_result.message,
                "hold_token": api_result.hold_token,
            }

            self.session.last_checked_params = current_params
            self.session.last_availability_result = avail_result

            if draft.customer_name:
                self.session.set_state(
                    ConversationState.AWAITING_CUSTOMER_CONFIRMATION
                )
            else:
                self.session.set_state(ConversationState.SLOT_AVAILABLE)

            return avail_result

        self.session.set_state(ConversationState.SLOT_UNAVAILABLE)
        draft.hold_token = None

        alternatives_data = [
            alt.model_dump() for alt in api_result.alternatives
        ]

        unavail_result = {
            "available": False,
            "message": api_result.message,
            "suggested_alternatives": alternatives_data,
        }

        self.session.last_checked_params = current_params
        self.session.last_availability_result = unavail_result

        return unavail_result

    def find_alternative_slots(
        self,
        reservation_date: str,
        requested_time: str,
        guest_count: int,
    ) -> Dict[str, Any]:
        """Find alternative available slots through MCP."""

        self.session.set_state(ConversationState.SUGGESTING_ALTERNATIVES)

        try:
            return call_mcp_tool(
                "find_alternative_slots",
                {
                    "restaurant_id": self.session.draft.restaurant_id,
                    "reservation_date": reservation_date,
                    "requested_time": requested_time,
                    "guest_count": guest_count,
                },
            )

        except Exception as exc:
            return {
                "status": "error",
                "message": "Could not retrieve alternative slots through MCP.",
                "details": str(exc),
            }

    def create_reservation(
        self,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        special_requests: Optional[str] = None,
        seating_preference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a confirmed reservation through MCP.

        The customer must explicitly confirm the booking details first.
        """

        # Prevent duplicate bookings.
        if (
            self.session.state == ConversationState.RESERVATION_CONFIRMED
            and self.session.last_confirmed_reservation_id
        ):
            return {
                "status": "confirmed",
                "reservation_id": self.session.last_confirmed_reservation_id,
                "message": (
                    "Your reservation is already confirmed "
                    f"(ID: {self.session.last_confirmed_reservation_id}). "
                    "Duplicate booking was prevented."
                ),
            }

        draft = self.session.draft

        if customer_name:
            draft.update_field("customer_name", customer_name.strip())

        if customer_phone:
            draft.update_field("customer_phone", customer_phone.strip())

        if special_requests:
            draft.update_field("special_requests", special_requests.strip())

        # Enforce booking confirmation guardrails.
        can_book, reason = Guardrails.can_execute_booking(
            draft,
            self.session.state,
        )

        if not can_book:
            return {
                "status": "failed",
                "error": reason,
                "hint": (
                    "Ask the customer for explicit confirmation "
                    "or missing details first."
                ),
            }

        previous_state = self.session.state
        self.session.set_state(ConversationState.CREATING_RESERVATION)

        # Prepare booking payload. Phone number is optional.
        try:
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
                seating_preference=(
                    seating_preference
                    or draft.seating_preference
                    or "any"
                ),
            )

            mcp_data = call_mcp_tool(
                "create_reservation",
                req.model_dump(exclude_none=True),
            )

            result = ReservationResponse.model_validate(mcp_data)

        except Exception as exc:
            self.session.set_state(previous_state)

            return {
                "status": "error",
                "message": "Could not create the reservation through MCP.",
                "details": str(exc),
            }

        if result.status == "confirmed":
            self.session.set_state(
                ConversationState.RESERVATION_CONFIRMED
            )
            self.session.last_confirmed_reservation_id = result.reservation_id

            return {
                "status": "confirmed",
                "reservation_id": result.reservation_id,
                "details": (
                    result.details.model_dump()
                    if result.details
                    else {}
                ),
                "message": result.message,
            }

        self.session.set_state(ConversationState.RESERVATION_FAILED)

        return {
            "status": "failed",
            "message": result.message,
        }

    def get_reservation_details(
        self,
        reservation_id: str,
    ) -> Dict[str, Any]:
        """Retrieve reservation details exclusively through MCP."""

        try:
            return call_mcp_tool(
                "get_reservation",
                {"reservation_id": reservation_id},
            )

        except Exception as exc:
            return {
                "status": "error",
                "found": False,
                "message": "Could not retrieve the reservation through MCP.",
                "details": str(exc),
            }

    def cancel_existing_reservation(
        self,
        reservation_id: str,
    ) -> Dict[str, Any]:
        """Cancel a reservation exclusively through MCP."""

        self.session.set_state(ConversationState.CANCELLING_RESERVATION)

        try:
            result = call_mcp_tool(
                "cancel_reservation",
                {"reservation_id": reservation_id},
            )

            cancelled = result.get("cancelled", False)

        except Exception as exc:
            return {
                "status": "error",
                "message": "Could not cancel the reservation through MCP.",
                "details": str(exc),
            }

        if cancelled:
            return {
                "status": "success",
                "message": (
                    f"Reservation {reservation_id} has been cancelled."
                ),
            }

        return {
            "status": "failed",
            "message": (
                f"Could not cancel reservation {reservation_id}."
            ),
        }

    def update_confirmed_reservation(
        self,
        reservation_id: str,
        reservation_date: Optional[str] = None,
        reservation_time: Optional[str] = None,
        guest_count: Optional[int] = None,
        seating_preference: Optional[str] = None,
        special_requests: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a confirmed reservation exclusively through MCP."""

        self.session.set_state(ConversationState.MODIFYING_RESERVATION)

        try:
            return call_mcp_tool(
                "update_reservation",
                {
                    "reservation_id": reservation_id,
                    "reservation_date": reservation_date or "",
                    "reservation_time": reservation_time or "",
                    "guest_count": guest_count or 0,
                    "seating_preference": seating_preference or "",
                    "special_requests": special_requests or "",
                },
            )

        except Exception as exc:
            return {
                "status": "error",
                "updated": False,
                "reservation_id": reservation_id,
                "message": "Could not update the reservation through MCP.",
                "details": str(exc),
            }
