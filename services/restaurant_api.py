
"""
Restaurant Backend API Integration Client.

Supports three backend modes:
1. PostgreSQL persistence
2. Colleague's external HTTP API
3. In-memory mock backend

The MCP server calls this service. Database access stays behind
the restaurant backend service rather than the chatbot layer.
"""

import logging
import os
import re
import secrets
import threading

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from sqlalchemy import func, text

from schemas.reservation import (
    AvailabilityRequest,
    AvailabilityResponse,
    AlternativeSlot,
    ReservationCreateRequest,
    ReservationResponse,
    ReservationDetails,
)

from services.db import SessionLocal, is_database_configured
from services.models import Reservation


load_dotenv()

logger = logging.getLogger("restaurant_api")
logger.setLevel(logging.INFO)


# ============================================================================
# CONFIGURATION
# ============================================================================

USE_MOCK = (
    os.getenv("USE_MOCK_BACKEND", "true").lower()
    in ("true", "1", "yes")
)

BASE_URL = os.getenv(
    "RESTAURANT_API_BASE_URL",
    "http://localhost:8003",
).rstrip("/")

TIMEOUT_SECONDS = float(
    os.getenv("RESTAURANT_API_TIMEOUT_SECONDS", "10.0")
)


class RestaurantAPIClient:
    """Client for mock, PostgreSQL, and external HTTP backends."""

    MOCK_MAX_TABLES_PER_SLOT = 2
    MOCK_MAX_GUESTS_PER_SLOT = 20

    # Temporary availability holds expire after 10 minutes.
    HOLD_DURATION_MINUTES = 10

    # Shared PostgreSQL advisory lock for reservation writes.
    # This serializes booking and update capacity checks.
    DATABASE_LOCK_KEY = 73519021

    ALTERNATIVE_TIMES = ("19:30", "21:45")

    def __init__(
        self,
        base_url: str = BASE_URL,
        use_mock: bool = USE_MOCK,
    ):
        self.base_url = base_url
        self.use_mock = use_mock

        self.use_database = (
            not self.use_mock
            and is_database_configured()
        )

        # Existing mock storage.
        self._mock_db_reservations: List[dict] = []

        # Temporary PostgreSQL availability holds.
        # Holds are intentionally temporary and kept in process memory.
        self._db_holds: dict = {}
        self._holds_lock = threading.Lock()

        if self.use_mock:
            logger.info("Restaurant backend mode: MOCK")
        elif self.use_database:
            logger.info("Restaurant backend mode: POSTGRESQL")
        else:
            logger.info("Restaurant backend mode: HTTP")

    # ========================================================================
    # COMMON HELPERS
    # ========================================================================

    @staticmethod
    def _parse_date(value: str) -> date:
        if isinstance(value, date):
            return value
        val = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
        return date.fromisoformat(val)

    @staticmethod
    def _parse_time(value: str) -> time:
        if isinstance(value, time):
            return value
        val = str(value).strip().lower().rstrip("'.")
        # Standard ISO format (HH:MM or HH:MM:SS)
        try:
            return time.fromisoformat(val)
        except ValueError:
            pass
        # 12-hour and 24-hour strptime formats
        for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(val.upper(), fmt).time()
            except ValueError:
                pass
        # Regex matching for patterns like "1pm", "3:30pm", "12am", "6pm"
        m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", val, re.IGNORECASE)
        if m:
            hr = int(m.group(1))
            mn = int(m.group(2) or 0)
            ampm = m.group(3).lower()
            if ampm == "pm" and hr < 12:
                hr += 12
            elif ampm == "am" and hr == 12:
                hr = 0
            return time(hr, mn)
        # Standalone hour integer (e.g. "12", "13", "18")
        if val.isdigit():
            hr = int(val)
            if 0 <= hr <= 23:
                return time(hr, 0)
        raise ValueError(f"Invalid time format '{value}'. Expected HH:MM or 12-hour format.")

    @staticmethod
    def _format_time(value: time) -> str:
        return value.strftime("%H:%M")

    @staticmethod
    def _to_details(booking: Reservation) -> ReservationDetails:
        """Convert a SQLAlchemy reservation into a Pydantic response."""

        return ReservationDetails(
            reservation_id=booking.id,
            customer_name=booking.customer_name,
            customer_phone=booking.customer_phone,
            customer_email=booking.customer_email,
            restaurant_id=booking.restaurant_id,
            reservation_date=booking.reservation_date.isoformat(),
            reservation_time=booking.reservation_time.strftime("%H:%M"),
            guest_count=booking.guest_count,
            seating_preference=booking.seating_preference,
            special_requests=booking.special_requests,
            table_number=booking.table_number,
            status=booking.status,
            hold_token=booking.hold_token,
            calendar_event_id=getattr(booking, "calendar_event_id", None),
            created_at=booking.created_at,
            updated_at=booking.updated_at,
        )

    @staticmethod
    def _lock_database(session) -> None:
        """
        Serialize reservation writes.

        PostgreSQL releases this transaction-level advisory lock
        automatically when the transaction finishes.
        """

        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": RestaurantAPIClient.DATABASE_LOCK_KEY},
        )

    def _database_slot_capacity(
        self,
        session,
        restaurant_id: str,
        reservation_date: date,
        reservation_time: time,
        guest_count: int,
        exclude_reservation_id: Optional[str] = None,
    ) -> tuple[bool, int, int]:
        """Check remaining capacity for a reservation slot."""

        query = session.query(
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.guest_count), 0),
        ).filter(
            Reservation.restaurant_id == restaurant_id,
            Reservation.reservation_date == reservation_date,
            Reservation.reservation_time == reservation_time,
            Reservation.status == "confirmed",
        )

        if exclude_reservation_id:
            query = query.filter(
                Reservation.id != exclude_reservation_id
            )

        booked_tables, booked_guests = query.one()

        available = (
            booked_tables < self.MOCK_MAX_TABLES_PER_SLOT
            and (
                booked_guests + guest_count
                <= self.MOCK_MAX_GUESTS_PER_SLOT
            )
        )

        return available, booked_tables, booked_guests

    # ========================================================================
    # 1. CHECK AVAILABILITY
    # ========================================================================

    def check_availability(
        self,
        request: AvailabilityRequest,
    ) -> AvailabilityResponse:
        """Check whether a reservation slot is available."""

        if self.use_mock:
            return self._mock_check_availability(request)

        if self.use_database:
            return self._database_check_availability(request)

        url = f"{self.base_url}/availability"

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(
                    url,
                    json=request.model_dump(),
                )
                response.raise_for_status()

                return AvailabilityResponse(**response.json())

        except httpx.HTTPError as exc:
            logger.error("Availability API error: %s", exc)

            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="Failed to verify availability with backend service.",
                alternatives=[],
            )

    async def check_availability_async(
        self,
        request: AvailabilityRequest,
    ) -> AvailabilityResponse:
        """Asynchronous availability check."""

        if self.use_mock or self.use_database:
            return self.check_availability(request)

        url = f"{self.base_url}/availability"

        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    url,
                    json=request.model_dump(),
                )
                response.raise_for_status()

                return AvailabilityResponse(**response.json())

        except httpx.HTTPError as exc:
            logger.error("Availability API error: %s", exc)

            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="Failed to verify availability with backend service.",
                alternatives=[],
            )

    def _database_check_availability(
        self,
        request: AvailabilityRequest,
    ) -> AvailabilityResponse:
        """Check PostgreSQL capacity and create a temporary hold."""

        try:
            requested_date = self._parse_date(
                request.reservation_date
            )
            requested_time = self._parse_time(
                request.reservation_time
            )

            with SessionLocal() as session:
                available, booked_tables, booked_guests = (
                    self._database_slot_capacity(
                        session=session,
                        restaurant_id=request.restaurant_id,
                        reservation_date=requested_date,
                        reservation_time=requested_time,
                        guest_count=request.guest_count,
                    )
                )

            if not available:
                return AvailabilityResponse(
                    available=False,
                    hold_token=None,
                    message=(
                        f"No tables available for "
                        f"{request.reservation_date} at "
                        f"{request.reservation_time}. "
                        f"{booked_tables} tables and "
                        f"{booked_guests} guests are already booked."
                    ),
                    alternatives=self._database_get_alternatives(
                        restaurant_id=request.restaurant_id,
                        reservation_date=request.reservation_date,
                        requested_time=request.reservation_time,
                        guest_count=request.guest_count,
                    ),
                )

            token = secrets.token_urlsafe(24)

            with self._holds_lock:
                self._db_holds[token] = {
                    "restaurant_id": request.restaurant_id,
                    "reservation_date": request.reservation_date,
                    "reservation_time": request.reservation_time,
                    "guest_count": request.guest_count,
                    "expires_at": (
                        datetime.now(timezone.utc)
                        + timedelta(
                            minutes=self.HOLD_DURATION_MINUTES
                        )
                    ),
                }

            return AvailabilityResponse(
                available=True,
                hold_token=token,
                message=(
                    f"Table available for {request.guest_count} guests "
                    f"on {request.reservation_date} at "
                    f"{request.reservation_time}. "
                    f"Your temporary hold expires in "
                    f"{self.HOLD_DURATION_MINUTES} minutes."
                ),
                alternatives=[],
            )

        except (ValueError, TypeError) as exc:
            logger.error("Invalid availability request: %s", exc)

            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="Invalid reservation date or time.",
                alternatives=[],
            )

        except Exception:
            logger.exception("PostgreSQL availability check failed.")

            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="Unable to check availability right now.",
                alternatives=[],
            )

    # ========================================================================
    # 2. GET ALTERNATIVE SLOTS
    # ========================================================================

    def get_alternatives(
        self,
        restaurant_id: str,
        reservation_date: str,
        requested_time: str,
        guest_count: int,
    ) -> List[AlternativeSlot]:
        """Find alternative available reservation times."""

        if self.use_mock:
            return self._mock_get_alternatives(
                reservation_date,
                requested_time,
            )

        if self.use_database:
            return self._database_get_alternatives(
                restaurant_id,
                reservation_date,
                requested_time,
                guest_count,
            )

        url = f"{self.base_url}/alternatives"

        payload = {
            "restaurant_id": restaurant_id,
            "reservation_date": reservation_date,
            "requested_time": requested_time,
            "guest_count": guest_count,
        }

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()

                data = response.json()

                return [
                    AlternativeSlot(**slot)
                    for slot in data.get("alternatives", [])
                ]

        except httpx.HTTPError as exc:
            logger.error("Alternative slots API error: %s", exc)
            return []

    def _database_get_alternatives(
        self,
        restaurant_id: str,
        reservation_date: str,
        requested_time: str,
        guest_count: int,
    ) -> List[AlternativeSlot]:
        """Return candidate alternative times that have capacity."""

        alternatives = []

        try:
            parsed_date = self._parse_date(reservation_date)
            requested = self._parse_time(requested_time)

            with SessionLocal() as session:
                for candidate in self.ALTERNATIVE_TIMES:
                    candidate_time = self._parse_time(candidate)

                    if candidate_time == requested:
                        continue

                    available, _, _ = self._database_slot_capacity(
                        session=session,
                        restaurant_id=restaurant_id,
                        reservation_date=parsed_date,
                        reservation_time=candidate_time,
                        guest_count=guest_count,
                    )

                    if available:
                        alternatives.append(
                            AlternativeSlot(
                                date=reservation_date,
                                time=candidate,
                            )
                        )

        except Exception:
            logger.exception(
                "Failed to find PostgreSQL alternative slots."
            )

        return alternatives

    # ========================================================================
    # 3. CREATE CONFIRMED RESERVATION
    # ========================================================================

    def create_reservation(
        self,
        request: ReservationCreateRequest,
    ) -> ReservationResponse:
        """Create and persist a confirmed reservation."""

        if self.use_mock:
            return self._mock_create_reservation(request)

        if self.use_database:
            return self._database_create_reservation(request)

        url = f"{self.base_url}/reservations"

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(
                    url,
                    json=request.model_dump(),
                )
                response.raise_for_status()

                return ReservationResponse(**response.json())

        except httpx.HTTPError as exc:
            logger.error("Reservation creation API error: %s", exc)

            return ReservationResponse(
                status="failed",
                reservation_id=None,
                details=None,
                message="Backend reservation service error. Please try again later.",
            )

    def _database_create_reservation(
        self,
        request: ReservationCreateRequest,
    ) -> ReservationResponse:
        """Validate a temporary hold and save a reservation in PostgreSQL."""

        try:
            requested_date = self._parse_date(
                request.reservation_date
            )
            requested_time = self._parse_time(
                request.reservation_time
            )

            with self._holds_lock:
                hold = self._db_holds.get(request.hold_token)

                if not hold:
                    return ReservationResponse(
                        status="failed",
                        message=(
                            "Invalid or expired availability hold. "
                            "Please check availability again."
                        ),
                    )

                if hold["expires_at"] <= datetime.now(timezone.utc):
                    self._db_holds.pop(request.hold_token, None)

                    return ReservationResponse(
                        status="failed",
                        message="Your availability hold has expired. Please check again.",
                    )

                expected = {
                    "restaurant_id": request.restaurant_id,
                    "reservation_date": request.reservation_date,
                    "reservation_time": request.reservation_time,
                    "guest_count": request.guest_count,
                }

                if any(
                    hold[key] != value
                    for key, value in expected.items()
                ):
                    return ReservationResponse(
                        status="failed",
                        message=(
                            "Reservation details do not match the "
                            "availability check. Please check again."
                        ),
                    )

            with SessionLocal() as session:
                try:
                    self._lock_database(session)

                    available, booked_tables, booked_guests = (
                        self._database_slot_capacity(
                            session=session,
                            restaurant_id=request.restaurant_id,
                            reservation_date=requested_date,
                            reservation_time=requested_time,
                            guest_count=request.guest_count,
                        )
                    )

                    if not available:
                        session.rollback()

                        with self._holds_lock:
                            self._db_holds.pop(
                                request.hold_token,
                                None,
                            )

                        return ReservationResponse(
                            status="failed",
                            message=(
                                "Sorry, this slot has just become "
                                "unavailable. Please check alternatives."
                            ),
                        )

                    reservation_id = (
                        f"RES-{secrets.token_hex(4).upper()}"
                    )

                    booking = Reservation(
                        id=reservation_id,
                        customer_name=request.customer_name,
                        customer_phone=request.customer_phone,
                        customer_email=request.customer_email,
                        restaurant_id=request.restaurant_id,
                        reservation_date=requested_date,
                        reservation_time=requested_time,
                        guest_count=request.guest_count,
                        seating_preference=request.seating_preference,
                        special_requests=request.special_requests,
                        table_number=booked_tables + 1,
                        status="confirmed",
                        hold_token=request.hold_token,
                    )

                    session.add(booking)
                    session.commit()
                    session.refresh(booking)

                    details = self._to_details(booking)

                except Exception:
                    session.rollback()
                    raise

            with self._holds_lock:
                self._db_holds.pop(request.hold_token, None)

            logger.info(
                "PostgreSQL reservation created: %s",
                reservation_id,
            )

            return ReservationResponse(
                status="confirmed",
                reservation_id=reservation_id,
                details=details,
                message="Reservation confirmed and saved successfully.",
            )

        except (ValueError, TypeError) as exc:
            logger.error("Invalid reservation data: %s", exc)

            return ReservationResponse(
                status="failed",
                message="Invalid reservation date or time.",
            )

        except Exception:
            logger.exception("PostgreSQL reservation creation failed.")

            return ReservationResponse(
                status="failed",
                message="Unable to create your reservation right now.",
            )

    # ========================================================================
    # 4. GET EXISTING RESERVATION
    # ========================================================================

    def get_reservation(
        self,
        reservation_id: str,
    ) -> Optional[ReservationDetails]:
        """Retrieve a reservation by its unique ID."""

        if self.use_mock:
            return self._mock_get_reservation(reservation_id)

        if self.use_database:
            try:
                with SessionLocal() as session:
                    booking = session.get(
                        Reservation,
                        reservation_id,
                    )

                    if booking is None:
                        return None

                    return self._to_details(booking)

            except Exception:
                logger.exception(
                    "PostgreSQL retrieval failed for %s",
                    reservation_id,
                )
                return None

        url = f"{self.base_url}/reservations/{reservation_id}"

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.get(url)

                if response.status_code == 404:
                    return None

                response.raise_for_status()

                return ReservationDetails(**response.json())

        except httpx.HTTPError as exc:
            logger.error("Reservation retrieval API error: %s", exc)
            return None

    # ========================================================================
    # 5. CANCEL RESERVATION
    # ========================================================================

    def cancel_reservation(self, reservation_id: str) -> bool:
        """Cancel an existing reservation."""

        if self.use_mock:
            for booking in self._mock_db_reservations:
                if booking.get("reservation_id") == reservation_id:
                    booking["status"] = "cancelled"

                    self._mock_db_reservations.remove(booking)

                    logger.info(
                        "[MOCK BACKEND] Cancelled %s",
                        reservation_id,
                    )
                    return True

            return False

        if self.use_database:
            try:
                with SessionLocal() as session:
                    self._lock_database(session)

                    booking = session.get(
                        Reservation,
                        reservation_id,
                    )

                    if not booking or booking.status != "confirmed":
                        session.rollback()
                        return False

                    booking.status = "cancelled"

                    session.commit()

                    logger.info(
                        "PostgreSQL reservation cancelled: %s",
                        reservation_id,
                    )
                    return True

            except Exception:
                logger.exception(
                    "PostgreSQL cancellation failed for %s",
                    reservation_id,
                )
                return False

        url = f"{self.base_url}/reservations/{reservation_id}"

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.delete(url)
                return response.status_code in (200, 204)

        except httpx.HTTPError as exc:
            logger.error("Reservation cancellation API error: %s", exc)
            return False

    # ========================================================================
    # 6. UPDATE EXISTING RESERVATION
    # ========================================================================

    def update_reservation(
        self,
        reservation_id: str,
        reservation_date: Optional[str] = None,
        reservation_time: Optional[str] = None,
        guest_count: Optional[int] = None,
        seating_preference: Optional[str] = None,
        special_requests: Optional[str] = None,
    ) -> Optional[ReservationDetails]:
        """Update an existing confirmed reservation."""

        if self.use_mock:
            return self._mock_update_reservation(
                reservation_id,
                reservation_date,
                reservation_time,
                guest_count,
                seating_preference,
                special_requests,
            )

        if self.use_database:
            return self._database_update_reservation(
                reservation_id,
                reservation_date,
                reservation_time,
                guest_count,
                seating_preference,
                special_requests,
            )

        url = f"{self.base_url}/reservations/{reservation_id}"

        payload = {}

        if reservation_date:
            payload["reservation_date"] = reservation_date

        if reservation_time:
            payload["reservation_time"] = reservation_time

        if guest_count:
            payload["guest_count"] = guest_count

        if seating_preference:
            payload["seating_preference"] = seating_preference

        if special_requests:
            payload["special_requests"] = special_requests

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.patch(url, json=payload)

                if response.status_code == 404:
                    return None

                response.raise_for_status()

                return ReservationDetails(**response.json())

        except httpx.HTTPError as exc:
            logger.error("Reservation update API error: %s", exc)
            return None

    def _database_update_reservation(
        self,
        reservation_id: str,
        reservation_date: Optional[str],
        reservation_time: Optional[str],
        guest_count: Optional[int],
        seating_preference: Optional[str],
        special_requests: Optional[str],
    ) -> Optional[ReservationDetails]:
        """Update a PostgreSQL reservation with capacity validation."""

        try:
            with SessionLocal() as session:
                self._lock_database(session)

                booking = session.get(
                    Reservation,
                    reservation_id,
                )

                if not booking or booking.status != "confirmed":
                    session.rollback()
                    return None

                new_date = (
                    self._parse_date(reservation_date)
                    if reservation_date
                    else booking.reservation_date
                )

                new_time = (
                    self._parse_time(reservation_time)
                    if reservation_time
                    else booking.reservation_time
                )

                new_guest_count = (
                    guest_count
                    if guest_count is not None
                    else booking.guest_count
                )

                if not 1 <= new_guest_count <= self.MOCK_MAX_GUESTS_PER_SLOT:
                    session.rollback()
                    return None

                slot_changed = (
                    new_date != booking.reservation_date
                    or new_time != booking.reservation_time
                    or new_guest_count != booking.guest_count
                )

                if slot_changed:
                    available, _, _ = self._database_slot_capacity(
                        session=session,
                        restaurant_id=booking.restaurant_id,
                        reservation_date=new_date,
                        reservation_time=new_time,
                        guest_count=new_guest_count,
                        exclude_reservation_id=reservation_id,
                    )

                    if not available:
                        session.rollback()
                        return None

                booking.reservation_date = new_date
                booking.reservation_time = new_time
                booking.guest_count = new_guest_count

                if seating_preference is not None:
                    booking.seating_preference = seating_preference

                if special_requests is not None:
                    booking.special_requests = special_requests

                session.commit()
                session.refresh(booking)

                logger.info(
                    "PostgreSQL reservation updated: %s",
                    reservation_id,
                )

                return self._to_details(booking)

        except (ValueError, TypeError):
            logger.exception("Invalid reservation update data.")
            return None

        except Exception:
            logger.exception(
                "PostgreSQL reservation update failed: %s",
                reservation_id,
            )
            return None

    # ========================================================================
    # MOCK IMPLEMENTATIONS
    # ========================================================================

    def _mock_check_availability(
        self,
        req: AvailabilityRequest,
    ) -> AvailabilityResponse:
        """Simulate availability checking in mock mode."""

        logger.info(
            "[MOCK BACKEND] Checking %s guests on %s at %s",
            req.guest_count,
            req.reservation_date,
            req.reservation_time,
        )

        if "21:00" in req.reservation_time:
            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="No tables available at this time.",
                alternatives=self._mock_get_alternatives(
                    req.reservation_date,
                    req.reservation_time,
                ),
            )

        matching = [
            booking
            for booking in self._mock_db_reservations
            if booking.get("date") == req.reservation_date
            and booking.get("time") == req.reservation_time
            and booking.get("status") == "confirmed"
        ]

        booked_guests = sum(
            booking.get("guest_count", 0)
            for booking in matching
        )

        if (
            len(matching) >= self.MOCK_MAX_TABLES_PER_SLOT
            or booked_guests + req.guest_count
            > self.MOCK_MAX_GUESTS_PER_SLOT
        ):
            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="This reservation slot is fully booked.",
                alternatives=self._mock_get_alternatives(
                    req.reservation_date,
                    req.reservation_time,
                ),
            )

        return AvailabilityResponse(
            available=True,
            hold_token=(
                f"HOLD-{secrets.token_hex(8).upper()}"
            ),
            message=(
                f"Table available for {req.guest_count} guests "
                f"on {req.reservation_date} at {req.reservation_time}."
            ),
            alternatives=[],
        )

    def _mock_get_alternatives(
        self,
        res_date: str,
        req_time: str,
    ) -> List[AlternativeSlot]:
        """Return the existing mock alternative slots."""

        return [
            AlternativeSlot(date=res_date, time=candidate)
            for candidate in self.ALTERNATIVE_TIMES
            if candidate != req_time
        ]

    def _mock_create_reservation(
        self,
        req: ReservationCreateRequest,
    ) -> ReservationResponse:
        """Create a mock reservation."""

        generated_id = (
            f"RES-{secrets.token_hex(4).upper()}"
        )

        table_number = len(self._mock_db_reservations) + 1

        booking = {
            "reservation_id": generated_id,
            "name": req.customer_name,
            "customer_phone": req.customer_phone,
            "customer_email": req.customer_email,
            "restaurant_id": req.restaurant_id,
            "date": req.reservation_date,
            "time": req.reservation_time,
            "guest_count": req.guest_count,
            "seating_preference": req.seating_preference,
            "special_requests": req.special_requests,
            "table_number": table_number,
            "status": "confirmed",
            "hold_token": req.hold_token,
        }

        self._mock_db_reservations.append(booking)

        details = self._mock_booking_to_details(booking)

        logger.info(
            "[MOCK BACKEND] Created reservation %s",
            generated_id,
        )

        return ReservationResponse(
            status="confirmed",
            reservation_id=generated_id,
            details=details,
            message="Reservation confirmed successfully in mock backend.",
        )

    def _mock_booking_to_details(
        self,
        booking: dict,
    ) -> ReservationDetails:
        """Convert mock booking data into a Pydantic response."""

        return ReservationDetails(
            reservation_id=booking["reservation_id"],
            customer_name=booking["name"],
            customer_phone=booking.get("customer_phone"),
            customer_email=booking.get("customer_email"),
            restaurant_id=booking.get("restaurant_id", "rest_01"),
            reservation_date=booking["date"],
            reservation_time=booking["time"],
            guest_count=booking["guest_count"],
            seating_preference=booking.get("seating_preference"),
            special_requests=booking.get("special_requests"),
            table_number=booking.get("table_number"),
            status=booking.get("status", "confirmed"),
            hold_token=booking.get("hold_token"),
        )

    def _mock_get_reservation(
        self,
        reservation_id: str,
    ) -> Optional[ReservationDetails]:
        """Retrieve a mock reservation."""

        for booking in self._mock_db_reservations:
            if booking["reservation_id"] == reservation_id:
                return self._mock_booking_to_details(booking)

        return None

    def _mock_update_reservation(
        self,
        reservation_id: str,
        reservation_date: Optional[str],
        reservation_time: Optional[str],
        guest_count: Optional[int],
        seating_preference: Optional[str],
        special_requests: Optional[str],
    ) -> Optional[ReservationDetails]:
        """Update a mock reservation."""

        for booking in self._mock_db_reservations:
            if booking["reservation_id"] != reservation_id:
                continue

            if reservation_date:
                booking["date"] = reservation_date

            if reservation_time:
                booking["time"] = reservation_time

            if guest_count is not None:
                if not 1 <= guest_count <= self.MOCK_MAX_GUESTS_PER_SLOT:
                    return None
                booking["guest_count"] = guest_count

            if seating_preference is not None:
                booking["seating_preference"] = seating_preference

            if special_requests is not None:
                booking["special_requests"] = special_requests

            logger.info(
                "[MOCK BACKEND] Updated reservation %s",
                reservation_id,
            )

            return self._mock_booking_to_details(booking)

        return None


# ============================================================================
# GLOBAL CLIENT INSTANCE
# ============================================================================

restaurant_api = RestaurantAPIClient()
