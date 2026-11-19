from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app import models  # noqa: F401 - imports models so SQLAlchemy can register their tables.
from app.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create any missing tables when the development app starts."""
    Base.metadata.create_all(bind=engine)
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
    return {"status": "ok","version":"0.1.0"}
