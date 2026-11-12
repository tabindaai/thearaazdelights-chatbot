"""
Gemini AI Agent Chatbot Orchestrator.

Integrates:
- Google GenAI SDK (google-genai)
- Dynamic System Instruction with Runtime Context
- Function/Tool Calling
- Input and Output Guardrails
- Session Memory and State Transitions
"""

import os
import asyncio
import logging
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv

from google import genai
from google.genai import types

from agent.memory import memory_manager, SessionMemory, ConversationState
from agent.prompts import build_system_prompt
from agent.guardrails import Guardrails
from agent.tools import AgentTools

load_dotenv()

logger = logging.getLogger("agent.chatbot")
logger.setLevel(logging.INFO)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


class RestaurantChatbotAgent:
    """Orchestrates conversations, memory, guardrails, and Gemini tool calling."""

    def __init__(self, api_key: Optional[str] = None, model: str = GEMINI_MODEL):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model

    def _get_genai_client(self) -> Optional[genai.Client]:
        """Instantiate official GenAI client if a valid key exists."""
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return None
        return genai.Client(api_key=self.api_key)

    async def process_message(self, session_id: str, user_message: str) -> Tuple[str, str, Optional[str]]:
        """
        Main entry point for processing a customer message.
        Returns:
            (reply_text, current_state, reservation_id_if_confirmed)
        """
        # 1. Input Guardrail: Validate message length, whitespace, and injection
        is_valid, error_msg, sanitized_text = Guardrails.validate_user_input(user_message)
        session = memory_manager.get_or_create(session_id)

        if not is_valid:
            return error_msg, session.state.value, session.last_confirmed_reservation_id

        # 2. Duplicate Booking Safeguard: If already confirmed
        if (
            session.state == ConversationState.RESERVATION_CONFIRMED
            and session.last_confirmed_reservation_id
        ):
            if Guardrails.is_affirmative_confirmation(sanitized_text) or any(
                w in sanitized_text.lower() for w in ["confirm", "booked", "reservation", "status", "again", "yes", "yeah"]
            ):
                already_booked_reply = (
                    f"Your reservation is already confirmed!\n\n"
                    f"**Reservation ID:** `{session.last_confirmed_reservation_id}`\n"
                    f"**Name:** {session.draft.customer_name}\n"
                    f"**Date:** {session.draft.reservation_date}\n"
                    f"**Time:** {session.draft.reservation_time}\n"
                    f"**Party Size:** {session.draft.guest_count} guests\n"
                    f"We look forward to welcoming you to The Araaz Delights! Please let us know if you need to cancel or change details."
                )
                session.add_user_message(sanitized_text)
                session.add_model_message(already_booked_reply)
                return already_booked_reply, session.state.value, session.last_confirmed_reservation_id

        # 3. Context-Aware Deterministic Confirmation Handling in Python
        tools_instance = AgentTools(session)
        is_awaiting_confirmation = session.state in (
            ConversationState.AWAITING_CUSTOMER_CONFIRMATION,
            ConversationState.SLOT_AVAILABLE,
        )
        has_all_details = session.draft.has_required_booking_fields()
        is_affirmative = Guardrails.is_affirmative_confirmation(sanitized_text)

        if is_awaiting_confirmation and has_all_details and is_affirmative:
            logger.info(f"Customer explicit confirmation recognized for session '{session_id}'. Creating reservation...")
            session.draft.confirmed_by_customer = True

            booking_result = tools_instance.create_reservation()

            if booking_result.get("status") == "confirmed":
                res_id = booking_result["reservation_id"]
                phone_line = f"**Contact Phone:** {session.draft.customer_phone}\n" if session.draft.customer_phone else ""
                special_line = f"**Special Requests:** {session.draft.special_requests}\n" if session.draft.special_requests else ""

                confirmation_reply = (
                    f"Wonderful! Your reservation has been officially confirmed!\n\n"
                    f"**Reservation ID:** `{res_id}`\n"
                    f"**Guest Name:** {session.draft.customer_name}\n"
                    f"**Date:** {session.draft.reservation_date}\n"
                    f"**Time:** {session.draft.reservation_time}\n"
                    f"**Party Size:** {session.draft.guest_count} guests\n"
                    f"{phone_line}"
                    f"{special_line}\n"
                    f"We look forward to welcoming you to The Araaz Delights! Please let me know if you need anything else."
                )
                session.add_user_message(sanitized_text)
                session.add_model_message(confirmation_reply)
                return confirmation_reply, session.state.value, res_id
            else:
                fail_msg = booking_result.get("message") or booking_result.get("error") or "Unknown error"
                error_reply = (
                    f"I apologize, but we could not complete your reservation at this moment: {fail_msg}. "
                    f"Would you like to try another date or time?"
                )
                session.add_user_message(sanitized_text)
                session.add_model_message(error_reply)
                return error_reply, session.state.value, None

        # 4. Update Session History with user message
        session.add_user_message(sanitized_text)

        # 5. Check for API key configuration
        client = self._get_genai_client()
        if not client:
            fallback_reply = (
                "⚠️ **Gemini API Key Missing**: Please set your valid `GEMINI_API_KEY` in the `.env` file to enable the AI agent. "
                "Get your key at https://aistudio.google.com/"
            )
            session.add_model_message(fallback_reply)
            return fallback_reply, session.state.value, session.last_confirmed_reservation_id

        # 6. Bind Tools to this specific session
        tools_instance = AgentTools(session)

        # Synchronous wrapper functions for Gemini tool calling
        def update_reservation_details(
            name: str = "",
            phone: str = "",
            email: str = "",
            date: str = "",
            time: str = "",
            guest_count: int = 0,
            special_requests: str = "",
            confirmed_by_customer: bool = False,
        ) -> Dict[str, Any]:
            """Record customer details or explicit confirmation extracted from conversation."""
            return tools_instance.update_reservation_details(
                name=name or None,
                phone=phone or None,
                email=email or None,
                date=date or None,
                time=time or None,
                guest_count=guest_count if guest_count > 0 else None,
                special_requests=special_requests or None,
                confirmed_by_customer=confirmed_by_customer if confirmed_by_customer else None,
            )

        def check_table_availability(
            reservation_date: str,
            reservation_time: str,
            guest_count: int,
        ) -> Dict[str, Any]:
            """Check if tables are available for the requested date, time, and guest count."""
            return tools_instance.check_table_availability(
                reservation_date=reservation_date,
                reservation_time=reservation_time,
                guest_count=guest_count,
            )

        def find_alternative_slots(
            reservation_date: str,
            requested_time: str,
            guest_count: int,
        ) -> Dict[str, Any]:
            """Find alternative available time slots when requested time is booked."""
            return tools_instance.find_alternative_slots(
                reservation_date=reservation_date,
                requested_time=requested_time,
                guest_count=guest_count,
            )

        def create_reservation(
            customer_name: str = "",
            customer_phone: str = "",
            special_requests: str = "",
        ) -> Dict[str, Any]:
            """Book and confirm table reservation after customer has explicitly agreed."""
            return tools_instance.create_reservation(
                customer_name=customer_name or None,
                customer_phone=customer_phone or None,
                special_requests=special_requests or None,
            )

        def get_reservation_details(reservation_id: str) -> Dict[str, Any]:
            """Lookup an existing reservation by its reservation code."""
            return tools_instance.get_reservation_details(reservation_id)

        def cancel_existing_reservation(reservation_id: str) -> Dict[str, Any]:
            """Cancel an active reservation by its reservation code."""
            return tools_instance.cancel_existing_reservation(reservation_id)

        # 5. Build Dynamic System Prompt with current runtime state
        system_instruction = build_system_prompt(session)

        # 6. Execute Gemini Generation with Tool Calling Loop
        try:
            available_tools = [
                update_reservation_details,
                check_table_availability,
                find_alternative_slots,
                create_reservation,
                get_reservation_details,
                cancel_existing_reservation,
            ]

            # Build message history for Gemini SDK
            contents = []
            for msg in session.history:
                role = msg.get("role", "user")
                text = msg["parts"][0]["text"]
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=text)]
                    )
                )

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=available_tools,
                temperature=0.2,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False,
                    maximum_remote_calls=5,
                ),
            )

            # Generate content using google-genai
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

            raw_reply = response.text or "I have processed your request. How else may I assist you?"

            # 7. Apply Output Guardrails
            sanitized_reply = Guardrails.sanitize_output(raw_reply)

            # 8. Record model reply in session history
            session.add_model_message(sanitized_reply)

            return (
                sanitized_reply,
                session.state.value,
                session.last_confirmed_reservation_id,
            )

        except Exception as exc:
            logger.error(f"Error during Gemini processing: {exc}", exc_info=True)
            fallback = "I apologize, but I encountered a temporary issue processing your request. Could you please rephrase or try again?"
            session.add_model_message(fallback)
            return fallback, session.state.value, session.last_confirmed_reservation_id


# Global singleton instance of chatbot agent
chatbot_agent = RestaurantChatbotAgent()
