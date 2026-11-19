
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

        if len(cleaned) < cls.MIN_INPUT_LENGTH:
            return False, "Message is too short.", ""

        if len(cleaned) > cls.MAX_INPUT_LENGTH:
            return (
                False,
                f"Message is too long. Please keep your message under {cls.MAX_INPUT_LENGTH} characters.",
                "",
            )

        # Prompt injection check
        if INJECTION_REGEX.search(cleaned):
            return (
                False,
                "I am a restaurant reservation assistant and cannot fulfill instructions to override my guidelines. How may I help you book a table?",
                cleaned,
            )

        return True, None, cleaned

    # ------------------------------------------------------------------------
    # 1.1 GREETING DETECTION
    # ------------------------------------------------------------------------
    @staticmethod
    def is_greeting(text: str) -> bool:
        """
        Recognizes common greetings and greeting variations.
        """
        if not text:
            return False

        message = re.sub(r"[^\w\s']", " ", text.lower())
        message = re.sub(r"\s+", " ", message).strip()

        greeting_words = (
            r"\b(hi+|hello+|hey+|hii+|heyy+|"
            r"namaste|namaskar|"
            r"good morning|good afternoon|good evening|"
            r"greetings|howdy)\b"
        )
        conversational_inquiries = (
            r"\b(how are you|how are you doing|how do you do|"
            r"hope you are doing well|how is it going|how are things)\b"
        )

        has_greeting = bool(
            re.search(greeting_words, message)
            or re.search(conversational_inquiries, message)
        )
        if not has_greeting:
            return False

        # If it has a greeting, ensure it is not followed by an unrelated question
        unrelated_signals = (
            r"\b(what is|who is|calculate|solve|code|programming|"
            r"python|java|javascript|fibonacci|quantum|weather|"
            r"history|geography|formula)\b"
        )
        if re.search(unrelated_signals, message):
            return False

        # If it contains reservation keywords, let it proceed to reservation handling
        booking_keywords = (
            r"\b(table|reserve|reservation|book|booking|guest|guests|people|indoor|outdoor)\b"
        )
        if re.search(booking_keywords, message):
            return False

        return True

    # ------------------------------------------------------------------------
    # 1.2 CONVERSATION CLOSING DETECTION
    # ------------------------------------------------------------------------
    @staticmethod
    def is_closing_message(text: str) -> bool:
        """
        Recognizes different ways customers may end a conversation.
        """
        if not text:
            return False

        message = re.sub(r"[^\w\s']", " ", text.lower())
        message = re.sub(r"\s+", " ", message).strip()

        # Closing markers
        closing_markers = [
            r"\b(bye|goodbye|good bye|farewell|see you|see you later|take care)\b",
            r"\b(have a (nice|good|great|wonderful) day)\b",
            r"\b(that's all|thats all|that is all|nothing else|nothing more|i'm done|i am done|all done|i'm finished|i am finished)\b",
            r"\b(no thanks|no thank you|no thankyou)\b",
        ]

        if any(re.search(marker, message) for marker in closing_markers):
            # Ensure it is not asking a new reservation request
            booking_keywords = r"\b(book|reserve|table|reservation|modify|cancel)\b"
            if not re.search(booking_keywords, message):
                return True

        # Standalone gratitude or polite acknowledgement without booking intent
        gratitude_phrases = [
            "thank you", "thanks", "thank u", "thanks a lot",
            "thank you so much", "thanks so much", "thank you very much",
            "okay thanks", "ok thanks", "ok thank you", "okay thank you",
            "sure thanks", "alright thanks", "alrighty thanks"
        ]
        if message in gratitude_phrases:
            return True

        return False

    # ------------------------------------------------------------------------
    # 1.3 TOPIC RELEVANCE GUARDRAIL
    # ------------------------------------------------------------------------
    @staticmethod
    def is_off_topic(text: str, session=None) -> bool:
        """
        Checks whether a message is related to restaurant reservations.

        Allows:
        - Greetings and closing messages.
        - Reservation-related questions.
        - Booking, availability, cancellation and modification requests.
        - Answers to reservation-detail questions.

        Rejects unrelated general knowledge, programming,
        mathematics, technology and other unrelated questions.
        """

        if not text or not text.strip():
            return True

        message = text.lower().strip()
        normalized = re.sub(r"[^\w\s']", " ", message)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Always allow recognized greetings
        if Guardrails.is_greeting(message):
            return False

        # Always allow recognized conversation endings
        if Guardrails.is_closing_message(message):
            return False

        # Always allow affirmative booking confirmations
        if Guardrails.is_affirmative_confirmation(message):
            return False

        # Simple acknowledgements and short conversational responses
        simple_responses = [
            "hi", "hello", "hey", "hii", "namaste", "namaskar",
            "okay", "ok", "sure", "yes", "yeah", "yep", "yup",
            "no", "nope", "alright", "fine", "perfect",
            "got it", "understood", "sounds good",
            "how are you", "i am fine", "i'm fine",
        ]

        if normalized in simple_responses:
            return False

        # Reservation-related keywords and phrases
        restaurant_keywords = [
            "reservation", "reserve", "book", "booking",
            "table", "availability", "available",
            "cancel", "cancellation", "modify",
            "change reservation", "reschedule",
            "restaurant", "guest", "guests",
            "people", "person", "indoor", "outdoor",
            "seating", "date", "time", "slot",
            "today", "tomorrow", "tonight", "day after tomorrow",
            "morning", "afternoon", "evening", "night",
            "lunch", "dinner", "brunch",
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
            "weekend", "this weekend", "next week",
            "opening hours", "closing hours",
            "opening time", "closing time",
            "restaurant hours", "restaurant location",
            "restaurant address", "restaurant timings",
            "special request", "special requests",
            "occasion", "reservation id", "booking id",
            "my booking", "my reservation",
            "confirmed", "confirmation",
            "check availability", "book a table",
            "reserve a table", "table for",
            "party size", "number of guests",
            "available tables", "booking details",
            "reservation details", "email", "email address",
            "my email", "calendar", "google calendar",
        ]

        # Check reservation-related keywords
        if any(
            re.search(r"\b" + re.escape(keyword) + r"\b", normalized)
            for keyword in restaurant_keywords
        ):
            return False

        # Date input support (both numeric formats and natural relative expressions)
        natural_date_pattern = (
            r"\b(today|tonight|tomorrow|day after tomorrow|"
            r"(this|next|coming)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
            r"(this|next)\s*(weekend|week)|"
            r"\d{1,2}(st|nd|rd|th)?\s*(of\s+)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|"
            r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*\d{1,2}(st|nd|rd|th)?|"
            r"\d{1,2}[-/\s]"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
            r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
            r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{1,2})"
            r"[-/\s]\d{2,4})\b"
        )

        # Time input support (e.g., "1pm", "1:00 PM", "13:00", "12", "12pm'", "at 6")
        time_pattern = (
            r"\b(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s?(?:am|pm)\b"
            r"|\b(?:[01]?\d|2[0-3]):[0-5]\d\b"
        )
        time_expression_pattern = (
            r"^\s*(?:at\s+)?(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(?:am|pm)?['.]?\s*$"
        )

        if (
            re.search(natural_date_pattern, message)
            or re.search(time_pattern, message)
            or re.search(time_expression_pattern, message, re.IGNORECASE)
        ):
            return False

        # Email input support (always on-topic)
        email_pattern = r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
        if re.search(email_pattern, message):
            return False

        # Context-aware reservation detail collection across all detail-gathering states
        detail_gathering_states = (
            ConversationState.COLLECTING_DETAILS,
            ConversationState.SLOT_AVAILABLE,
            ConversationState.SLOT_UNAVAILABLE,
            ConversationState.CHECKING_AVAILABILITY,
        )
        if session and session.state in detail_gathering_states:

            # Do not accept obvious unrelated questions as reservation details
            unrelated_question_pattern = (
                r"\b(what|why|who|where|explain|define|"
                r"teach|calculate|solve|code|programming|"
                r"python|java|javascript|machine learning|"
                r"artificial intelligence|history|science)\b"
            )

            if (
                "?" in message
                or re.search(unrelated_question_pattern, message)
            ):
                return True

            # Allow short answers that may represent reservation details
            # such as a customer's name, requested time, or party size.
            missing_fields = session.draft.missing_fields_for_booking()

            if (missing_fields or session.state == ConversationState.SLOT_UNAVAILABLE) and len(message.split()) <= 8 and len(message) <= 80:
                # Accept simple name-like or detail-like responses.
                simple_answer_pattern = r"^[a-zA-Z][a-zA-Z\s.'-]*$"

                if re.match(simple_answer_pattern, message.strip()):
                    return False

                # Accept numeric hour, guest counts, or phone-number-like answers.
                if re.fullmatch(r"[\d\s+\-()']+", message.strip()):
                    return False

                # Accept email address patterns as valid reservation detail answers.
                email_pattern = r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
                if re.search(email_pattern, message):
                    return False

        return True

    @staticmethod
    def off_topic_response() -> str:
        return (
            "I'm Aria, the virtual reservation assistant at Araaz Delights. "
            "I can help you with table reservations, availability, "
            "booking changes, and cancellations. "
            "How may I assist you?"
        )

    # ------------------------------------------------------------------------
    # 2. BUSINESS LOGIC GUARDRAILS
    # ------------------------------------------------------------------------
    @staticmethod
    def validate_reservation_date(date_str: str) -> Tuple[bool, str]:
        """
        Ensures date is valid and not in the past.
        Expected format: YYYY-MM-DD
        """
        if not date_str or not date_str.strip():
            return False, "Please provide a valid reservation date."

        target_date = None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                target_date = datetime.strptime(date_str.strip(), fmt).date()
                break
            except ValueError:
                continue

        if not target_date:
            return False, (
                f"Invalid date format '{date_str}'. Expected YYYY-MM-DD."
            )

        today = date.today()
        if target_date < today:
            return False, (
                f"Reservation date cannot be in the past ({date_str}). "
                "Please select today or a future date."
            )

        return True, "Valid date"

    @staticmethod
    def validate_guest_count(count: int) -> Tuple[bool, str]:
        """Ensures party size is within supported restaurant limits."""
        if count < 1:
            return False, "Party size must be at least 1 guest."

        if count > 20:
            return False, (
                "For parties larger than 20 guests, "
                "please contact our events team directly by phone."
            )

        return True, "Valid guest count"

    @staticmethod
    def validate_phone(phone_str: Optional[str]) -> Tuple[bool, str]:
        """Basic validation for customer contact number (optional)."""
        if not phone_str or not phone_str.strip():
            return True, "Phone number is optional"

        cleaned = re.sub(r"[\s\-()+]", "", phone_str)

        if not cleaned.isdigit() or len(cleaned) < 7 or len(cleaned) > 15:
            return False, (
                "Please provide a valid phone number (7 to 15 digits) "
                "or you may skip it."
            )

        return True, "Valid phone"

    @staticmethod
    def validate_email(email_str: Optional[str]) -> Tuple[bool, str]:
        """Validates customer email address format. Email is required for reservation and Google Calendar reminder."""
        if not email_str or not email_str.strip():
            return False, "Please provide your email address."

        pattern = re.compile(
            r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        )
        if not pattern.match(email_str.strip()):
            return False, (
                "Please provide a valid email address (e.g., name@example.com)."
            )

        return True, "Valid email"

    # ------------------------------------------------------------------------
    # 3. CONFIRMATION DETECTION & TOOL EXECUTION GATE
    # ------------------------------------------------------------------------
    @staticmethod
    def is_affirmative_confirmation(text: str) -> bool:
        """
        Determines whether customer's message expresses affirmative confirmation
        to book.

        Rejects messages containing negation, changes, new parameters,
        closings (e.g. 'okay bye', 'sure thanks'), or greetings.
        """
        if not text:
            return False

        # Closing messages must NEVER be interpreted as booking confirmation
        if Guardrails.is_closing_message(text):
            return False

        # Pure greetings must NEVER be interpreted as booking confirmation
        if Guardrails.is_greeting(text):
            return False

        cleaned = text.strip().lower()

        # Disqualify changes, cancellations, closings, negations, or non-booking acknowledgements
        disqualifiers = [
            r"\b(no|wait|cancel|don't|dont|change|different|"
            r"instead|actually|not yet|re-?book)\b",
            r"\b(pm|am|\d{1,2}:\d{2}|\d+\s*(people|guests|persons))\b",
            r"\b(bye|goodbye|see you|take care|that's all|thats all|nothing else|nothing more)\b",
            r"\b(thank you|thanks|thank u)\b",
            r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
        ]

        if any(re.search(pattern, cleaned) for pattern in disqualifiers):
            return False

        # Positive affirmative signals
        affirmative_patterns = [
            r"^\s*(yes|yeah|yep|yup|confirm|proceed|definitely|absolutely)\b",
            r"\b(please\s+book(\s+it)?|go\s+ahead|book\s+it|"
            r"confirm(\s+it)?|make\s+the\s+reservation|"
            r"finalize(\s+it)?)\b",
            r"\b(yes\s+please|yes\s+go\s+ahead|sounds\s+good|"
            r"that\s+works|looks\s+good)\b",
            r"^\s*(ok|okay|sure)\s*$",
        ]

        return any(
            re.search(pattern, cleaned)
            for pattern in affirmative_patterns
        )

    @staticmethod
    def can_execute_booking(
        draft: ReservationDraft,
        state: ConversationState
    ) -> Tuple[bool, str]:
        """
        Enforces that a reservation can NEVER be submitted to the backend unless:
        1. All mandatory fields are present (phone is optional).
        2. A valid availability hold token exists from check_table_availability.
        3. The customer has explicitly confirmed.
        """
        missing = draft.missing_fields_for_booking()

        if missing:
            return False, (
                f"Cannot book yet. Missing required details: "
                f"{', '.join(missing)}."
            )

        if not draft.hold_token or not draft.hold_token.strip():
            return False, (
                "Table availability hold token is missing or has expired. "
                "Please verify table availability before confirming the reservation."
            )

        if not draft.confirmed_by_customer:
            return (
                False,
                "Confirmation missing! You MUST ask the customer for "
                "explicit confirmation of date, time, and party size "
                "before calling create_reservation."
            )

        return True, "Authorized for booking"

    # ------------------------------------------------------------------------
    # 4. OUTPUT SANITIZATION GUARDRAIL
    # ------------------------------------------------------------------------
    @staticmethod
    def sanitize_output(response_text: str) -> str:
        """
        Scrubs internal stack traces, private API endpoints,
        and database errors before presenting responses.
        """
        if not response_text:
            return (
                "I apologize, but I could not generate a response. "
                "How can I assist you with your booking?"
            )

        # Mask internal endpoints and credentials (allow user-facing OAuth authorization link)
        redacted = re.sub(
            r"https?://(?:localhost|127\.0\.0\.1):\d+(?!/auth/google)",
            "[internal-service]",
            response_text
        )

        redacted = re.sub(
            r"AIza[0-9A-Za-z_-]{35}",
            "[REDACTED_API_KEY]",
            redacted
        )

        # Replace tracebacks if present
        if "Traceback (most recent call last):" in redacted:
            redacted = re.sub(
                r"Traceback \(most recent call last\):[\s\S]+",
                "An internal error occurred. Please try again.",
                redacted
            )

        return redacted
