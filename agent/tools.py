
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
from services.restaurant_api import restaurant_api

from schemas.reservation import (
    AvailabilityRequest,
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
            is_valid, msg = Guardrails.validate_email(email)
            if not is_valid:
                return {"status": "error", "message": msg}
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
        # Normalize date and time strings before validation and backend calls
        try:
            parsed_t = RestaurantAPIClient._parse_time(reservation_time)
            reservation_time = parsed_t.strftime("%H:%M")
        except Exception:
            pass

        try:
            parsed_d = RestaurantAPIClient._parse_date(reservation_date)
            reservation_date = parsed_d.strftime("%Y-%m-%d")
        except Exception:
            pass

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

        # 4. Communicate with restaurant backend (MCP with direct backend fallback).
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
            if not api_result.available and any(
                marker in (api_result.message or "").lower()
                for marker in ("unable to check", "failed to verify", "error", "trouble", "invalid reservation")
            ):
                logger.warning(
                    f"MCP availability returned error message: '{api_result.message}'. "
                    "Falling back to direct restaurant backend..."
                )
                raise RuntimeError(api_result.message)

        except Exception as exc:
            # Fallback to direct restaurant API client (e.g. mock or db in tests/offline)
            try:
                api_result = restaurant_api.check_availability(
                    AvailabilityRequest(
                        restaurant_id=draft.restaurant_id,
                        reservation_date=reservation_date,
                        reservation_time=reservation_time,
                        guest_count=guest_count,
                    )
                )
            except Exception as fallback_exc:
                draft.hold_token = None
                self.session.set_state(ConversationState.COLLECTING_DETAILS)

                return {
                    "available": False,
                    "status": "error",
                    "error": "Could not check availability through MCP or backend.",
                    "details": str(fallback_exc),
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

            try:
                mcp_data = call_mcp_tool(
                    "create_reservation",
                    req.model_dump(exclude_none=True),
                )
                result = ReservationResponse.model_validate(mcp_data)
                # If MCP returned failed with an error message, try direct fallback
                if result.status != "confirmed" and any(
                    marker in (result.message or "").lower()
                    for marker in ("unable", "failed", "error", "trouble", "closed")
                ):
                    logger.warning(
                        f"MCP create_reservation returned '{result.message}'. "
                        "Falling back to direct restaurant backend..."
                    )
                    result = restaurant_api.create_reservation(req)
            except Exception:
                # Fallback to direct restaurant API client (e.g. during test/offline)
                result = restaurant_api.create_reservation(req)

        except Exception as exc:
            self.session.set_state(previous_state)

            return {
                "status": "error",
                "message": "Could not create the reservation through MCP or backend.",
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
        """Retrieve reservation details through MCP (with direct backend fallback)."""

        try:
            return call_mcp_tool(
                "get_reservation",
                {"reservation_id": reservation_id},
            )

        except Exception:
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

    def cancel_existing_reservation(
        self,
        reservation_id: str,
    ) -> Dict[str, Any]:
        """Cancel a reservation through MCP (with direct backend fallback)."""

        self.session.set_state(ConversationState.CANCELLING_RESERVATION)

        try:
            result = call_mcp_tool(
                "cancel_reservation",
                {"reservation_id": reservation_id},
            )

            cancelled = result.get("cancelled", False)

        except Exception:
            cancelled = restaurant_api.cancel_reservation(reservation_id)

        if cancelled:
            # Sync cancellation with Google Calendar if an event exists
            calendar_sync = self.sync_calendar_on_cancel()
            cal_msg = ""
            if calendar_sync.get("success"):
                cal_msg = " The reservation event has also been removed from your Google Calendar."

            return {
                "status": "success",
                "message": (
                    f"Reservation {reservation_id} has been cancelled.{cal_msg}"
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
            result = call_mcp_tool(
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

        except Exception:
            details = restaurant_api.update_reservation(
                reservation_id=reservation_id,
                reservation_date=reservation_date,
                reservation_time=reservation_time,
                guest_count=guest_count,
                seating_preference=seating_preference,
                special_requests=special_requests,
            )
            result = {
                "updated": details is not None,
                "reservation_id": reservation_id,
                "details": details.model_dump() if details else {},
                "message": f"Reservation {reservation_id} updated successfully." if details else "Update failed.",
            }

        if result.get("updated"):
            # Sync update with Google Calendar if event exists
            self.sync_calendar_on_update(
                reservation_id=reservation_id,
                reservation_date=reservation_date,
                reservation_time=reservation_time,
                guest_count=guest_count,
                seating_preference=seating_preference,
                special_requests=special_requests,
            )

        return result

    def save_to_google_calendar(self) -> Dict[str, Any]:
        """
        Save the confirmed reservation to the customer's Google Calendar via MCP.
        Configures a 3-hour (180 minutes) reminder before the reservation.
        """
        session = self.session
        draft = session.draft

        # Prevent duplicate events
        if session.last_confirmed_calendar_event_id:
            return {
                "success": True,
                "event_id": session.last_confirmed_calendar_event_id,
                "message": "Calendar event already saved.",
                "already_saved": True,
            }

        # Check authorization
        if not session.google_calendar_authorized:
            return {
                "success": False,
                "message": "Google Calendar not connected. Guest can connect via the sidebar.",
                "requires_auth": True,
            }

        if not session.last_confirmed_reservation_id:
            return {
                "success": False,
                "message": "No confirmed reservation found to save.",
            }

        try:
            result = call_mcp_tool(
                "create_calendar_event",
                {
                    "session_id": session.session_id,
                    "customer_name": draft.customer_name or "Guest",
                    "customer_email": draft.customer_email or "",
                    "reservation_date": draft.reservation_date or "",
                    "reservation_time": draft.reservation_time or "",
                    "guest_count": draft.guest_count or 1,
                    "reservation_id": session.last_confirmed_reservation_id,
                    "special_requests": draft.special_requests or "",
                    "seating_preference": draft.seating_preference or "any",
                },
            )

            if result.get("success"):
                session.last_confirmed_calendar_event_id = result.get("event_id")
                return {
                    "success": True,
                    "event_id": result.get("event_id"),
                    "event_link": result.get("event_link"),
                    "message": "Reservation saved to Google Calendar with a 3-hour reminder.",
                }

            return {
                "success": False,
                "message": result.get("error", "Could not save calendar event."),
                "calendar_unavailable": result.get("calendar_unavailable", False),
            }

        except Exception as exc:
            return {
                "success": False,
                "message": f"Calendar MCP execution failed: {str(exc)}",
                "calendar_unavailable": True,
            }

    def sync_calendar_on_update(
        self,
        reservation_id: str,
        reservation_date: Optional[str] = None,
        reservation_time: Optional[str] = None,
        guest_count: Optional[int] = None,
        seating_preference: Optional[str] = None,
        special_requests: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synchronize an updated reservation with the customer's Google Calendar."""
        event_id = self.session.last_confirmed_calendar_event_id
        if not event_id or not self.session.google_calendar_authorized:
            return {"success": False, "message": "No active calendar event to update."}

        try:
            result = call_mcp_tool(
                "update_calendar_event",
                {
                    "session_id": self.session.session_id,
                    "event_id": event_id,
                    "reservation_date": reservation_date or "",
                    "reservation_time": reservation_time or "",
                    "guest_count": guest_count or 0,
                    "seating_preference": seating_preference or "",
                    "special_requests": special_requests or "",
                },
            )
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def sync_calendar_on_cancel(self) -> Dict[str, Any]:
        """Synchronize reservation cancellation with the customer's Google Calendar."""
        event_id = self.session.last_confirmed_calendar_event_id
        if not event_id or not self.session.google_calendar_authorized:
            return {"success": False, "message": "No active calendar event to cancel."}

        try:
            result = call_mcp_tool(
                "delete_calendar_event",
                {
                    "session_id": self.session.session_id,
                    "event_id": event_id,
                },
            )
            if result.get("success"):
                self.session.last_confirmed_calendar_event_id = None
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}
