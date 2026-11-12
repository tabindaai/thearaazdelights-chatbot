"""
Restaurant Backend API Integration Client.

Handles all external HTTP communication with your colleague's restaurant & database APIs.
Contains:
1. Configurable base URL & timeouts via environment variables.
2. Async HTTP communication via HTTPX.
3. Built-in MOCK implementation (USE_MOCK_BACKEND=True) so you can test immediately
   even before your colleague finishes the live backend.
"""

import os
import logging
from typing import List, Optional
import httpx
from dotenv import load_dotenv

from schemas.reservation import (
    AvailabilityRequest,
    AvailabilityResponse,
    AlternativeSlot,
    ReservationCreateRequest,
    ReservationResponse,
    ReservationDetails,
)

load_dotenv()

logger = logging.getLogger("restaurant_api")
logger.setLevel(logging.INFO)

# ============================================================================
# CONFIGURATION
# ============================================================================
USE_MOCK = os.getenv("USE_MOCK_BACKEND", "true").lower() in ("true", "1", "yes")
BASE_URL = os.getenv("RESTAURANT_API_BASE_URL", "http://localhost:8001").rstrip("/")
TIMEOUT_SECONDS = float(os.getenv("RESTAURANT_API_TIMEOUT_SECONDS", "10.0"))


class RestaurantAPIClient:
    """Async/Sync API Client for colleague's restaurant reservation backend."""

    # Maximum tables / guest capacity per hour slot in mock mode
    MOCK_MAX_TABLES_PER_SLOT = 2
    MOCK_MAX_GUESTS_PER_SLOT = 20

    def __init__(self, base_url: str = BASE_URL, use_mock: bool = USE_MOCK):
        self.base_url = base_url
        self.use_mock = use_mock
        # Simulated database table in memory for local testing
        self._mock_db_reservations: List[dict] = []

    # ------------------------------------------------------------------------
    # 1. CHECK AVAILABILITY
    # ------------------------------------------------------------------------
    def check_availability(self, request: AvailabilityRequest) -> AvailabilityResponse:
        """
        Check if a table is available for the given criteria.
        Calls POST /availability on colleague's backend (or mock).
        """
        if self.use_mock:
            return self._mock_check_availability(request)

        # Real Backend Call
        url = f"{self.base_url}/availability"
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(url, json=request.model_dump())
                response.raise_for_status()
                return AvailabilityResponse(**response.json())
        except httpx.HTTPError as exc:
            logger.error(f"Error calling availability API: {exc}")
            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message="Failed to verify availability with backend service.",
                alternatives=[]
            )

    async def check_availability_async(self, request: AvailabilityRequest) -> AvailabilityResponse:
        """Async variant of availability check."""
        if self.use_mock:
            return self._mock_check_availability(request)

        url = f"{self.base_url}/availability"
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(url, json=request.model_dump())
                response.raise_for_status()
                return AvailabilityResponse(**response.json())
            except httpx.HTTPError as exc:
                logger.error(f"Error calling availability API: {exc}")
                return AvailabilityResponse(
                    available=False,
                    hold_token=None,
                    message="Failed to verify availability with backend service.",
                    alternatives=[]
                )

    # ------------------------------------------------------------------------
    # 2. GET ALTERNATIVE SLOTS
    # ------------------------------------------------------------------------
    def get_alternatives(
        self, restaurant_id: str, reservation_date: str, requested_time: str, guest_count: int
    ) -> List[AlternativeSlot]:
        """Retrieve alternative available time slots."""
        if self.use_mock:
            return self._mock_get_alternatives(reservation_date, requested_time)

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
                return [AlternativeSlot(**slot) for slot in data.get("alternatives", [])]
        except httpx.HTTPError as exc:
            logger.error(f"Error fetching alternative slots: {exc}")
            return []

    # ------------------------------------------------------------------------
    # 3. CREATE CONFIRMED RESERVATION
    # ------------------------------------------------------------------------
    def create_reservation(self, request: ReservationCreateRequest) -> ReservationResponse:
        """Commit and create a confirmed reservation."""
        if self.use_mock:
            return self._mock_create_reservation(request)

        url = f"{self.base_url}/reservations"
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(url, json=request.model_dump())
                response.raise_for_status()
                return ReservationResponse(**response.json())
        except httpx.HTTPError as exc:
            logger.error(f"Error creating reservation: {exc}")
            return ReservationResponse(
                status="failed",
                reservation_id=None,
                details=None,
                message="Backend reservation service error. Please try again later."
            )

    # ------------------------------------------------------------------------
    # 4. GET EXISTING RESERVATION DETAILS
    # ------------------------------------------------------------------------
    def get_reservation(self, reservation_id: str) -> Optional[ReservationDetails]:
        """Retrieve details of an existing reservation by its ID."""
        if self.use_mock:
            return self._mock_get_reservation(reservation_id)

        url = f"{self.base_url}/reservations/{reservation_id}"
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.get(url)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return ReservationDetails(**response.json())
        except httpx.HTTPError as exc:
            logger.error(f"Error fetching reservation {reservation_id}: {exc}")
            return None

    # ------------------------------------------------------------------------
    # 5. CANCEL RESERVATION
    # ------------------------------------------------------------------------
    def cancel_reservation(self, reservation_id: str) -> bool:
        """Cancel an existing reservation."""
        if self.use_mock:
            return True

        url = f"{self.base_url}/reservations/{reservation_id}"
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.delete(url)
                return response.status_code in (200, 204)
        except httpx.HTTPError as exc:
            logger.error(f"Error cancelling reservation {reservation_id}: {exc}")
            return False

    # ========================================================================
    # SIMULATED / MOCK IMPLEMENTATIONS (For development before colleague APIs)
    # ========================================================================
    def _mock_check_availability(self, req: AvailabilityRequest) -> AvailabilityResponse:
        """Simulate realistic backend availability logic with capacity tracking."""
        logger.info(f"[MOCK BACKEND] Checking availability for {req.guest_count} guests on {req.reservation_date} at {req.reservation_time}")
        
        # 1. Hardcoded 21:00 (9 PM) full check to test alternative proposal flow
        if "21:00" in req.reservation_time or "9:00 pm" in req.reservation_time.lower():
            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message=f"No tables available at {req.reservation_time} on {req.reservation_date} for {req.guest_count} guests.",
                alternatives=self._mock_get_alternatives(req.reservation_date, req.reservation_time)
            )

        # 2. Check existing bookings in mock database for the same date & time slot
        matching_bookings = [
            b for b in self._mock_db_reservations
            if b.get("date") == req.reservation_date and b.get("time") == req.reservation_time
        ]
        total_booked_guests = sum(b.get("guest_count", 0) for b in matching_bookings)

        # If slot tables or guest capacity exceeded:
        if (
            len(matching_bookings) >= self.MOCK_MAX_TABLES_PER_SLOT
            or (total_booked_guests + req.guest_count) > self.MOCK_MAX_GUESTS_PER_SLOT
        ):
            logger.info(f"[MOCK BACKEND] Slot {req.reservation_date} {req.reservation_time} is fully booked ({len(matching_bookings)} tables, {total_booked_guests} guests).")
            return AvailabilityResponse(
                available=False,
                hold_token=None,
                message=f"All tables are fully booked for {req.reservation_date} at {req.reservation_time} ({total_booked_guests}/{self.MOCK_MAX_GUESTS_PER_SLOT} seats reserved).",
                alternatives=self._mock_get_alternatives(req.reservation_date, req.reservation_time)
            )

        # Available
        return AvailabilityResponse(
            available=True,
            hold_token=f"HOLD-{abs(hash(req.reservation_date + req.reservation_time + str(req.guest_count))) % 100000}",
            message=f"Table available for {req.guest_count} guests on {req.reservation_date} at {req.reservation_time}.",
            alternatives=[]
        )

    def _mock_get_alternatives(self, res_date: str, req_time: str) -> List[AlternativeSlot]:
        """Simulate returning 2 alternative nearby slots."""
        return [
            AlternativeSlot(date=res_date, time="19:30"),
            AlternativeSlot(date=res_date, time="21:45"),
        ]

    def _mock_create_reservation(self, req: ReservationCreateRequest) -> ReservationResponse:
        """Simulate successful reservation creation and store in mock DB."""
        generated_id = f"RES-{abs(hash(req.customer_name + req.reservation_time + str(len(self._mock_db_reservations)))) % 100000}"
        details = ReservationDetails(
            reservation_id=generated_id,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone or "Not provided",
            restaurant_id=req.restaurant_id,
            reservation_date=req.reservation_date,
            reservation_time=req.reservation_time,
            guest_count=req.guest_count,
            table_number=len(self._mock_db_reservations) + 1,
            status="confirmed"
        )

        # Save to mock database
        self._mock_db_reservations.append({
            "reservation_id": generated_id,
            "name": req.customer_name,
            "date": req.reservation_date,
            "time": req.reservation_time,
            "guest_count": req.guest_count,
        })

        logger.info(f"[MOCK BACKEND] Created reservation {generated_id} for {req.customer_name}. Total reservations in mock DB: {len(self._mock_db_reservations)}")
        return ReservationResponse(
            status="confirmed",
            reservation_id=generated_id,
            details=details,
            message="Reservation confirmed successfully in backend database."
        )

    def _mock_get_reservation(self, reservation_id: str) -> Optional[ReservationDetails]:
        """Simulate fetching an existing reservation."""
        return ReservationDetails(
            reservation_id=reservation_id,
            customer_name="Tabinda",
            customer_phone="+1234567890",
            restaurant_id="rest_01",
            reservation_date="2026-11-07",
            reservation_time="20:00",
            guest_count=4,
            table_number=12,
            status="confirmed"
        )


# Global singleton instance for easy import across modules
restaurant_api = RestaurantAPIClient()

