# Araaz Delights – AI-Powered Restaurant Reservation Chatbot

Araaz Delights is an AI-powered restaurant reservation chatbot designed to make table booking easier through natural language conversations. It allows customers to interact with an AI assistant, check table availability, make reservations, retrieve booking details, and cancel reservations.

The project uses Google's Gemini model for conversational intelligence and the Model Context Protocol (MCP) to connect the AI application with restaurant reservation tools through a dedicated MCP server.

## Key Features

- **AI-Powered Conversations:** Natural language interaction using Google's Gemini API.
- **Reservation Management:** Collects customer details and reservation information through conversation.
- **Availability Checking:** Checks table availability for the requested date, time, and number of guests.
- **Alternative Suggestions:** Suggests alternative reservation slots when the requested time is unavailable.
- **Booking Confirmation:** Confirms reservations after customer approval.
- **Reservation Retrieval:** Retrieves existing reservation details.
- **Reservation Cancellation:** Supports cancellation of existing reservations.
- **Conversation Memory:** Maintains session-based conversation context to avoid repeatedly asking for previously provided information.
- **Input Validation and Guardrails:** Validates reservation details and helps prevent invalid or unintended operations.
- **MCP Integration:** Uses an MCP client and server to expose and execute reservation-related tools.
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
| Data Validation | Pydantic |
| HTTP Communication | HTTPX |
| Environment Configuration | python-dotenv |
| Testing | Pytest |

## Project Architecture

The application follows a modular architecture that separates the frontend, chatbot logic, MCP communication, and restaurant reservation operations.

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
                CHATBOT / GEMINI
                       |
                       | Decides when a tool is needed
                       v
                AGENT / TOOLS.PY
                       |
                       v
                 MCP CLIENT
              (agent/mcp_client.py)
                       |
                       | Streamable HTTP
                       | initialize / tool calls
                       v
                  MCP SERVER
                 (mcp_server.py)
                       |
                       v
             RESTAURANT API SERVICE
                       |
                       v
             RESERVATION OPERATIONS
```

### Architecture Explanation

1. **Streamlit Frontend:** Provides the customer-facing chat interface and sends messages to the FastAPI backend.
2. **FastAPI Backend:** Receives requests, manages sessions, and communicates with the chatbot.
3. **Gemini:** Understands customer messages and determines when reservation-related tools are required.
4. **Agent Tools:** Handles the application's reservation operations and routes tool requests through the MCP client.
5. **MCP Client:** Establishes a connection with the MCP server using Streamable HTTP and sends tool execution requests.
6. **MCP Server:** Exposes reservation-related tools and executes the requested operations.
7. **Restaurant API Service:** Handles the underlying reservation operations using the configured backend.

## Model Context Protocol (MCP) Integration

A major part of this project is the implementation of a separate MCP server and MCP client.

The purpose of this implementation is to demonstrate how an AI application can communicate with external tools through a standardized protocol instead of directly coupling the chatbot to every backend operation.

### 1. MCP Server

The MCP server is implemented using FastMCP in `mcp_server.py`.

It exposes the following six tools:

| Tool | Description |
|---|---|
| `test_connection` | Checks whether the MCP server is working. |
| `check_table_availability` | Checks availability for a requested reservation. |
| `create_reservation` | Creates a restaurant reservation. |
| `get_reservation` | Retrieves reservation details. |
| `cancel_reservation` | Cancels an existing reservation. |
| `find_alternative_slots` | Finds alternative available reservation times. |

The MCP server receives tool requests, executes the corresponding operations, and returns the results to the client.

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
Client → Server: initialize
Server → Client: initialization response
```

This establishes the MCP session and allows both sides to begin communicating.

**Step 2 – Discover Available Tools**

The client requests the tools exposed by the server.

```text
Client → Server: tools/list
Server → Client: available tools
```

The client receives the available tool names, descriptions, and input schemas.

**Step 3 – Execute a Tool**

When a tool is required, the client sends a tool execution request.

```text
Client → Server: tools/call
                 Tool name + arguments
```

The MCP server executes the requested operation and returns the result.

**Step 4 – Receive the Result**

```text
Server → Client: tool execution result
```

The client processes the response and makes it available to the application.

Overall, the communication flow is:

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

MCP and Gemini function calling serve different purposes in this application.

**Gemini Function Calling:**

Gemini understands the customer's message and decides when a reservation-related tool needs to be used. It determines the appropriate tool and its arguments based on the conversation.

**Model Context Protocol (MCP):**

MCP provides the communication protocol between the application-side MCP client and the MCP server. It allows the client to discover available tools and execute them through a standardized interface.

In this project, Gemini is responsible for deciding *when and which tool to use*, while MCP handles *how the application communicates with the server to execute that tool*.

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
│   └── restaurant_api.py
│
├── tests/
│   ├── test_availability.py
│   ├── test_guardrails.py
│   ├── test_memory.py
│   └── test_reservation.py
│
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
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root using `.env.example` as a reference.

Example configuration:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

USE_MOCK_BACKEND=true
RESTAURANT_API_BASE_URL=http://localhost:8001
RESTAURANT_API_TIMEOUT_SECONDS=10.0

FASTAPI_HOST=127.0.0.1
FASTAPI_PORT=8000
DEBUG=true

MCP_SERVER_URL=http://127.0.0.1:8001/mcp
```

Update the configuration according to your environment.

**Important:** Keep your actual `.env` file private. Never commit API keys or other secrets to GitHub.

**Backend Configuration:** Configure `RESTAURANT_API_BASE_URL` to point to the restaurant reservation API. Ensure that the restaurant API and MCP server use the correct host and port configurations to avoid conflicts.

## Running the Project

The project uses separate processes for the MCP server, FastAPI backend, and Streamlit frontend.

Open separate terminals for the following steps.

### 1. Start the MCP Server

```bash
python mcp_server.py
```

The MCP server exposes its Streamable HTTP endpoint at:

```text
http://127.0.0.1:8001/mcp
```

### 2. Start the FastAPI Backend

```bash
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

```bash
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

```bash
python test_mcp_client.py
```

The script demonstrates:

1. Connecting to the MCP server.
2. Initializing the MCP session.
3. Discovering available tools using `tools/list`.
4. Executing a tool using `tools/call`.
5. Displaying the returned result.

The demonstration verifies that the MCP client can connect to the server, discover its tools, and successfully execute tool calls.

## Local and Remote MCP Communication

The MCP implementation uses Streamable HTTP, allowing the client and server to run as separate processes and communicate through an HTTP endpoint.

### Local Communication

For local testing, configure:

```env
MCP_SERVER_URL=http://127.0.0.1:8001/mcp
```

Start the MCP server locally and run:

```bash
python test_mcp_client.py
```

### Remote Communication

The MCP server can also be hosted on another machine.

For remote communication:

1. Start the MCP server on the host machine with an externally accessible network interface.
2. Ensure that the required port is accessible through the firewall.
3. Obtain the host machine's LAN IP address if both machines are on the same network, or use a secure tunnel when communicating across different networks.
4. Configure the client machine's `.env` file with the server's reachable URL.

For example:

```env
MCP_SERVER_URL=http://192.168.1.42:8001/mcp
```

For a tunnel-based connection:

```env
MCP_SERVER_URL=https://your-tunnel-domain.example/mcp
```

Run the client demo from the client machine:

```bash
python test_mcp_client.py
```

During this test, the client connects to the independently hosted server. The MCP server does not need to be started locally on the client machine.

**Security Note:** Do not expose an unauthenticated MCP server publicly for longer than necessary. Use appropriate network restrictions and authentication for deployments.

## Testing

The project includes tests for reservation operations, availability, guardrails, and conversation memory.

Run the test suite using:

```bash
python -m pytest -v
```

A separate mock backend test can be executed using:

```bash
python test_mock_backend.py
```

The MCP client-server integration can be tested independently using:

```bash
python test_mcp_client.py
```

## Current Implementation Status

- AI-powered restaurant reservation chatbot implemented.
- Conversation memory and reservation workflow implemented.
- Reservation validation and guardrails implemented.
- FastMCP server exposing six reservation-related tools implemented.
- MCP client implemented using Streamable HTTP.
- MCP client successfully connects to the local MCP server.
- Tool discovery and tool execution successfully tested locally.
- Mock reservation creation, retrieval, and cancellation behavior implemented and tested.

Cross-machine remote MCP verification and clean-environment testing should be completed before treating those deployment checks as fully verified.

## Future Improvements

The following improvements can be considered for future development:

- Complete cross-machine remote MCP testing.
- Add authentication and authorization for remote MCP communication.
- Improve error handling, reconnection, and timeout management.
- Add persistent conversation and reservation storage.
- Improve logging and monitoring for MCP tool execution.
- Add more comprehensive automated integration tests.
- Improve the chatbot's handling of ambiguous customer requests.
- Deploy the application using a production-ready hosting environment.
- Add more restaurant management and reservation-related tools.

## Conclusion

Araaz Delights demonstrates the integration of conversational AI with a modular backend architecture and the Model Context Protocol.

The project combines Gemini-powered natural language understanding, FastAPI, Streamlit, and an MCP client-server implementation to provide a structured approach to restaurant reservation management.

The MCP implementation also serves as a practical demonstration of how an AI application can discover and execute external tools through a standardized client-server protocol.