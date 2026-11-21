"""
Tests for Customer Relationship Management (CRM) & Loyalty Tier Integration.
"""

import pytest
from datetime import date
from schemas.customer import calculate_vip_tier
from services.restaurant_api import RestaurantAPIClient
from agent.memory import SessionMemory, ReservationDraft, ConversationState
from agent.tools import AgentTools
from agent.prompts import build_system_prompt
import os


@pytest.fixture(autouse=True)
def clean_mock_crm():
    """Reset mock customers in memory and disk before each test."""
    from services.restaurant_api import restaurant_api, MOCK_CUSTOMERS_FILE
    restaurant_api._mock_customers.clear()
    if os.path.exists(MOCK_CUSTOMERS_FILE):
        try:
            os.remove(MOCK_CUSTOMERS_FILE)
        except Exception:
            pass
    yield
    restaurant_api._mock_customers.clear()
    if os.path.exists(MOCK_CUSTOMERS_FILE):
        try:
            os.remove(MOCK_CUSTOMERS_FILE)
        except Exception:
            pass


def test_calculate_vip_tier():
    """Verify tier calculations based on visit thresholds."""
    assert calculate_vip_tier(0) == "Standard"
    assert calculate_vip_tier(1) == "Standard"
    assert calculate_vip_tier(2) == "Standard"
    assert calculate_vip_tier(3) == "Silver"
    assert calculate_vip_tier(5) == "Silver"
    assert calculate_vip_tier(6) == "Gold"
    assert calculate_vip_tier(9) == "Gold"
    assert calculate_vip_tier(10) == "VIP Platinum"
    assert calculate_vip_tier(25) == "VIP Platinum"


def test_crm_mock_sync_on_booking():
    """Verify customer profile creation and visit increments in mock mode."""
    client = RestaurantAPIClient(use_mock=True)

    # First booking creates new customer profile with 1 visit
    cust_id = client._mock_sync_customer_on_booking(
        name="Aarav Sharma",
        email="aarav@example.com",
        phone="9876543210",
        reservation_date="2026-12-01",
        seating_preference="outdoor",
        special_requests="Vegetarian",
    )
    assert cust_id is not None
    prof1 = client.get_customer_profile(email="aarav@example.com")
    assert prof1 is not None
    assert prof1["name"] == "Aarav Sharma"
    assert prof1["email"] == "aarav@example.com"
    assert prof1["total_visits"] == 1
    assert prof1["vip_tier"] == "Standard"
    assert prof1["dietary_preferences"] == "Vegetarian"
    assert prof1["seating_preference"] == "outdoor"

    # Second booking increments visit to 2 (still Standard)
    client._mock_sync_customer_on_booking(
        name="Aarav Sharma",
        email="aarav@example.com",
        phone="9876543210",
        reservation_date="2026-12-05",
    )
    prof2 = client.get_customer_profile(email="aarav@example.com")
    assert prof2["total_visits"] == 2
    assert prof2["vip_tier"] == "Standard"

    # Third booking upgrades to Silver tier
    client._mock_sync_customer_on_booking(
        name="Aarav Sharma",
        email="aarav@example.com",
        phone="9876543210",
        reservation_date="2026-12-10",
    )
    prof3 = client.get_customer_profile(email="aarav@example.com")
    assert prof3["total_visits"] == 3
    assert prof3["vip_tier"] == "Silver"


def test_crm_lookup_and_preference_update():
    """Verify looking up a customer and modifying dietary/seating preferences."""
    client = RestaurantAPIClient(use_mock=True)

    client._mock_sync_customer_on_booking(
        name="Priya Patel",
        email="priya@example.com",
        phone="9123456780",
        reservation_date="2026-11-20",
        seating_preference="indoor",
    )

    # Lookup by email
    found_by_email = client.get_customer_profile(email="priya@example.com")
    assert found_by_email is not None
    assert found_by_email["name"] == "Priya Patel"

    # Lookup by phone
    found_by_phone = client.get_customer_profile(phone="9123456780")
    assert found_by_phone is not None
    assert found_by_phone["email"] == "priya@example.com"

    # Update preferences
    updated = client.update_customer_preferences(
        email_or_id="priya@example.com",
        dietary_preferences="Gluten-Free, No Peanuts",
        seating_preference="Window booth",
        notes="Prefers quiet table",
    )
    assert updated["success"] is True
    assert updated["dietary_preferences"] == "Gluten-Free, No Peanuts"
    assert updated["seating_preference"] == "Window booth"
    assert updated["notes"] == "Prefers quiet table"


def test_agent_tools_crm_integration():
    """Verify AgentTools.get_customer_profile populates session and draft."""
    session = SessionMemory(session_id="test_crm_session")
    tools = AgentTools(session)

    # Pre-populate CRM mock customer
    from services.restaurant_api import restaurant_api
    restaurant_api._mock_sync_customer_on_booking(
        name="Vikram Singh",
        email="vikram@example.com",
        phone="9988776655",
        reservation_date="2026-11-25",
        seating_preference="outdoor",
        special_requests="Vegan",
    )

    # Agent calls get_customer_profile
    res = tools.get_customer_profile(email="vikram@example.com")
    assert res["found"] is True
    assert session.is_returning_customer is True
    assert session.customer_profile is not None
    assert session.customer_profile["name"] == "Vikram Singh"

    # Draft should be auto-filled
    assert session.draft.customer_name == "Vikram Singh"
    assert session.draft.customer_email == "vikram@example.com"
    assert session.draft.customer_phone == "9988776655"
    assert session.draft.seating_preference == "outdoor"
    assert session.draft.dietary_preferences == "Vegan"
    assert session.draft.vip_tier == "Standard"

    # Agent updates preferences
    up_res = tools.update_customer_preferences(
        dietary_preferences="Vegan, Nut Allergy",
        seating_preference="indoor",
    )
    assert up_res["success"] is True
    assert session.draft.dietary_preferences == "Vegan, Nut Allergy"
    assert session.draft.seating_preference == "indoor"


def test_prompts_returning_customer_context():
    """Verify build_system_prompt injects CRM loyalty profile details."""
    session = SessionMemory(session_id="test_prompt_crm")
    session.customer_profile = {
        "id": "cust_123",
        "name": "Ananya Roy",
        "email": "ananya@example.com",
        "phone": "9811223344",
        "vip_tier": "VIP Platinum",
        "total_visits": 12,
        "dietary_preferences": "Lactose Intolerant",
        "seating_preference": "outdoor",
        "notes": "Anniversary celebration",
        "last_visit_date": "2026-11-10",
    }
    session.is_returning_customer = True

    prompt = build_system_prompt(session)
    assert "VIP Platinum" in prompt
    assert "Total Visits: 12" in prompt
    assert "Ananya Roy" in prompt
    assert "Lactose Intolerant" in prompt
    assert "outdoor" in prompt


def test_crm_second_visit_recognition():
    """Verify customer on their second visit has total_visits=1 recognized as their 2nd visit."""
    session = SessionMemory(session_id="test_second_visit")
    session.customer_profile = {
        "id": "cust_zara_01",
        "name": "Zara",
        "email": "zara987@gmail.com",
        "phone": "9876543210",
        "vip_tier": "Standard",
        "total_visits": 1,
        "dietary_preferences": "Vegetarian",
        "seating_preference": "outdoor",
        "notes": None,
        "last_visit_date": "2026-11-20",
    }
    session.is_returning_customer = True

    prompt = build_system_prompt(session)
    assert "RETURNING GUEST" in prompt
    assert "Total Visits: 1" in prompt
    assert "2nd visit to The Araaz Delights" in prompt
    assert "Welcome back, Zara!" in prompt


def test_crm_email_domain_typo_correction():
    """Verify that common domain typos in customer emails are normalized."""
    from agent.guardrails import Guardrails
    assert Guardrails.normalize_email("ftoiba738@gamil.com") == "ftoiba738@gmail.com"
    assert Guardrails.normalize_email("tabinda@gmial.com") == "tabinda@gmail.com"
    assert Guardrails.normalize_email("user@yaho.com") == "user@yahoo.com"
    assert Guardrails.normalize_email("guest@hotmial.com") == "guest@hotmail.com"
    assert Guardrails.normalize_email("person@outlok.com") == "person@outlook.com"
    # Valid emails unchanged
    assert Guardrails.normalize_email("valid@gmail.com") == "valid@gmail.com"


def test_crm_cross_session_typo_resilience():
    """Verify that a returning guest who typos their domain (gamil.com) is still recognized from past booking."""
    from services.restaurant_api import restaurant_api

    # 1st Visit booked with @gmail.com
    restaurant_api._mock_sync_customer_on_booking(
        name="Tabinda",
        email="ftoiba738@gmail.com",
        phone="9876543210",
        reservation_date="2026-11-24",
        seating_preference="outdoor",
    )

    # 2nd Session lookup with typo @gamil.com
    prof = restaurant_api.get_customer_profile(email="ftoiba738@gamil.com")
    assert prof is not None, "Profile should be found even with @gamil.com typo!"
    assert prof["name"] == "Tabinda"
    assert prof["email"] == "ftoiba738@gmail.com"
    assert prof["total_visits"] == 1

    # Injected into 2nd session memory
    session = SessionMemory(session_id="fresh_session_after_refresh")
    tools = AgentTools(session)
    lookup_res = tools.get_customer_profile(email="ftoiba738@gamil.com")
    assert lookup_res["found"] is True
    assert session.is_returning_customer is True
    assert session.draft.customer_name == "Tabinda"

    prompt = build_system_prompt(session)
    assert "2nd visit to The Araaz Delights" in prompt
    assert "Welcome back, Tabinda!" in prompt
