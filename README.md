# The Araaz Delights – AI-Powered Restaurant Reservation Chatbot with Google Calendar MCP Integration

The Araaz Delights is an AI-powered restaurant reservation concierge designed to handle table bookings through natural, human-like conversations. Powered by Google's Gemini model and an AI assistant named **Aria**, the system guides guests through checking table availability, selecting preferences, confirming bookings, and automatically synchronizing reservations with their personal **Google Calendar** with an automated **3-hour reminder**.

The architecture uses the **Model Context Protocol (MCP)** to connect conversational AI to backend tools through a **single unified MCP client** communicating over Streamable HTTP with two independent MCP servers: the **Restaurant MCP Server** (for table bookings) and the **Google Calendar MCP Server** (for calendar event management).

---

## Table of Contents

- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [Project Folder Structure](#project-folder-structure)
- [How the Unified MCP Client Connects to Both Servers](#how-the-unified-mcp-client-connects-to-both-servers)
- [Customer Email Collection & Validation](#customer-email-collection--validation)
- [Google OAuth 2.0 Authorization Flow](#google-oauth-20-authorization-flow)
- [Automatic Calendar Synchronization](#automatic-calendar-synchronization)
- [3-Hour (180-Minute) Reminder Configuration](#3-hour-180-minute-reminder-configuration)
- [Reservation Update & Cancellation Synchronization](#reservation-update--cancellation-synchronization)
- [Database Schema & Migrations](#database-schema--migrations)
- [Google Cloud Project & Calendar API Setup](#google-cloud-project--calendar-api-setup)
- [Installation and Environment Configuration](#installation-and-environment-configuration)
- [Running the Complete System](#running-the-complete-system)
- [Testing & Verification](#testing--verification)
- [Security Considerations](#security-considerations)

---

## Key Features

- **Natural AI Concierge (Aria):** Understands greetings (*hello, hi, namaste*), relative dates (*tomorrow, next Friday*), natural times (*7 PM, 19:30*), polite acknowledgments, and conversation closings.
- **Mandatory Email Collection:** Collects customer name, email address, reservation date, time, and guest count naturally without repetitive questioning. Phone number is strictly optional.
- **Table Availability Checking:** Verifies real-time table capacity and returns alternative slots when a preferred time is booked out.
- **Two Independent MCP Servers:** Separates restaurant database operations (Port `8001`) from Google Calendar operations (Port `8002`).
- **Single Unified MCP Client (`agent/mcp_client.py`):** A single persistent bridge managing concurrent connections to both MCP servers with automatic tool routing and fault isolation.
- **Customer Google Calendar Integration:** Connects the customer's personal Google account using secure Google OAuth 2.0 authorization.
- **Automatic 3-Hour Reminders:** Schedules a Google Calendar popup reminder exactly **180 minutes** before the reservation time.
- **Full Life-Cycle Calendar Sync:** Updating a reservation updates the calendar event; cancelling a reservation deletes the calendar event.
- **Decoupled & Optional Calendar:** Restaurant reservations always succeed even if the guest has not connected Google Calendar or if calendar services are temporarily offline.
- **PostgreSQL & In-Memory Mock Modes:** Seamlessly toggles between PostgreSQL database persistence, external colleague HTTP backend, and an in-memory mock backend.
- **Streamlit Interactive UI:** Customer-facing chat interface featuring real-time booking state, sidebar session reset, and one-click Google Calendar connection.

---

## Technology Stack

| Component | Technology | Description |
|---|---|---|
| **Programming Language** | Python 3.11+ / 3.13 | Core runtime environment |
| **Conversational AI** | Google Gemini (`gemini-2.5-flash` / `gemini-3.5-flash-lite`) | Natural language understanding & function calling |
| **AI SDK** | Google GenAI SDK (`google-genai`) | Official client for system prompts and tool calling |
| **Backend API** | FastAPI + Uvicorn | REST endpoints for chat, session management, and OAuth |
| **Frontend UI** | Streamlit | Responsive customer chat interface and sidebar controls |
| **Protocol Architecture** | Model Context Protocol (MCP) | Standardized client-server tool execution protocol |
| **MCP Framework** | FastMCP (`mcp` Python SDK) | Lightweight Streamable HTTP servers |
| **Calendar API** | Google Calendar API v3 | `google-api-python-client`, `google-auth-oauthlib` |
| **Database (Reservations)** | PostgreSQL + SQLAlchemy 2.0 | Persistent reservation storage |
| **Database (OAuth Tokens)** | SQLite (`oauth_tokens.db`) | Dedicated server-side token store with thread locks |
| **Validation & Schemas** | Pydantic v2 | Schema enforcement and runtime data validation |
| **Testing** | Pytest + Pytest-Asyncio | Unit and integration test suite |

---

## System Architecture

The application implements a clean separation of concerns: conversational orchestration, tool execution protocol, business domain, and external service layers.

### Architecture Diagram

```mermaid
flowchart TD
    User([Customer / Guest]) <--> UI[Streamlit Frontend\n:8501]
    UI <--> API[FastAPI Backend\nmain.py :8000]
    API <--> Agent[Gemini AI Concierge\nagent/chatbot.py]
    Agent <--> Tools[Agent Tools Bridge\nagent/tools.py]
    
    Tools <--> MCPClient[Unified MCP Client\nagent/mcp_client.py]
    
    MCPClient <-- Streamable HTTP :8001 --> RestMCP[Restaurant MCP Server\nmcp_server.py :8001]
    MCPClient <-- Streamable HTTP :8002 --> CalMCP[Google Calendar MCP Server\ncalendar_mcp_server.py :8002]
    
    RestMCP <--> RestAPI[Restaurant API Service\nservices/restaurant_api.py]
    RestAPI <--> DB[(PostgreSQL Database\nreservations table)]
    
    CalMCP <--> CalService[Calendar Service\nservices/calendar_service.py]
    CalService <--> OAuthStore[(SQLite Store\noauth_tokens.db)]
    CalService <--> GCalAPI[Google Calendar API v3\naccounts.google.com / Google Cloud]
```

### Flow Summary

1. **Guest interacts with Streamlit:** Messages are sent via HTTP POST `/chat` to FastAPI.
2. **FastAPI & Agent:** FastAPI routes messages into `RestaurantChatbotAgent`, evaluating input guardrails, dynamic system prompts, and conversation history.
3. **Gemini Tool Calling:** Gemini decides which tools to invoke (`check_table_availability`, `update_reservation_details`, `create_reservation`, etc.).
4. **AgentTools Execution:** `AgentTools` passes tool calls to `call_mcp_tool()`.
5. **Unified MCP Client Routing:** `agent/mcp_client.py` determines whether the tool belongs to the restaurant domain or calendar domain, routing it to Port `8001` or Port `8002`.
6. **Backend Execution:**
   - Restaurant tools execute against PostgreSQL/mock database via `services/restaurant_api.py`.
   - Calendar tools execute against Google Calendar API using stored OAuth tokens via `services/calendar_service.py`.

---

## Project Folder Structure

```text
restaurant_ai_chatbot/
│
├── agent/
│   ├── __init__.py
│   ├── chatbot.py              # Gemini conversational orchestrator & tool execution loop
│   ├── guardrails.py           # Input sanitization, email validation, and topic filters
│   ├── mcp_client.py           # Unified persistent MCP client connecting to both servers
│   ├── memory.py               # Session memory, FSM states, and ReservationDraft
│   ├── prompts.py              # Dynamic system prompt builder with runtime context
│   └── tools.py                # AgentTools binding session logic to MCP calls
│
├── frontend/
│   └── app.py                  # Streamlit chat interface with Google Calendar sidebar controls
│
├── schemas/
│   ├── __init__.py
│   ├── chat.py                 # Pydantic models for chat requests and responses
│   └── reservation.py          # Data validation models for availability and bookings
│
├── services/
│   ├── __init__.py
│   ├── calendar_service.py     # Google Calendar API v3 client (CRUD & 3-hour reminder)
│   ├── db.py                   # SQLAlchemy engine, session maker, and connection logic
│   ├── models.py               # SQLAlchemy models (Reservation with calendar_event_id)
│   ├── oauth_store.py          # SQLite token store for Google OAuth tokens
│   └── restaurant_api.py       # Restaurant backend service (PostgreSQL, mock, HTTP)
│
├── tests/
│   ├── __init__.py
│   ├── test_availability.py    # Availability and capacity limit unit tests
│   ├── test_guardrails.py      # Input, email, and confirmation gate guardrail tests
│   ├── test_memory.py          # Multi-turn memory and draft accumulation tests
│   └── test_reservation.py     # End-to-end booking scenarios
│
├── calendar_mcp_server.py      # FastMCP Google Calendar server (port 8002)
├── create_tables.py            # PostgreSQL database table initialization script
├── main.py                     # FastAPI backend application with OAuth routes
├── mcp_server.py               # FastMCP Restaurant server (port 8001)
├── test_mcp_client.py          # Standalone MCP client testing demo script
├── verify_get_reservation.py   # MCP restart persistence verification script
├── requirements.txt            # Python package dependencies
├── .env.example                # Safe environment variable configuration template
├── .gitignore
└── README.md
```

---

## How the Unified MCP Client Connects to Both Servers

A key design requirement is **one unified MCP client** (`agent/mcp_client.py`) rather than separate disconnected client files.

### 1. Dual Persistent Sessions
`MCPClient` runs an isolated background thread with its own asyncio event loop. When initialized, it establishes two concurrent Streamable HTTP protocol sessions:
- **`restaurant_session`** connected to `http://127.0.0.1:8001/mcp`
- **`calendar_session`** connected to `http://127.0.0.1:8002/mcp`

### 2. Intelligent Tool Routing
When `call_mcp_tool(tool_name, arguments)` is invoked, the client checks the target tool against a registered set of calendar tools:

```python
CALENDAR_TOOLS = {
    "test_calendar_connection",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
}
```

- If `tool_name in CALENDAR_TOOLS`: Routed directly to the **Calendar MCP Server** (Port `8002`).
- Otherwise: Routed to the **Restaurant MCP Server** (Port `8001`).

### 3. Fault Isolation & Auto-Reconnection
- If the Calendar MCP server is not running or offline, calendar operations fail gracefully with a descriptive error dict, **without raising unhandled exceptions or interrupting restaurant bookings**.
- If either server is restarted, the client automatically attempts on-demand reconnection during the next tool call.

---

## Customer Email Collection & Validation

Aria collects the customer's email address as a mandatory detail before confirming the reservation.

### Mandatory Booking Details
1. **Customer Name**
2. **Customer Email Address** (required for confirmation and Google Calendar reminders)
3. **Reservation Date** (`YYYY-MM-DD`)
4. **Reservation Time** (`HH:MM` 24-hour format)
5. **Number of Guests** (`1` to `20`)

*Phone number is strictly optional.*

### Validation & Behavior
- **Regex Format Validation:** Evaluated by `Guardrails.validate_email()`:
  ```regex
  ^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$
  ```
- **Context-Aware Topic Guard:** Email addresses provided naturally (e.g. `arun.kumar@gmail.com` or `my email is test@domain.com`) are recognized as valid detail answers and are never blocked as off-topic.
- **Correction Support:** Customers can update or correct their email address at any point before confirmation.
- **Privacy:** Email addresses are never exposed in system error logs or leaked to third-party endpoints.

---

## Google OAuth 2.0 Authorization Flow

To save confirmed bookings directly into the customer's own Google Calendar, the application implements a secure OAuth 2.0 Authorization Code Flow.

### Sequence of Authorization

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant UI as Streamlit (:8501)
    participant API as FastAPI (:8000)
    participant Google as Google Accounts
    participant DB as SQLite (oauth_tokens.db)

    Customer->>UI: Clicks "Connect Google Calendar"
    UI->>API: GET /auth/google?session_id=XYZ
    API->>API: Generates CSRF state token
    API-->>Customer: 307 Redirect to Google Consent Screen
    Customer->>Google: Authenticates & grants calendar.events scope
    Google-->>API: 302 Redirect to /auth/callback?code=...&state=...
    API->>API: Validates state against active session
    API->>Google: Exchanges code for access & refresh tokens
    Google-->>API: Returns tokens + ID token
    API->>DB: Stores encrypted tokens & user's Google email
    API-->>UI: Redirects to :8501?oauth_success=1
    UI->>UI: Updates sidebar: "Connected as user@gmail.com"
```

### OAuth Endpoints in `main.py`

| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/google` | `GET` | Initiates flow; generates CSRF `state`, maps to `session_id`, redirects to Google consent URL. |
| `/auth/callback` | `GET` | Callback handler; validates `state`, exchanges `code` for tokens, stores tokens, redirects back to Streamlit. |
| `/auth/status/{session_id}` | `GET` | Returns connection status, authorized Google email, and token validity for a session. |
| `/auth/disconnect/{session_id}` | `POST` | Revokes stored tokens and clears session calendar authorization. |

### Email Mismatch Handling
If the Google account authorized via OAuth differs from the email collected during conversation (e.g., booked for `work@company.com`, but authorized Google account is `personal@gmail.com`), Aria explicitly communicates which account holds the event:
> *"Saved to your calendar (saved to connected Google account: `personal@gmail.com`) with a reminder 3 hours before!"*

---

## Automatic Calendar Synchronization

Once the restaurant backend confirms a table booking, the application triggers calendar synchronization:

1. **Pre-condition:** `create_reservation` returns `status == "confirmed"`.
2. **Authorization Check:** The system verifies `session.google_calendar_authorized`.
3. **Event Body Structure:**
   - **Summary:** `Restaurant Reservation - Araaz Delights`
   - **Start Time:** Reservation date & time in ISO-8601 with configured timezone (`CALENDAR_TIMEZONE`).
   - **End Time:** Automatically calculated as 2 hours after start time.
   - **Location:** `The Araaz Delights, 123 Fine Dining Avenue`
   - **Description:** Clean summary containing Reservation ID, Guest Name, Guest Email, Party Size, Seating Preference, and Special Requests.
   - **Duplicate Prevention:** The generated Google Calendar `event_id` is saved to `session.last_confirmed_calendar_event_id` and database column `calendar_event_id`. Subsequent calls detect the existing ID and do not create duplicates.

---

## 3-Hour (180-Minute) Reminder Configuration

### Reminder Setting
The event reminder is configured within the event creation payload:

```python
"reminders": {
    "useDefault": False,
    "overrides": [
        {"method": "popup", "minutes": 180}
    ]
}
```

### Explanation of Notification Types
- **Calendar Event Reminders (Implemented):** Configured via the `reminders.overrides` property with `method: "popup"` and `minutes: 180`. These trigger notifications on the customer's mobile device and desktop Google Calendar app 3 hours prior to the reservation.
- **Email Notifications:** Configured using `method: "email"` in the reminder overrides. Sends a reminder email directly to the customer's Gmail inbox.
- **Calendar Event Invitations:** Involves adding attendees to the event (`attendees: [{"email": "..."}]`). Google automatically sends an RSVP invitation email asking the guest to Accept/Decline.

> **Important Delivery Note:** Actual popup delivery depends on the customer's Google Calendar settings, operating system notification permissions, and mobile notification toggles. Aria does not claim an event has been saved unless the Calendar MCP tool execution succeeds.

---

## Reservation Update & Cancellation Synchronization

### 1. Reservation Updates
When a customer changes date, time, party size, or seating preference:
- The restaurant reservation is updated via `update_reservation`.
- If an associated `calendar_event_id` exists, `AgentTools.sync_calendar_on_update()` calls `update_calendar_event` on the Calendar MCP server.
- The event's start time, end time, and description are updated, **while the 3-hour popup reminder is strictly preserved**.

### 2. Reservation Cancellations
When a customer cancels a reservation:
- The restaurant backend marks the reservation status as `cancelled`.
- If an associated `calendar_event_id` exists, `AgentTools.sync_calendar_on_cancel()` calls `delete_calendar_event` on the Calendar MCP server.
- The event is removed from the customer's Google Calendar, and `last_confirmed_calendar_event_id` is cleared.

### 3. Failure Independence
If a calendar update or deletion fails (e.g. Google API rate limits or network issues), **it never rolls back or invalidates the confirmed restaurant reservation**. The customer is simply informed of the calendar sync notice.

---

## Database Schema & Migrations

### 1. PostgreSQL `reservations` Table

The `reservations` table schema in `services/models.py`:

```python
class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    restaurant_id: Mapped[str] = mapped_column(String(100), nullable=False, default="rest_01")
    reservation_date: Mapped[date] = mapped_column(Date, nullable=False)
    reservation_time: Mapped[time] = mapped_column(Time, nullable=False)
    guest_count: Mapped[int] = mapped_column(Integer, nullable=False)
    seating_preference: Mapped[str | None] = mapped_column(String(30), nullable=True)
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="confirmed")
    hold_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
```

#### Migration for Existing Databases
If updating an existing PostgreSQL database instance, execute the following SQL:

```sql
ALTER TABLE reservations ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(255);
```

### 2. SQLite OAuth Token Store (`oauth_tokens.db`)

OAuth credentials are kept in a separate, local SQLite database (`oauth_tokens.db`) managed by `services/oauth_store.py`. This ensures token storage remains independent from PostgreSQL and functions identically in mock backend mode.

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    session_id    TEXT PRIMARY KEY,
    access_token  TEXT,
    refresh_token TEXT,
    token_expiry  TEXT,
    google_email  TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
```

---

## Google Cloud Project & Calendar API Setup

To enable Google Calendar synchronization, set up an OAuth 2.0 Web Application in Google Cloud:

### 1. Create Google Cloud Project
1. Visit the [Google Cloud Console](https://console.cloud.google.com/).
2. Click **Select a project** > **New Project**, name it `Araaz Delights`, and click **Create**.

### 2. Enable Google Calendar API
1. Navigate to **APIs & Services** > **Library**.
2. Search for `Google Calendar API`.
3. Select it and click **Enable**.

### 3. Configure OAuth Consent Screen
1. Go to **APIs & Services** > **OAuth consent screen**.
2. Select **External** user type and click **Create**.
3. Fill in the App Name (*The Araaz Delights*), User Support Email, and Developer Contact Information.
4. Under **Scopes**, click **Add or Remove Scopes** and add:
   - `https://www.googleapis.com/auth/calendar.events`
5. Under **Test Users**, add the personal Google email address you will use for testing.
6. Save and finish.

### 4. Create OAuth Client Credentials
1. Go to **APIs & Services** > **Credentials**.
2. Click **Create Credentials** > **OAuth client ID**.
3. Set Application Type to **Web application**.
4. Set Name to `Araaz Delights Client`.
5. Under **Authorized redirect URIs**, add:
   - `http://localhost:8000/auth/callback`
6. Click **Create** and copy your **Client ID** and **Client Secret**.

---

## Installation and Environment Configuration

### 1. Clone the Repository

```bash
git clone https://github.com/tabindaai/thearaazdelights-chatbot.git
cd thearaazdelights-chatbot
```

### 2. Create and Activate Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root based on `.env.example`:

```env
# ========================================================
# Google Gemini API Configuration
# Get your key from: https://aistudio.google.com/
# ========================================================
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite

# ========================================================
# Restaurant Backend Configuration
# Set USE_MOCK_BACKEND=true for local in-memory development
# ========================================================
USE_MOCK_BACKEND=true
RESTAURANT_API_BASE_URL=http://localhost:8003
RESTAURANT_API_TIMEOUT_SECONDS=10.0

# ========================================================
# Application Settings
# ========================================================
FASTAPI_HOST=127.0.0.1
FASTAPI_PORT=8000
DEBUG=true

# ========================================================
# MCP Server Configuration
# ========================================================
# Restaurant MCP Server (port 8001)
MCP_SERVER_URL=http://127.0.0.1:8001/mcp

# Google Calendar MCP Server (port 8002)
CALENDAR_MCP_SERVER_URL=http://127.0.0.1:8002/mcp

# ========================================================
# Google Calendar OAuth 2.0 Configuration
# ========================================================
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
CALENDAR_TIMEZONE=Asia/Kolkata

# ========================================================
# Optional PostgreSQL Database Configuration
# ========================================================
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/araaz_delights
```

---

## Running the Complete System

The system operates across **four modular processes**. Open separate terminals for each:

### Terminal 1: Start the Restaurant MCP Server
```powershell
python mcp_server.py
```
*Listens on `http://127.0.0.1:8001/mcp`.*

### Terminal 2: Start the Google Calendar MCP Server
```powershell
python calendar_mcp_server.py
```
*Listens on `http://127.0.0.1:8002/mcp`.*

### Terminal 3: Start the FastAPI Backend
```powershell
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
*Listens on `http://127.0.0.1:8000` (Health check: `/health`).*

### Terminal 4: Start the Streamlit Frontend
```powershell
streamlit run frontend/app.py
```
*Opens chat interface at `http://localhost:8501`.*

---

## Testing & Verification

### Run Automated Unit Tests

```powershell
.venv\Scripts\python.exe -m pytest
```

### Standalone MCP Communication Test
To test the restaurant MCP server independently:
```powershell
python test_mcp_client.py
```

### Persistence Verification Test
To verify reservation persistence across MCP server restarts:
```powershell
python verify_get_reservation.py
```

---

## Security Considerations

1. **Least-Privilege Scopes:** The application only requests the narrow `https://www.googleapis.com/auth/calendar.events` scope. It does not request access to contacts, profile data, or Gmail.
2. **Server-Side Token Storage:** Access and refresh tokens are stored exclusively in the server-side SQLite token database. Tokens are never transmitted to the Streamlit frontend.
3. **No Password Prompting:** Aria will never ask customers for their Google passwords. All authentication occurs on Google's official sign-in page.
4. **Log Sanitization:** Sensitive tokens, client secrets, and user credentials are scrubbed from structured log outputs.
5. **CSRF State Validation:** OAuth 2.0 authorization codes are bound to single-use cryptographically random `state` parameters to protect against cross-site request forgery.
6. **Graceful Degeneration:** A failure in Google Calendar communication never causes data loss in the restaurant reservation system.
