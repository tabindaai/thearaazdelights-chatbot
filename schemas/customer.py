"""
Pydantic schemas for Customer Relationship Management (CRM).
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


def calculate_vip_tier(total_visits: int) -> str:
    """
    Calculate customer loyalty tier based on cumulative completed visits:
    - 1-2 visits : Standard
    - 3-5 visits : Silver
    - 6-9 visits : Gold
    - 10+ visits : VIP Platinum
    """
    if total_visits >= 10:
        return "VIP Platinum"
    elif total_visits >= 6:
        return "Gold"
    elif total_visits >= 3:
        return "Silver"
    return "Standard"


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150, description="Customer full name")
    email: str = Field(..., description="Customer unique email address")
    phone: Optional[str] = Field(None, max_length=30, description="Customer phone number")
    dietary_preferences: Optional[str] = Field(None, description="Known allergies or dietary restrictions (e.g. Vegan, Nut Allergy)")
    seating_preference: Optional[str] = Field(None, max_length=50, description="Favorite seating (e.g. Window booth, Quiet corner)")
    notes: Optional[str] = Field(None, description="Special customer notes (e.g. Anniversary in November)")


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    phone: Optional[str] = Field(None, max_length=30)
    dietary_preferences: Optional[str] = None
    seating_preference: Optional[str] = None
    notes: Optional[str] = None


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    phone: Optional[str] = None
    vip_tier: str = "Standard"
    total_visits: int = 1
    dietary_preferences: Optional[str] = None
    seating_preference: Optional[str] = None
    notes: Optional[str] = None
    last_visit_date: Optional[date] = None
