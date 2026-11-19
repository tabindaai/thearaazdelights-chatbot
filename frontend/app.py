"""
Streamlit Frontend Chatbot Interface.

Provides a clean, conversational UI for customers to reserve tables.
Communicates strictly via HTTP with the FastAPI backend (/chat, /health, /session).
Does NOT store Gemini keys or call database APIs directly.
"""

import uuid
import requests
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================================
# CONFIGURATION
# ============================================================================
FASTAPI_URL = "http://127.0.0.1:8000"

def get_greeting():
    current_hour = datetime.now(ZoneInfo("Asia/Kolkata")).hour

    if current_hour < 12:
        return "Good morning!"
    elif current_hour < 17:
        return "Good afternoon!"
    else:
        return "Good evening!"

st.set_page_config(
    page_title="The Araaz Delights - AI Concierge",
    page_icon="🍽️",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Custom CSS for polished hospitality styling
st.markdown("""
<style>
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    .restaurant-title {
        font-family: 'Playfair Display', serif;
        font-size: 2.2rem;
        color: #2c3e50;
        margin-bottom: 0.2rem;
    }
    .restaurant-subtitle {
        font-size: 1.0rem;
        color: #7f8c8d;
    }
    .stChatMessage {
        border-radius: 12px;
        padding: 0.5rem;
    }
    .status-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: bold;
        background-color: #e8f4fd;
        color: #1976d2;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
"content": f"{get_greeting()} Welcome to **The Araaz Delights**. I am Aria, your AI Reservation Concierge. How may I assist you with your table booking today?"        }
    ]

if "current_state" not in st.session_state:
    st.session_state.current_state = "START"

if "reservation_id" not in st.session_state:
    st.session_state.reservation_id = None

if "google_calendar_authorized" not in st.session_state:
    st.session_state.google_calendar_authorized = False

if "google_calendar_email" not in st.session_state:
    st.session_state.google_calendar_email = None


# ============================================================================
# BACKEND COMMUNICATION HELPERS
# ============================================================================
def check_backend_health() -> bool:
    """Verifies that the FastAPI backend is running."""
    try:
        res = requests.get(f"{FASTAPI_URL}/health", timeout=2.0)
        return res.status_code == 200
    except Exception:
        return False


def send_message_to_backend(user_text: str) -> dict:
    """Sends customer message to FastAPI /chat endpoint."""
    try:
        response = requests.post(
            f"{FASTAPI_URL}/chat",
            json={
                "message": user_text,
                "session_id": st.session_state.session_id,
            },
            timeout=120.0
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "response": f"⚠️ Server Error ({response.status_code}): {response.text}",
                "state": "ERROR",
                "reservation_id": None
            }
    except requests.exceptions.ConnectionError:
        return {
            "response": "⚠️ **Cannot connect to FastAPI backend server.** Please make sure the backend is running (`uvicorn main:app --reload`).",
            "state": "DISCONNECTED",
            "reservation_id": None
        }
    except Exception as exc:
        return {
            "response": f"⚠️ Communication error: {str(exc)}",
            "state": "ERROR",
            "reservation_id": None
        }


def reset_conversation():
    """Resets memory on backend and clears frontend chat."""
    try:
        requests.post(f"{FASTAPI_URL}/session/reset", params={"session_id": st.session_state.session_id}, timeout=2.0)
    except Exception:
        pass
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.current_state = "START"
    st.session_state.reservation_id = None
    st.session_state.messages = [
        {
            "role": "assistant",
"content": f"{get_greeting()} Welcome to **The Araaz Delights**. I am Aria, your AI Reservation Concierge. How may I assist you with your table booking today?"        }
    ]


def check_calendar_auth_status() -> dict:
    """Check Google Calendar authorization status from FastAPI backend."""
    try:
        res = requests.get(
            f"{FASTAPI_URL}/auth/status/{st.session_state.session_id}",
            timeout=3.0
        )
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {"google_calendar_authorized": False, "google_email": None, "has_stored_tokens": False}


def disconnect_google_calendar():
    """Disconnect Google Calendar via FastAPI backend."""
    try:
        requests.post(
            f"{FASTAPI_URL}/auth/disconnect/{st.session_state.session_id}",
            timeout=3.0
        )
    except Exception:
        pass
    st.session_state.google_calendar_authorized = False
    st.session_state.google_calendar_email = None


# Process OAuth callback redirect parameters
_query_params = st.query_params

if "oauth_success" in _query_params:
    auth_info = check_calendar_auth_status()
    st.session_state.google_calendar_authorized = auth_info.get("google_calendar_authorized", False)
    st.session_state.google_calendar_email = auth_info.get("google_email")
    st.toast("🎉 Google Calendar connected successfully!", icon="📅")
    st.query_params.clear()

elif "oauth_error" in _query_params:
    err_code = _query_params.get("oauth_error", "unknown")
    detail = _query_params.get("oauth_detail", "")
    err_msgs = {
        "cancelled": "Google Calendar authorization was cancelled.",
        "invalid_state": "Authorization session expired or was invalid. Please try again.",
        "exchange_failed": "Could not connect to Google Calendar. Please check your credentials.",
    }
    base_msg = err_msgs.get(err_code, "Calendar authorization failed.")
    full_msg = f"{base_msg} (Details: {detail})" if detail else base_msg
    st.error(f"⚠️ {full_msg}")
    st.query_params.clear()

if not st.session_state.google_calendar_authorized:
    _initial_status = check_calendar_auth_status()
    if _initial_status.get("google_calendar_authorized"):
        st.session_state.google_calendar_authorized = True
        st.session_state.google_calendar_email = _initial_status.get("google_email")


# ============================================================================
# SIDEBAR
# ============================================================================
with st.sidebar:
    st.markdown("### 🍷 The Araaz Delights")
    st.caption("AI-Powered Reservation Assistant")
    st.divider()

    # Backend Connectivity
    is_healthy = check_backend_health()
    if is_healthy:
        st.success("🟢 Backend Connected", icon="✅")
    else:
        st.error("🔴 Backend Offline", icon="⚠️")
        st.info("Run in terminal:\n`uvicorn main:app --reload`")

    st.divider()

    # Session Info
    st.markdown(f"**Session ID:** `{st.session_state.session_id}`")
    st.markdown(f"**Stage:** `{st.session_state.current_state}`")

    if st.session_state.reservation_id:
        st.success(f"🎉 **Booked ID:** `{st.session_state.reservation_id}`")

    st.divider()

    # Reset Button
    if st.button("🔄 Start New Conversation", use_container_width=True):
        reset_conversation()
        st.rerun()

    st.divider()

    # Google Calendar Integration Section
    st.markdown("### 📅 Google Calendar")
    if st.session_state.google_calendar_authorized:
        user_acc = st.session_state.google_calendar_email or "Authorized Google Account"
        st.success(f"**Connected**\n\n`{user_acc}`", icon="✅")
        st.caption("Reservations will automatically sync with a 3-hour reminder.")
        if st.button("🔌 Disconnect Calendar", use_container_width=True):
            disconnect_google_calendar()
            st.rerun()
    else:
        st.info("Sync bookings to your Google Calendar and receive a reminder 3 hours before.", icon="📅")
        auth_link = f"{FASTAPI_URL}/auth/google?session_id={st.session_state.session_id}"
        st.link_button("🔗 Connect Google Calendar", auth_link, use_container_width=True)
        st.caption("Optional. Table reservations work without it.")

    st.markdown("---")
    st.markdown(
    "💡 **Tip:** You can say:\n"
    "- *'Table for 4 tomorrow at 8 PM'*\n"
    "- *'I want to book a table for 2'*\n"
    "- *'Change time to 7:30 PM'*"
)

# ============================================================================
# MAIN CHAT AREA
# ============================================================================
st.markdown("""
<div class="main-header">
    <div class="restaurant-title">🍽️ The Araaz Delights</div>
    <div class="restaurant-subtitle">Fine Dining • Reservations & Inquiries Concierge</div>
</div>
""", unsafe_allow_html=True)

# Render chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🍽️"):
            st.markdown(msg["content"])

# Customer Input
if prompt := st.chat_input("Type your message here..."):
    # Append & display user message immediately
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    # Process with FastAPI backend with spinner
    with st.chat_message("assistant", avatar="🍽️"):
        with st.spinner("Aria is checking details..."):
            backend_result = send_message_to_backend(prompt)
            reply = backend_result.get("response", "No response received.")
            st.markdown(reply)

            # Update session state metadata
            st.session_state.current_state = backend_result.get("state", "UNKNOWN")
            if backend_result.get("reservation_id"):
                st.session_state.reservation_id = backend_result.get("reservation_id")

            # Store assistant reply in history
            st.session_state.messages.append({"role": "assistant", "content": reply})

