# Running the ADK Workflow Agent

The project exposes the same ADK `root_agent` through two development entry points.

## Install dependencies

From the project root in PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`google-adk` provides ADK graph workflows. `SQLAlchemy[asyncio]` and `aiosqlite` provide the async SQLite driver required by ADK's persistent session service.

## Run the FastAPI API

```powershell
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the REST endpoints. `POST /api/v1/chat` calls the ADK runner and returns the ADK session ID as `conversation_id`. Send that ID with later messages to continue the same session.

## Run the ADK development UI

From the project root, in another terminal:

```powershell
adk web --port 8001
```

Open `http://127.0.0.1:8001` and select `app`. The ADK CLI discovers the `root_agent` exported by `app/agent.py`. This web UI is for local development and debugging, not production deployment.

## Data files

- `workflow_agent.db` stores appointments and support tickets.
- `agent_sessions.db` stores ADK conversation history and workflow state.

Both files are local development data and are excluded from Git. The current workflows use deterministic Python functions, so no Gemini API key is needed yet. A key will be required when an LLM node is added, such as for RAG answer generation.

If the API receives a conversation ID created by the earlier custom workflow, it transfers the current appointment or ticket step into an ADK session using that same ID. Old message history is not copied; existing appointments and tickets remain in the business database.
