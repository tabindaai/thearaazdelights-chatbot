"""
Guardrails and Security Layer.

Implements multi-layer protection:
1. Input validation & prompt injection defenses.
2. Deterministic business rule validation (dates, guests, phone numbers).
3. Tool execution safety gates (strict confirmation before booking).
4. Output sanitization (hides stack traces, credentials, and raw internal errors).
"""

import re
from datetime import datetime, date
from typing import Tuple, Optional
from agent.memory import ReservationDraft, ConversationState


# Common prompt injection patterns attempting to hijack system directives
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|system)\s+instructions",
    r"you\s+are\s+now\s+(an?\s+)?unrestricted",
    r"system\s*:\s*override",
    r"show\s+me\s+your\s+system\s+prompt",
    r"reveal\s+your\s+(api\s+key|instructions|credentials)",
    r"dan\s+mode",
    r"jailbreak",
]

INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


class Guardrails:
    """Security and business integrity validation engine."""

    MAX_INPUT_LENGTH = 800
    MIN_INPUT_LENGTH = 1

    # ------------------------------------------------------------------------
    # 1. INPUT GUARDRAILS
    # ------------------------------------------------------------------------
    @classmethod
    def validate_user_input(cls, text: str) -> Tuple[bool, Optional[str], str]:
        """
        Validates incoming user message.
        Returns:
            (is_valid, error_message_for_user, sanitized_text)
        """
        if not text or not text.strip():
            return False, "Please enter a valid message. Empty messages cannot be processed.", ""

        cleaned = text.strip()

        # Length bounds check
        if len(cleaned) < cls.MIN_INPUT_LENGTH:
            return False, "Message is too short.", ""

        if len(cleaned) > cls.MAX_INPUT_LENGTH:
            return False, f"Message is too long. Please keep your message under {cls.MAX_INPUT_LENGTH} characters.", ""

        # Prompt injection check
        if INJECTION_REGEX.search(cleaned):
            return (
                False,
                "I am a restaurant reservation assistant and cannot fulfill instructions to override my guidelines. How may I help you book a table?",
                cleaned,
            )

        return True, None, cleaned

    # ------------------------------------------------------------------------
    # 2. BUSINESS LOGIC GUARDRAILS
    # ------------------------------------------------------------------------
    @staticmethod
    def validate_reservation_date(date_str: str) -> Tuple[bool, str]:
        """
        Ensures date is valid and not in the past.
        Expected format: YYYY-MM-DD
        """
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = date.today()
            if target_date < today:
                return False, f"Reservation date cannot be in the past ({date_str}). Please select today or a future date."
            return True, "Valid date"
        except ValueError:
            return False, f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."

    @staticmethod
    def validate_guest_count(count: int) -> Tuple[bool, str]:
        """Ensures party size is within supported restaurant limits."""
        if count < 1:
            return False, "Party size must be at least 1 guest."
        if count > 20:
            return False, "For parties larger than 20 guests, please contact our events team directly by phone."
        return True, "Valid guest count"

    @staticmethod
    def validate_phone(phone_str: Optional[str]) -> Tuple[bool, str]:
        """Basic validation for customer contact number (optional)."""
        if not phone_str or not phone_str.strip():
            return True, "Phone number is optional"
        cleaned = re.sub(r"[\s\-\(\)\+]", "", phone_str)
        if not cleaned.isdigit() or len(cleaned) < 7 or len(cleaned) > 15:
            return False, "Please provide a valid phone number (7 to 15 digits) or you may skip it."
        return True, "Valid phone"

    # ------------------------------------------------------------------------
    # 3. CONFIRMATION DETECTION & TOOL EXECUTION GATE
    # ------------------------------------------------------------------------
    @staticmethod
    def is_affirmative_confirmation(text: str) -> bool:
        """
        Determines whether customer's message expresses affirmative confirmation to book.
        Context-aware: Rejects if user also expresses negation, changes, or new parameters.
        """
        if not text:
            return False

        cleaned = text.strip().lower()

        # Disqualify if customer asks to change, cancel, or expresses negation
        disqualifiers = [
            r"\b(no|wait|cancel|don'?t|change|different|instead|actually|not\s+yet|re-?book)\b",
            r"\b(pm|am|\d{1,2}:\d{2}|\d+\s*(people|guests|persons))\b",  # Parameter changes
        ]
        if any(re.search(pat, cleaned) for pat in disqualifiers):
            return False

        # Positive affirmative signals
        affirmative_patterns = [
            r"^\s*(yes|yeah|yep|yup|sure|ok|okay|confirm|proceed|definitely|absolutely)\b",
            r"\b(please\s+book(\s+it)?|go\s+ahead|book\s+it|confirm(\s+it)?|make\s+the\s+reservation|finalize(\s+it)?)\b",
            r"\b(yes\s+please|yes\s+go\s+ahead|sounds\s+good|that\s+works|looks\s+good)\b",
        ]
        return any(re.search(pat, cleaned) for pat in affirmative_patterns)

    @staticmethod
    def can_execute_booking(draft: ReservationDraft, state: ConversationState) -> Tuple[bool, str]:
        """
        Enforces that a reservation can NEVER be submitted to the backend unless:
        1. All mandatory fields (name, date, time, guests) are present (phone is optional).
        2. The customer has given explicit confirmation.
        """
        missing = draft.missing_fields_for_booking()
        if missing:
            return False, f"Cannot book yet. Missing required details: {', '.join(missing)}."

        if not draft.confirmed_by_customer:
            return (
                False,
                "Confirmation missing! You MUST ask the customer for explicit confirmation of date, time, and party size before calling create_reservation."
            )

        return True, "Authorized for booking"

    # ------------------------------------------------------------------------
    # 4. OUTPUT SANITIZATION GUARDRAIL
    # ------------------------------------------------------------------------
    @staticmethod
    def sanitize_output(response_text: str) -> str:
        """
        Scrubs internal stack traces, private API endpoints, or database errors
        before presenting response to customer.
        """
        if not response_text:
            return "I apologize, but I could not generate a response. How can I assist you with your booking?"

        # Mask potential leaked internal endpoints & credentials first
        redacted = re.sub(r"https?://localhost:\d+", "[internal-service]", response_text)
        redacted = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", redacted)

        # Replace tracebacks if present
        if "Traceback (most recent call last):" in redacted:
            redacted = re.sub(r"Traceback \(most recent call last\):[\s\S]+", "An internal error occurred. Please try again.", redacted)

        return redacted
