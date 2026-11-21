
"""
Data validation models for restaurant reservation operations.
"""

from datetime import date, time, datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator


class CustomerInfo(BaseModel):
    """Customer profile and contact details."""

    name: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)


class AlternativeSlot(BaseModel):
    """An alternative available reservation slot."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    time: str = Field(description="Time in HH:MM format")


class AvailabilityRequest(BaseModel):
    """Request to check table availability."""

    restaurant_id: str = "rest_01"
    reservation_date: str
    reservation_time: str
    guest_count: int = Field(gt=0, le=20)

    @field_validator("guest_count")
    @classmethod
    def validate_guest_count(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("Guest count must be between 1 and 20.")
        return value


class AvailabilityResponse(BaseModel):
    """Response from an availability check."""

    available: bool
    hold_token: Optional[str] = None
    message: str
    alternatives: List[AlternativeSlot] = Field(default_factory=list)


class ReservationCreateRequest(BaseModel):
    """Request to create a confirmed reservation."""

    hold_token: str = Field(min_length=1)
    customer_name: str = Field(min_length=2)
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    restaurant_id: str = "rest_01"
    reservation_date: str
    reservation_time: str
    guest_count: int = Field(gt=0, le=20)
    special_requests: Optional[str] = None
    seating_preference: Optional[str] = "any"


class ReservationDetails(BaseModel):
    """Structured details of a reservation."""

    reservation_id: str
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    restaurant_id: str
    reservation_date: str
    reservation_time: str
    guest_count: int
    seating_preference: Optional[str] = None
    special_requests: Optional[str] = None
    table_number: Optional[int] = None
    status: str = "confirmed"
    hold_token: Optional[str] = None
    customer_id: Optional[str] = None
    calendar_event_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReservationResponse(BaseModel):
    """Response returned after reservation creation."""

    status: str
    reservation_id: Optional[str] = None
    details: Optional[ReservationDetails] = None
    message: str
