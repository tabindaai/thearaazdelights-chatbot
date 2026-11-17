# Araaz Delights – AI-Powered Restaurant Reservation Chatbot

Araaz Delights is an AI-powered restaurant reservation chatbot designed to simplify table booking through natural language conversations.

Customers can interact with an AI assistant to check table availability, make reservations, retrieve booking details, update existing reservations, find alternative time slots, and cancel reservations.

The project uses Google's Gemini model for conversational intelligence and the Model Context Protocol (MCP) to connect the AI application with reservation-management tools through a dedicated MCP client-server architecture.

PostgreSQL provides persistent reservation storage, while the application also supports an in-memory mock backend and an external HTTP API backend.

## Key Features

- **AI-Powered Conversations:** Natural language interaction using Google's Gemini API.
- **Reservation Management:** Collects customer names, dates, times, guest counts, and seating preferences through conversation.
- **Availability Checking:** Checks table availability for the requested date, time, and number of guests.
- **Alternative Suggestions:** Suggests alternative reservation slots when the requested time is unavailable.
- **Booking Confirmation:** Creates reservations after customer approval.
- **Reservation Retrieval:** Retrieves existing reservation details.
- **Reservation Updating:** Allows customers to modify existing reservation details.
- **Reservation Cancellation:** Supports cancellation of existing reservations.
- **Conversation Memory:** Maintains session-based conversation context to avoid repeatedly asking for previously provided information.
- **Input Validation and Guardrails:** Validates reservation details and helps prevent invalid or unintended operations.
- **MCP Integration:** Uses a dedicated MCP client and server for reservation-related tool execution.
- **PostgreSQL Persistence:** Stores confirmed reservations in a PostgreSQL database.
- **Multiple Backend Modes:** Supports PostgreSQL, an external HTTP API, and an in-memory mock backend.
- **Streamlit Interface:** Provides a user-friendly chat interface.

## Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| AI Model | Google Gemini |
| AI Integration | Google GenAI SDK |
| Backend API | FastAPI |
| Frontend | Streamlit |
| MCP Framework | MCP Python SDK / FastMCP |
| MCP Transport | Streamable HTTP |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Database Driver | Psycopg |
| Data Validation | Pydantic |
| HTTP Communication | HTTPX |
| Environment Configuration | python-dotenv |
| Testing | Pytest |

## Project Architecture

The application follows a modular architecture that separates the frontend, chatbot logic, MCP communication, reservation operations, and database persistence.

### Architecture Diagram

```text
                    CUSTOMER
                       |
                       v
              STREAMLIT FRONTEND
                       |
                       v
                FASTAPI BACKEND
                       |
                       v
                 GEMINI AI AGENT
                       |
                       v
                 AGENT / TOOLS.PY
                       |
                       v
              MCP CLIENT
           (agent/mcp_client.py)
                       |
                       | Streamable HTTP
                       v
                 MCP SERVER
                (mcp_server.py)
                       |
                       v
            RESTAURANT API SERVICE
          (services/restaurant_api.py)
                       |
             +---------+----------+
             |         |          |
             v         v          v
         PostgreSQL  HTTP API   Mock Backend
           Backend   Backend   (In-Memory)
             |
             v
       SQLAlchemy ORM
             |
             v
       PostgreSQL Database
```

### Architecture Explanation

1. **Streamlit Frontend:** Provides the customer-facing chat interface and sends messages to the FastAPI backend.
2. **FastAPI Backend:** Receives requests, manages sessions, and communicates with the chatbot.
3. **Gemini AI Agent:** Understands customer messages and determines when reservation-related tools are required.
4. **Agent Tools:** Handles reservation operations and routes tool requests through the MCP client.
5. **MCP Client:** Establishes a connection with the MCP server using Streamable HTTP and sends tool execution requests.
6. **MCP Server:** Exposes reservation-related tools and executes requested operations.
7. **Restaurant API Service:** Handles reservation operations and selects the configured backend.
8. **PostgreSQL Backend:** Uses SQLAlchemy to store and retrieve persistent reservation records.

The chatbot's reservation operations communicate with the restaurant backend through MCP. The AI agent does not directly access PostgreSQL.

## Model Context Protocol (MCP) Integration

A major part of this project is the implementation of a separate MCP server and MCP client.

The purpose is to demonstrate how an AI application can communicate with external tools through a standardized protocol instead of directly coupling chatbot logic to backend operations.

### 1. MCP Server

The MCP server is implemented using FastMCP in `mcp_server.py`.

It exposes seven tools:

| Tool | Description |
|---|---|
| `test_connection` | Checks whether the MCP server is working. |
| `check_table_availability` | Checks availability for a requested reservation. |
| `create_reservation` | Creates a restaurant reservation. |
| `get_reservation` | Retrieves reservation details. |
| `cancel_reservation` | Cancels an existing reservation. |
| `find_alternative_slots` | Finds alternative available reservation times. |
| `update_reservation` | Updates an existing reservation. |

The MCP server receives tool requests, executes the corresponding operations through the restaurant API service, and returns the results to the client.

### 2. MCP Client

The MCP client is implemented in `agent/mcp_client.py`.

Its responsibilities include:

- Connecting to the MCP server through its configured URL.
- Establishing an MCP session.
- Initializing the protocol connection.
- Sending tool execution requests.
- Receiving and processing tool results.
- Maintaining a persistent connection for multiple tool calls.
- Closing the connection gracefully.

The server URL is configured through the `MCP_SERVER_URL` environment variable.

### 3. MCP Communication Flow

The MCP communication follows these steps:

**Step 1 – Initialize**

The client connects to the MCP server and sends an initialization request.

```text
Client -> Server: initialize
Server -> Client: initialization response
```

**Step 2 – Discover Available Tools**

The client requests the tools exposed by the server.

```text
Client -> Server: tools/list
Server -> Client: available tools
```

**Step 3 – Execute a Tool**

When a reservation operation is required, the client sends a tool execution request.

```text
Client -> Server: tools/call
                 Tool name + arguments
```

**Step 4 – Receive the Result**

```text
Server -> Client: tool execution result
```

The client processes the response and makes it available to the application.

Overall:

```text
initialize
    |
    v
tools/list
    |
    v
tools/call
    |
    v
tool execution
    |
    v
result returned to client
```

### 4. MCP vs Gemini Function Calling

MCP and Gemini function calling serve different purposes.

**Gemini Function Calling:**

Gemini understands the customer's message and determines when a reservation-related tool needs to be used. It identifies the appropriate tool and its arguments based on the conversation.

**Model Context Protocol:**

MCP provides the communication protocol between the application-side MCP client and the MCP server. It allows the client to discover available tools and execute them through a standardized interface.

In this project, Gemini determines **when and which tool to use**, while MCP handles **how the application communicates with the server to execute that tool**.

## Database Integration and Persistence

The project uses PostgreSQL for persistent reservation storage.

Database connection and session management are implemented in:

- `services/db.py`
- `services/models.py`

The database operations are integrated into `services/restaurant_api.py`.

SQLAlchemy is used as the ORM, and Psycopg is used as the PostgreSQL driver.

### Reservation Model

The `reservations` table stores reservation information, including:

- Reservation ID
- Customer name
- Customer phone and email (optional)
- Restaurant ID
- Reservation date and time
- Guest count
- Seating preference
- Special requests
- Table number
- Reservation status
- Hold token
- Creation and update timestamps

### Reservation Persistence

Confirmed reservations are stored in PostgreSQL and remain available after the MCP server restarts.

Cancellation uses a status update rather than permanently deleting the reservation record. This preserves the reservation history.

### Temporary Availability Holds

When a table availability check succeeds, the backend generates a temporary hold token.

- Holds expire after 10 minutes.
- Temporary holds are maintained in process memory.
- Confirmed reservations are persisted in PostgreSQL.
- Temporary holds are not intended to survive an MCP server restart.

This separates temporary availability management from permanent reservation storage.

## Backend Configuration Modes

The restaurant API service supports three backend modes.

### 1. PostgreSQL Mode

PostgreSQL mode provides persistent reservation storage.

It is selected when:

```env
USE_MOCK_BACKEND=false
```

and valid PostgreSQL database configuration is available.

### 2. External HTTP API Mode

If mock mode is disabled but PostgreSQL is not configured, the service can use the colleague's external restaurant HTTP API.

Configure its base URL using:

```env
RESTAURANT_API_BASE_URL=http://localhost:8002
```

### 3. Mock Backend Mode

Mock mode uses in-memory storage and does not require a PostgreSQL connection.

Enable it using:

```env
USE_MOCK_BACKEND=true
```

Mock reservation data is temporary and is not persisted across application restarts.

## Project Structure

```text
thearaazdelights-chatbot/
│
├── agent/
│   ├── chatbot.py
│   ├── guardrails.py
│   ├── mcp_client.py
│   ├── memory.py
│   ├── prompts.py
│   └── tools.py
│
├── frontend/
│   └── app.py
│
├── schemas/
│   ├── chat.py
│   └── reservation.py
│
├── services/
│   ├── db.py
│   ├── models.py
│   └── restaurant_api.py
│
├── tests/
│   ├── test_availability.py
│   ├── test_guardrails.py
│   ├── test_memory.py
│   └── test_reservation.py
│
├── create_tables.py
├── main.py
├── mcp_server.py
├── test_mcp_client.py
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/tabindaai/thearaazdelights-chatbot.git
cd thearaazdelights-chatbot
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure PostgreSQL

Install and start PostgreSQL.

Create a database named:

```sql
CREATE DATABASE araaz_delights;
```

The application uses environment variables to establish the database connection.

### 5. Configure Environment Variables

Create a `.env` file in the project root using `.env.example` as a reference.

Example configuration:

```env
# Gemini Configuration
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash-lite

# Backend Selection
USE_MOCK_BACKEND=false

# PostgreSQL Configuration
DB_USER=postgres
DB_PASSWORD=your_database_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=araaz_delights

# External Restaurant API
RESTAURANT_API_BASE_URL=http://localhost:8002
RESTAURANT_API_TIMEOUT_SECONDS=10.0

# MCP Configuration
MCP_SERVER_URL=http://127.0.0.1:8001/mcp
```

Alternatively, database configuration can use a `DATABASE_URL` if supported by the deployment environment.

**Important:** Replace the example values with your own configuration. Never commit your actual `.env` file, API keys, or database passwords to GitHub.

### 6. Create Database Tables

After configuring PostgreSQL, run:

```powershell
python create_tables.py
```

This creates the reservation table using the SQLAlchemy models if it does not already exist.

## Running the Project

The project uses separate processes for the MCP server, FastAPI backend, and Streamlit frontend.

Open separate terminals for the following steps.

### 1. Start the MCP Server

```powershell
python mcp_server.py
```

The MCP server exposes its Streamable HTTP endpoint at:

```text
http://127.0.0.1:8001/mcp
```

### 2. Start the FastAPI Backend

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

The FastAPI application runs at:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/health
```

### 3. Start the Streamlit Frontend

```powershell
streamlit run frontend/app.py
```

The frontend is generally available at:

```text
http://localhost:8501
```

Once all three processes are running, customers can interact with the chatbot through the Streamlit interface.

## Running the MCP Client Demo

A standalone demonstration script is included to test MCP client-server communication independently of the chatbot interface.

Make sure the MCP server is running, then execute:

```powershell
python test_mcp_client.py
```

The script demonstrates:

1. Connecting to the MCP server.
2. Initializing the MCP session.
3. Discovering available tools.
4. Executing an MCP tool.
5. Displaying the returned result.

## Local and Remote MCP Communication

The MCP implementation uses Streamable HTTP, allowing the client and server to run as separate processes and communicate through an HTTP endpoint.

### Local Communication

For local testing:

```env
MCP_SERVER_URL=http://127.0.0.1:8001/mcp
```

Start the MCP server locally and run:

```powershell
python test_mcp_client.py
```

### Remote Communication

The MCP server can also be hosted on another machine.

For remote communication:

1. Start the MCP server on the host machine with an externally accessible network interface.
2. Ensure that the required port is accessible through the firewall.
3. Configure the client with the server's reachable URL.
4. Use appropriate network restrictions and authentication before exposing the service outside a trusted environment.

Example LAN configuration:

```env
MCP_SERVER_URL=http://192.168.1.42:8001/mcp
```

A secure tunnel or HTTPS endpoint can be used for communication across different networks.

**Security Note:** The current MCP implementation is intended for development and proof-of-concept use. Do not expose an unauthenticated MCP server publicly. Add authentication, authorization, and appropriate network security before production deployment.

## Testing

Test MCP client-server communication independently using:

```powershell
python test_mcp_client.py
```

### Integration Verification

The PostgreSQL and MCP integration has also been manually verified through the application.

The verification covered:

- PostgreSQL connection and reservation table creation.
- Table availability checking.
- Reservation creation.
- Reservation retrieval.
- Reservation updating.
- Alternative slot discovery.
- Reservation cancellation.
- Retrieval of cancelled reservation records.
- MCP client connection and tool discovery.
- Reservation persistence after restarting the MCP server.
- Mock backend initialization, availability checking, and reservation creation.

The mock backend checks were performed directly through the restaurant API client. The PostgreSQL reservation workflow was tested through the MCP client and `AgentTools`.

## Current Implementation Status

The following functionality has been implemented and verified:

- AI-powered restaurant reservation chatbot.
- Gemini-based conversational interaction.
- Session-based conversation memory.
- Reservation validation and guardrails.
- FastMCP server exposing seven tools.
- MCP client using Streamable HTTP.
- MCP tool discovery and execution.
- MCP-only communication from `agent/tools.py`.
- PostgreSQL database integration using SQLAlchemy.
- Persistent reservation creation and retrieval.
- Reservation updating and cancellation.
- Alternative availability suggestions.
- Mock backend initialization and reservation creation.
- Confirmed reservation persistence after an MCP server restart.

Cross-machine remote MCP verification and production security hardening remain future deployment tasks.

## Future Improvements

- Complete cross-machine remote MCP testing.
- Add authentication and authorization for remote MCP communication.
- Improve error handling, automatic reconnection, and timeout management.
- Add persistent conversation memory.
- Improve logging and monitoring for MCP tool execution.
- Expand automated integration test coverage.
- Improve handling of ambiguous customer requests.
- Add production-ready deployment and monitoring.
- Introduce additional restaurant management tools.

## Conclusion

Araaz Delights demonstrates the integration of conversational AI with a modular backend architecture and the Model Context Protocol.

The project combines Gemini-powered natural language understanding, FastAPI, Streamlit, MCP client-server communication, SQLAlchemy, and PostgreSQL to provide a structured restaurant reservation system.

It also demonstrates how an AI application can discover and execute external tools through a standardized protocol while keeping backend operations separate from conversational logic.
