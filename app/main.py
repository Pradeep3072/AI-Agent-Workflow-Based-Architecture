from fastapi import FastAPI


app = FastAPI(
    title="Workflow Agent API",
    description="API for appointment booking, support tickets, and knowledge answers.",
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Report that the API process is responding."""
    return {"status": "ok","version":"0.1.0"}