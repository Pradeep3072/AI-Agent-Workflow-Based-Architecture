from contextlib import asynccontextmanager
from fastapi import FastAPI
from google.adk import Runner
from google.adk.sessions import DatabaseSessionService
from sqlalchemy.engine import URL

from app import models  # noqa: F401 - imports models so SQLAlchemy can register their tables.
from app.adk_workflow import root_agent
from app.database import Base, PROJECT_ROOT, engine
from app.api import router as api_router

APP_NAME = "workflow_agent"
SESSION_DATABASE = PROJECT_ROOT / "agent_sessions.db"
SESSION_DATABASE_URL = str(
    URL.create(
        "sqlite+aiosqlite",
        database=str(SESSION_DATABASE),
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize business tables and the persistent ADK runtime."""
    Base.metadata.create_all(bind=engine)
    session_service = DatabaseSessionService(db_url=SESSION_DATABASE_URL)
    app.state.adk_app_name = APP_NAME
    app.state.adk_session_service = session_service
    app.state.adk_runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
    )
    yield


app = FastAPI(
    title="Workflow Agent API",
    description="API for appointment booking, support tickets, and knowledge answers.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Report that the API process is responding."""
    return {"status": "ok", "version": "0.1.0"}
