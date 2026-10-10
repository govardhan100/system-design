import socket

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Rate-Limited Demo API")


class WorkRequest(BaseModel):
    message: str = Field(default="hello", max_length=1000)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/{algorithm}")
async def run_work(
    algorithm: str,
    payload: WorkRequest,
    subject: str = Header(alias="X-Auth-Subject", min_length=1, max_length=128),
) -> dict[str, str]:
    if algorithm not in {"fixed", "sliding", "token"}:
        raise HTTPException(status_code=404, detail="Unknown demo route")
    return {
        "message": payload.message,
        "subject": subject,
        "served_by": socket.gethostname(),
    }