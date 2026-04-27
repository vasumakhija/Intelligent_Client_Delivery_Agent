from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncio
import logging

from agent3_orchestrator import run_orchestrator

app = FastAPI(title="Client Delivery Agent API")
log = logging.getLogger(__name__)

class QueryRequest(BaseModel):
    query: str
    user_id: str = "default_user"  # simulated auth

@app.get("/")
def root():
    return {"status": "MAQ Delivery Agent is running"}

@app.post("/query")
async def handle_query(request: QueryRequest):
    log.info(f"Query received from user {request.user_id}: {request.query}")
    await run_orchestrator(request.query)
    return {
        "status":  "success",
        "user_id": request.user_id,
        "query":   request.query,
        "report":  "report_output.html"
    }

@app.get("/report", response_class=HTMLResponse)
async def get_report():
    try:
        with open("report_output.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<h2>No report generated yet. POST to /query first.</h2>"