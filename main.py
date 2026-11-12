"""
FastAPI Application Entry Point.

Exposes REST endpoints:
- GET  /health            : Health check and status
- POST /chat              : Process customer conversation turns through AI agent
- POST /session/reset     : Reset a conversation session
- GET  /session/{session_id}: Inspect current session draft and state
"""

import logging
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from schemas.chat import ChatRequest, ChatResponse
from agent.chatbot import chatbot_agent
from agent.memory import memory_manager

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

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
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

