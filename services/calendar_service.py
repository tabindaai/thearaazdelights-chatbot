"""
Google Calendar API service wrapper for Araaz Delights restaurant chatbot.

Provides OAuth2 authorisation helpers and CRUD operations for Google Calendar
events that correspond to restaurant reservations.  All token persistence is
delegated to the OAuthStore singleton so no credentials are held in memory
beyond a single request.

Environment variables consumed:
    GOOGLE_CLIENT_ID      – OAuth2 client ID from Google Cloud Console.
    GOOGLE_CLIENT_SECRET  – OAuth2 client secret.
    GOOGLE_REDIRECT_URI   – Redirect URI registered in Google Cloud Console.
    CALENDAR_TIMEZONE     – IANA timezone for created events (default: Asia/Kolkata).

Security notes:
    - Access tokens and refresh tokens are NEVER written to log output.
    - All public methods catch every exception and return an error dict rather
      than propagating exceptions to callers.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow

from services.oauth_store import oauth_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_RESTAURANT_ADDRESS = "The Araaz Delights, 123 Fine Dining Avenue"
_EVENT_TITLE = "Restaurant Reservation - Araaz Delights"
_REMINDER_MINUTES = 3
_EVENT_DURATION_HOURS = 2


def _get_client_config() -> dict:
    """Build the OAuth2 client config dict from environment variables."""
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI", "")],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _calendar_timezone() -> str:
    """Return the configured IANA timezone string."""
    return os.getenv("CALENDAR_TIMEZONE", "Asia/Kolkata")


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------


class CalendarService:
    """
    Wrapper around the Google Calendar API v3 for managing reservation events.

    All methods are stateless with respect to credentials: tokens are read from
    and written back to the OAuthStore on every call.
    """

    def __init__(self):
        self._verifiers: dict = {}

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def build_auth_url(self, session_id: str, state: str) -> str:
        """
        Construct a Google OAuth2 authorisation URL for the given session.

        The URL directs the user to Google's consent screen and, upon approval,
        redirects them to ``GOOGLE_REDIRECT_URI`` with an authorisation code.

        Args:
            session_id: Unique identifier for the user session (stored for
                        later reference but not embedded in the URL itself).
            state:      An opaque string that Google will echo back on redirect,
                        used to prevent CSRF and to correlate the callback with
                        the initiating session.

        Returns:
            The full authorisation URL as a string.

        Raises:
            Never – exceptions are caught and re-raised as error strings are
            not applicable here; callers should handle ``ValueError`` if env
            vars are missing.
        """
        try:
            flow = Flow.from_client_config(
                _get_client_config(),
                scopes=_SCOPES,
                redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", ""),
                autogenerate_code_verifier=False,
            )
            auth_url, _ = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
                state=state,
                prompt="consent",
            )
            if getattr(flow, "code_verifier", None):
                self._verifiers[state] = flow.code_verifier
            return auth_url
        except Exception as exc:
            logger.error("build_auth_url failed for session %s: %s", session_id, exc)
            raise

    def exchange_code(self, session_id: str, code: str, state: str) -> dict:
        """
        Exchange an OAuth2 authorisation code for access and refresh tokens.

        The resulting tokens are saved to the OAuthStore under *session_id*.
        The user's Google email address is obtained from the ID token claims
        (if present) or via the ``userinfo`` endpoint as a fallback.

        Args:
            session_id: Unique identifier for the user session.
            code:       The one-time authorisation code returned by Google.
            state:      The state string from the redirect (not verified here;
                        CSRF validation should happen in the calling route).

        Returns:
            ``{"success": True, "google_email": "<email>"}`` on success, or
            ``{"success": False, "error": "<message>"}`` on failure.
        """
        try:
            flow = Flow.from_client_config(
                _get_client_config(),
                scopes=_SCOPES,
                redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", ""),
                state=state,
                autogenerate_code_verifier=False,
            )
            verifier = self._verifiers.pop(state, None)
            if verifier:
                flow.code_verifier = verifier
                flow.fetch_token(code=code, code_verifier=verifier)
            else:
                flow.fetch_token(code=code)
            credentials = flow.credentials

            # --- Extract Google email ------------------------------------------
            google_email = ""
            # Try ID token claims first (no extra HTTP request).
            id_token_claims = getattr(credentials, "id_token", None)
            if isinstance(id_token_claims, dict):
                google_email = id_token_claims.get("email", "")

            if not google_email:
                # Fallback: call userinfo endpoint.
                try:
                    import google.auth.transport.requests as gtr
                    import requests as _requests

                    authed_session = gtr.Request(session=_requests.Session())
                    userinfo_response = _requests.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers={"Authorization": f"Bearer {credentials.token}"},
                        timeout=10,
                    )
                    if userinfo_response.ok:
                        google_email = userinfo_response.json().get("email", "")
                except Exception as ui_exc:
                    logger.warning("Could not fetch userinfo for session %s: %s", session_id, ui_exc)

            # --- Determine expiry -----------------------------------------------
            expiry_dt = credentials.expiry  # datetime or None
            if expiry_dt is None:
                # Default to 1 hour from now if Google did not supply it.
                expiry_dt = datetime.now(timezone.utc) + timedelta(hours=1)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            expiry_iso = expiry_dt.isoformat()

            # --- Persist tokens (access_token value is not logged) --------------
            oauth_store.save_tokens(
                session_id=session_id,
                access_token=credentials.token or "",
                refresh_token=credentials.refresh_token or "",
                token_expiry_iso=expiry_iso,
                google_email=google_email,
            )

            logger.info("OAuth tokens saved for session %s (email: %s)", session_id, google_email)
            return {"success": True, "google_email": google_email}

        except Exception as exc:
            logger.error("exchange_code failed for session %s: %s", session_id, exc)
            return {"success": False, "error": str(exc)}

    def get_calendar_service(self, session_id: str):
        """
        Build and return an authenticated Google Calendar API service object.

        Tokens are loaded from the OAuthStore.  If the access token is expired,
        it is automatically refreshed using the stored refresh token, and the
        updated tokens are written back to the store.

        Args:
            session_id: Unique identifier for the user session.

        Returns:
            A ``googleapiclient.discovery.Resource`` for the Calendar v3 API,
            or ``None`` if no tokens are found for the session.
        """
        try:
            token_data = oauth_store.get_tokens(session_id)
            if token_data is None:
                logger.warning("No tokens found for session %s", session_id)
                return None

            expiry_dt = None
            if token_data.get("token_expiry"):
                try:
                    expiry_dt = datetime.fromisoformat(token_data["token_expiry"])
                    if expiry_dt.tzinfo is not None:
                        expiry_dt = expiry_dt.astimezone(tzinfo=timezone.utc).replace(tzinfo=None)
                except (ValueError, TypeError):
                    expiry_dt = None

            credentials = Credentials(
                token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
                client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
                scopes=_SCOPES,
                expiry=expiry_dt,
            )

            # Refresh if expired or about to expire.
            if (
                expiry_dt is not None
                and expiry_dt <= datetime.now(timezone.utc)
                and credentials.refresh_token
            ):

                try:
                    credentials.refresh(Request())
                    # Persist refreshed tokens (do NOT log token values).
                    new_expiry = credentials.expiry
                    if new_expiry and new_expiry.tzinfo is None:
                        new_expiry = new_expiry.replace(tzinfo=timezone.utc)
                    oauth_store.save_tokens(
                        session_id=session_id,
                        access_token=credentials.token or "",
                        refresh_token=credentials.refresh_token or "",
                        token_expiry_iso=new_expiry.isoformat() if new_expiry else "",
                        google_email=token_data.get("google_email", ""),
                    )
                    logger.info("Refreshed access token for session %s", session_id)
                except Exception as refresh_exc:
                    logger.error(
                        "Token refresh failed for session %s: %s", session_id, refresh_exc
                    )
                    return None

            service = build("calendar", "v3", credentials=credentials)
            return service

        except Exception as exc:
            logger.error("get_calendar_service failed for session %s: %s", session_id, exc)
            return None

    # ------------------------------------------------------------------
    # Event CRUD
    # ------------------------------------------------------------------

    def create_reservation_event(self, session_id: str, reservation_data: dict) -> dict:
        """
        Create a Google Calendar event for a confirmed restaurant reservation.

        The event is added to the authenticated user's primary calendar with a
        3-hour (180-minute) popup reminder.

        Args:
            session_id:       Unique identifier for the user session.
            reservation_data: Dictionary containing reservation details with
                              the following expected keys:

                              - ``customer_name`` (str)
                              - ``customer_email`` (str)
                              - ``reservation_date`` (str, YYYY-MM-DD)
                              - ``reservation_time`` (str, HH:MM)
                              - ``guest_count`` (int)
                              - ``reservation_id`` (str)
                              - ``special_requests`` (str, optional)
                              - ``seating_preference`` (str, optional)

        Returns:
            ``{"success": True, "event_id": "<id>", "event_link": "<url>"}``
            on success, or ``{"success": False, "error": "<message>"}`` on
            failure.
        """
        try:
            service = self.get_calendar_service(session_id)
            if service is None:
                return {"success": False, "error": "No valid Google Calendar credentials for this session."}

            tz = _calendar_timezone()
            date_str = reservation_data.get("reservation_date", "")
            time_str = reservation_data.get("reservation_time", "")
            start_dt_str = f"{date_str}T{time_str}:00"

            start_dt = datetime.fromisoformat(start_dt_str)
            end_dt = start_dt + timedelta(hours=_EVENT_DURATION_HOURS)

            customer_name = reservation_data.get("customer_name", "Guest")
            customer_email = reservation_data.get("customer_email", "")
            guest_count = reservation_data.get("guest_count", 1)
            reservation_id = reservation_data.get("reservation_id", "")
            special_requests = reservation_data.get("special_requests", "") or "None"
            seating_preference = reservation_data.get("seating_preference", "") or "Any"

            description = (
                f"🍽️ Reservation Details\n"
                f"{'─' * 40}\n"
                f"Reservation ID : {reservation_id}\n"
                f"Guest Name     : {customer_name}\n"
                f"Guest Email    : {customer_email}\n"
                f"Date           : {date_str}\n"
                f"Time           : {time_str}\n"
                f"Party Size     : {guest_count} guest(s)\n"
                f"Seating        : {seating_preference}\n"
                f"Special Notes  : {special_requests}\n"
                f"{'─' * 40}\n"
                f"📍 Location: {_RESTAURANT_ADDRESS}\n\n"
                f"We look forward to welcoming you at Araaz Delights!\n"
                f"For enquiries, please contact us with your Reservation ID."
            )

            event_body = {
                "summary": _EVENT_TITLE,
                "description": description,
                "location": _RESTAURANT_ADDRESS,
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": tz,
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": tz,
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {
                            "method": "popup",
                            "minutes": _REMINDER_MINUTES,
                        },
                        {
                            "method": "email",
                            "minutes": _REMINDER_MINUTES,
                        },
                    ],
                }
            }

            created_event = service.events().insert(
                calendarId="primary", body=event_body
            ).execute()

            event_id = created_event.get("id", "")
            event_link = created_event.get("htmlLink", "")
            logger.info(
                "Calendar event created for session %s, reservation %s, event_id %s",
                session_id,
                reservation_id,
                event_id,
            )
            return {"success": True, "event_id": event_id, "event_link": event_link}

        except Exception as exc:
            logger.error(
                "create_reservation_event failed for session %s: %s", session_id, exc
            )
            return {"success": False, "error": str(exc)}

    def update_reservation_event(
        self, session_id: str, event_id: str, reservation_data: dict
    ) -> dict:
        """
        Update an existing Google Calendar reservation event with new details.

        Only the fields supplied in *reservation_data* are applied; the event
        title and 180-minute reminder are always preserved.

        Args:
            session_id:       Unique identifier for the user session.
            event_id:         The Google Calendar event ID to update.
            reservation_data: Dictionary with any subset of the keys accepted
                              by :meth:`create_reservation_event`.

        Returns:
            ``{"success": True, "event_id": "<id>"}`` on success, or
            ``{"success": False, "error": "<message>"}`` on failure.
        """
        try:
            service = self.get_calendar_service(session_id)
            if service is None:
                return {"success": False, "error": "No valid Google Calendar credentials for this session."}

            tz = _calendar_timezone()

            # Fetch the existing event so we can patch only changed fields.
            existing_event = service.events().get(
                calendarId="primary", eventId=event_id
            ).execute()

            date_str = reservation_data.get("reservation_date", "")
            time_str = reservation_data.get("reservation_time", "")

            if date_str and time_str:
                start_dt_str = f"{date_str}T{time_str}:00"
                start_dt = datetime.fromisoformat(start_dt_str)
                end_dt = start_dt + timedelta(hours=_EVENT_DURATION_HOURS)
                existing_event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz}
                existing_event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}

            # Rebuild description from provided data, falling back to current values.
            customer_name = reservation_data.get("customer_name", "Guest")
            customer_email = reservation_data.get("customer_email", "")
            guest_count = reservation_data.get("guest_count", "")
            reservation_id = reservation_data.get("reservation_id", event_id)
            special_requests = reservation_data.get("special_requests", "") or "None"
            seating_preference = reservation_data.get("seating_preference", "") or "Any"

            description = (
                f"🍽️ Reservation Details (Updated)\n"
                f"{'─' * 40}\n"
                f"Reservation ID : {reservation_id}\n"
                f"Guest Name     : {customer_name}\n"
                f"Guest Email    : {customer_email}\n"
                f"Date           : {date_str}\n"
                f"Time           : {time_str}\n"
                f"Party Size     : {guest_count} guest(s)\n"
                f"Seating        : {seating_preference}\n"
                f"Special Notes  : {special_requests}\n"
                f"{'─' * 40}\n"
                f"📍 Location: {_RESTAURANT_ADDRESS}\n\n"
                f"We look forward to welcoming you at Araaz Delights!\n"
                f"For enquiries, please contact us with your Reservation ID."
            )

            existing_event["summary"] = _EVENT_TITLE
            existing_event["description"] = description
            existing_event["reminders"] = {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": _REMINDER_MINUTES},{"method":"email","minutes":_REMINDER_MINUTES}],
            }

            updated_event = service.events().update(
                calendarId="primary", eventId=event_id, body=existing_event
            ).execute()

            # Verify reminders saved by Google Calendar
            verified_event = service.events().get(
                calendarId="primary",
                eventId=event_id,
            ).execute()

            logger.info(
                "Verified reminder configuration: %s",
                verified_event.get("reminders", {})
            )
             
            logger.info(
                "Calendar event updated for session %s, event_id %s", session_id, event_id
            )
            return {"success": True, "event_id": updated_event.get("id", event_id)}

        except Exception as exc:
            logger.error(
                "update_reservation_event failed for session %s, event %s: %s",
                session_id,
                event_id,
                exc,
            )
            return {"success": False, "error": str(exc)}

    def delete_reservation_event(self, session_id: str, event_id: str) -> dict:
        """
        Delete (cancel) a Google Calendar reservation event.

        Args:
            session_id: Unique identifier for the user session.
            event_id:   The Google Calendar event ID to delete.

        Returns:
            ``{"success": True}`` on success, or
            ``{"success": False, "error": "<message>"}`` on failure.
        """
        try:
            service = self.get_calendar_service(session_id)
            if service is None:
                return {"success": False, "error": "No valid Google Calendar credentials for this session."}

            service.events().delete(calendarId="primary", eventId=event_id).execute()
            logger.info(
                "Calendar event deleted for session %s, event_id %s", session_id, event_id
            )
            return {"success": True}

        except Exception as exc:
            logger.error(
                "delete_reservation_event failed for session %s, event %s: %s",
                session_id,
                event_id,
                exc,
            )
            return {"success": False, "error": str(exc)}

    def get_authorized_email(self, session_id: str) -> str | None:
        """
        Return the Google email address on file for the given session.

        Args:
            session_id: Unique identifier for the user session.

        Returns:
            The email string, or ``None`` if the session is not found or has
            not been authorised.
        """
        return oauth_store.get_google_email(session_id)


# ---------------------------------------------------------------------------
# Module-level singleton – import and use this directly.
# ---------------------------------------------------------------------------
calendar_service = CalendarService()
