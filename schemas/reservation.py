"""
Data validation models for restaurant reservation operations.

Defines Pydantic schemas for:
- Customer contact details
- Table availability checks
- Alternative time slot proposals
- Reservation creation, retrieval, and cancellation
"""

from datetime import date, time
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class CustomerInfo(BaseModel):
    """Customer profile and contact details."""
    name: Optional[str] = Field(default=None, description="Customer's full name")
    phone: Optional[str] = Field(default=None, description="Customer's contact phone number")
    email: Optional[str] = Field(default=None, description="Customer's email address")


class AlternativeSlot(BaseModel):
    """An alternative available reservation slot suggested by the backend."""
    date: str = Field(description="Date of the alternative slot (YYYY-MM-DD)")
    time: str = Field(description="Time of the alternative slot (HH:MM in 24hr format)")


class AvailabilityRequest(BaseModel):
    """Payload to check table availability via colleague's API."""
    restaurant_id: str = Field(default="rest_01", description="Restaurant unique identifier")
    reservation_date: str = Field(description="Date in YYYY-MM-DD format")
    reservation_time: str = Field(description="Time in HH:MM format (24-hour clock)")
    guest_count: int = Field(gt=0, le=20, description="Party size (between 1 and 20)")


    @field_validator("guest_count")
    @classmethod
    def validate_guest_count(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("Guest count must be between 1 and 20.")
        return v


class AvailabilityResponse(BaseModel):
    """Response returned from availability check."""
    available: bool = Field(description="Whether a table is available for the requested slot")
    hold_token: Optional[str] = Field(default=None, description="Temporary reservation lock token from backend")
    message: str = Field(description="Human-readable status message from backend")
    alternatives: List[AlternativeSlot] = Field(default_factory=list, description="Alternative slots if requested is full")


class ReservationCreateRequest(BaseModel):
    """Payload sent to create a confirmed reservation."""
    hold_token: str = Field(
        min_length=1,
        description="Required hold token from availability check"
    )    
    customer_name: str = Field(min_length=2, description="Name of the person making the booking")
    customer_phone: Optional[str] = Field(default=None, description="Contact phone number (optional)")
    customer_email: Optional[str] = Field(default=None, description="Contact email")
    restaurant_id: str = Field(default="rest_01", description="Restaurant ID")
    reservation_date: str = Field(description="Date in YYYY-MM-DD format")
    reservation_time: str = Field(description="Time in HH:MM format")
    guest_count: int = Field(gt=0, le=20, description="Number of guests")
    special_requests: Optional[str] = Field(default=None, description="Dietary needs, birthday, window table, etc.")
    seating_preference: str = Field(default="any",description="Preferred seating: indoor, outdoor, or any.")


class ReservationDetails(BaseModel):
    """Structured details of an active or confirmed reservation."""
    reservation_id: str
    customer_name: str
    customer_phone: Optional[str] = Field(default=None, description="Customer phone number (optional)")
    restaurant_id: str
    reservation_date: str
    reservation_time: str
    guest_count: int
    table_number: Optional[int] = None
    status: str = Field(default="confirmed", description="confirmed, cancelled, or pending")


class ReservationResponse(BaseModel):
    """Response returned upon booking creation."""
    status: str = Field(description="'confirmed' or 'failed'")
    reservation_id: Optional[str] = Field(default=None, description="Generated reservation identifier from backend")
    details: Optional[ReservationDetails] = None
    message: str = Field(description="Summary message from backend")

