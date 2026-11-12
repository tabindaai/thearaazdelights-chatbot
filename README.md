# 🍽️ AI-Powered Restaurant Reservation Chatbot

An intelligent, multi-turn AI Concierge for restaurant table reservations, built with **Python 3.13**, **FastAPI**, **Streamlit**, and **Google Gemini** (using the official modern `google-genai` SDK with native tool calling).

Designed following professional software engineering principles: strict decoupling between the AI agent orchestration layer and the backend database/APIs.

---

## 🌟 Key Capabilities

- **Natural Language Dialogue**: Understands messy, multi-turn requests like *"Table for 4 tomorrow evening, outdoor if possible"*.
- **Native Gemini Function Calling**: Automatically decides when to update draft parameters, check table availability, propose alternatives, or execute bookings.
- **Strict Booking Confirmation Guardrail**: The AI can **never** commit a reservation without explicit, affirmative verbal confirmation from the customer.
- **Stale State Invalidation**: If a customer modifies party size or time after checking availability or confirming, all prior tokens are invalidated and re-verified.
- **Multi-Layer Guardrails**: Protects against empty input, buffer-length attacks, prompt injection (jailbreak defense), past dates, party-size limits (1–20), and scrubs internal stack traces/keys from outputs.

---

## 📁 Project Architecture

```
restaurant_ai_chatbot/
│
├── main.py                     # FastAPI entry point (/chat, /health, /session)
├── pytest.ini                  # Pytest configuration
├── requirements.txt            # Pinned production dependencies
├── .env.example                # Environment variable template
├── .env                        # Local runtime secrets
│
├── agent/                      # Core AI Agent Engine
│   ├── chatbot.py              # Gemini GenAI tool-calling orchestrator
│   ├── guardrails.py           # Multi-tier input/output & booking guardrails
│   ├── memory.py               # Session memory store & Finite State Machine (FSM)
│   ├── prompts.py              # Dynamic system instructions & runtime context
│   └── tools.py                # Python functions bound to Gemini tool declarations
│
├── schemas/                    # Pydantic Schemas & Data Contracts
│   ├── chat.py                 # Chat API request & response schemas
│   └── reservation.py          # Availability & Booking schemas (for colleague's APIs)
│
├── services/                   # Integration Layer
│   └── restaurant_api.py       # Async/Sync HTTPX client for colleague's APIs + Mock Engine
│
├── frontend/                   # User Interface
│   └── app.py                  # Streamlit chat interface with live state badges
│
└── tests/                      # Automated Test Suite (26 Unit & Integration Tests)
    ├── test_availability.py    # Availability & alternative slot testing
    ├── test_guardrails.py      # Prompt injection, boundaries & confirmation gate
    ├── test_memory.py          # Multi-turn memory & detail retention
    └── test_reservation.py     # End-to-end booking & endpoint validation
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python 3.11+** (Tested on Python 3.13)
- Windows 11 / macOS / Linux

### 2. Activate Virtual Environment
```powershell
# In PowerShell (Windows):
.\.venv\Scripts\Activate.ps1
```

### 3. Configure Environment Variables
Open `.env` and set your Google Gemini API key:
```ini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# Set to true to use built-in mock backend; false when colleague's server is running
USE_MOCK_BACKEND=true
RESTAURANT_API_BASE_URL=http://localhost:8001
RESTAURANT_API_TIMEOUT_SECONDS=10.0
```
> *Get a Gemini API Key free at: [Google AI Studio](https://aistudio.google.com/)*

---

### 4. Running the Application

Open **two** terminal windows:

#### Terminal 1 — Start FastAPI Backend:
```powershell
.\.venv\Scripts\uvicorn main:app --reload --port 8000
```
*Health check:* http://127.0.0.1:8000/health  
*Interactive API Docs (Swagger):* http://127.0.0.1:8000/docs

#### Terminal 2 — Start Streamlit Frontend:
```powershell
.\.venv\Scripts\streamlit run frontend/app.py
```
*Frontend opens automatically in your browser at:* http://localhost:8501

---

## 🧪 Running Automated Tests

Run the full test suite with verbose reporting:
```powershell
.\.venv\Scripts\pytest -v
```
All **26 tests** covering memory retention, prompt injection defenses, booking confirmation gates, availability checking, and FastAPI endpoints will execute.

---
