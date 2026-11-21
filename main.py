"""
FastAPI Application Entry Point.

Exposes REST endpoints:
- GET  /health            : Health check and status
- POST /chat              : Process customer conversation turns through AI agent
- POST /session/reset     : Reset a conversation session
- GET  /session/{session_id}: Inspect current session draft and state
"""

from dotenv import load_dotenv
load_dotenv()

import logging
import secrets
from urllib.parse import quote_plus
from typing import Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from schemas.chat import ChatRequest, ChatResponse
from agent.chatbot import chatbot_agent
from agent.memory import memory_manager
from services.oauth_store import oauth_store

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

# In-memory mapping of OAuth state -> session_id (validates callback CSRF)
_oauth_states: dict = {}

app = FastAPI(
    title="Restaurant Reservation AI Concierge API",
    description="FastAPI backend orchestrating Google Gemini function calling for restaurant bookings.",
    version="1.0.0",
)

# Enable CORS for local Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint to verify backend operational readiness."""
    return {
        "status": "healthy",
        "service": "restaurant_ai_chatbot",
        "version": "1.0.0"
    }


@app.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat_endpoint(request: ChatRequest):
    """
    Primary conversational endpoint.
    Receives customer message, routes through memory & guardrails,
    executes Gemini tool-calling, and returns structured response.
    """
    logger.info(f"Incoming message for session '{request.session_id}': {request.message[:60]}...")

    try:
        reply_text, current_state, reservation_id = await chatbot_agent.process_message(
            session_id=request.session_id,
            user_message=request.message,
        )

        return ChatResponse(
            response=reply_text,
            session_id=request.session_id,
            state=current_state,
            reservation_id=reservation_id,
        )

    except Exception as exc:
        logger.error(f"Unhandled error processing message: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing your conversation turn."
        )


@app.post("/session/reset", status_code=status.HTTP_200_OK)
async def reset_session(session_id: str):
    """Reset conversation memory and reservation draft for a session."""
    existed = memory_manager.reset_session(session_id)
    return {
        "status": "reset",
        "session_id": session_id,
        "message": "Session reset successfully." if existed else "Session initialized."
    }


@app.get("/session/{session_id}", status_code=status.HTTP_200_OK)
async def get_session_info(session_id: str):
    """Debug endpoint: inspect active session memory state and current draft."""
    if not memory_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    session = memory_manager.get_or_create(session_id)
    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "draft": session.draft.model_dump(),
        "missing_fields": session.draft.missing_fields_for_booking(),
        "history_count": len(session.history),
        "customer_profile": session.customer_profile,
        "is_returning_customer": session.is_returning_customer,
    }


# ============================================================================
# Google Calendar OAuth 2.0 Endpoints
# ============================================================================

@app.get("/auth/google", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def initiate_google_oauth(session_id: str):
    """
    Start Google OAuth 2.0 authorization for Google Calendar access.
    Redirects the customer to Google's official authorization page.
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = session_id

    try:
        from services.calendar_service import calendar_service
        auth_url = calendar_service.build_auth_url(session_id=session_id, state=state)
        logger.info(f"OAuth flow initiated for session '{session_id}' (state: {state[:8]}...)")
        return RedirectResponse(url=auth_url)
    except Exception as exc:
        logger.error(f"Failed to generate OAuth URL for session '{session_id}': {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Google OAuth configuration error: {str(exc)}. Please verify GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET."
        )


@app.get("/auth/callback")
async def google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Google OAuth 2.0 callback endpoint.
    Exchanges code for tokens, records the authorized email, and redirects back to Streamlit.
    """
    frontend_base = "http://localhost:8501"

    if error:
        logger.warning(f"Google OAuth authorization returned error: {error}")
        return RedirectResponse(url=f"{frontend_base}?oauth_error=cancelled")

    if not state or not code:
        logger.warning("Missing state or code in OAuth callback.")
        return RedirectResponse(url=f"{frontend_base}?oauth_error=invalid_request")

    session_id = _oauth_states.pop(state, None)
    if not session_id:
        logger.warning(f"OAuth callback state '{state}' not found or expired.")
        return RedirectResponse(url=f"{frontend_base}?oauth_error=invalid_state")

    try:
        from services.calendar_service import calendar_service
        result = calendar_service.exchange_code(session_id=session_id, code=code, state=state)

        if result.get("success"):
            google_email = result.get("google_email", "")
            session = memory_manager.get_or_create(session_id)
            session.google_calendar_authorized = True
            session.authorized_google_email = google_email
            logger.info(f"Google Calendar authorized for session '{session_id}' (account: '{google_email}')")

            # Auto-sync existing confirmed reservation to Google Calendar immediately
            if session.last_confirmed_reservation_id:
                try:
                    from agent.tools import AgentTools
                    tools = AgentTools(session)
                    cal_res = tools.save_to_google_calendar()
                    logger.info(f"Auto-synced existing reservation '{session.last_confirmed_reservation_id}' to Google Calendar: {cal_res}")
                except Exception as auto_cal_err:
                    logger.warning(f"Failed to auto-sync existing reservation on OAuth callback: {auto_cal_err}")

            return RedirectResponse(url=f"{frontend_base}?oauth_success=1&session_id={session_id}")
        else:
            err_msg = result.get("error", "Token exchange failed")
            logger.error(f"Token exchange failed for session '{session_id}': {err_msg}")
            return RedirectResponse(url=f"{frontend_base}?oauth_error=exchange_failed&oauth_detail={quote_plus(err_msg)}")

    except Exception as exc:
        logger.error(f"Unexpected error in OAuth callback for session '{session_id}': {exc}", exc_info=True)
        return RedirectResponse(url=f"{frontend_base}?oauth_error=internal_error&oauth_detail={quote_plus(str(exc))}")


@app.get("/auth/status/{session_id}", status_code=status.HTTP_200_OK)
async def get_auth_status(session_id: str):
    """
    Check whether Google Calendar is authorized for the given session.
    """
    has_tokens = oauth_store.has_valid_tokens(session_id)
    stored_email = oauth_store.get_google_email(session_id)
    session = memory_manager.get_or_create(session_id)

    # Sync memory with stored tokens if needed
    if has_tokens and not session.google_calendar_authorized:
        session.google_calendar_authorized = True
        session.authorized_google_email = stored_email

    return {
        "session_id": session_id,
        "google_calendar_authorized": session.google_calendar_authorized,
        "google_email": session.authorized_google_email or stored_email,
        "has_stored_tokens": has_tokens,
    }


@app.post("/auth/disconnect/{session_id}", status_code=status.HTTP_200_OK)
async def disconnect_calendar(session_id: str):
    """
    Revoke/remove Google Calendar access for the given session.
    """
    oauth_store.delete_tokens(session_id)
    session = memory_manager.get_or_create(session_id)
    session.google_calendar_authorized = False
    session.authorized_google_email = None
    session.last_confirmed_calendar_event_id = None
    logger.info(f"Google Calendar disconnected for session '{session_id}'")
    return {
        "status": "disconnected",
        "session_id": session_id,
        "message": "Google Calendar disconnected successfully."
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

