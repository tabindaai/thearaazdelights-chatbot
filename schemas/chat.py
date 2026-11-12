"""
Pydantic schemas for Chat API communication between Frontend and Backend.
"""

from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Individual message in the conversation history."""
    role: str = Field(description="Role of the sender: 'user', 'assistant', or 'system'")
    content: str = Field(description="Textual content of the message")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatRequest(BaseModel):
    """Payload sent by the frontend to the /chat endpoint."""
    message: str = Field(
        min_length=1,
        max_length=1000,
        description="The customer's message to the chatbot."
    )
    session_id: str = Field(
        default="default_session",
        min_length=1,
        max_length=128,
        description="Unique identifier for the customer conversation session."
    )


class ChatResponse(BaseModel):
    """Payload returned by the /chat endpoint to the frontend."""
    response: str = Field(description="The AI chatbot's reply to the customer.")
    session_id: str = Field(description="The session identifier.")
    state: str = Field(description="Current conversation state (e.g. COLLECTING_DETAILS, SLOT_AVAILABLE)")
    reservation_id: Optional[str] = Field(
        default=None,
        description="Confirmed reservation ID if a reservation was successfully completed."
    )
