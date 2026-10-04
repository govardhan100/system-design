import socket

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Rate-Limited Demo API")


class WorkRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    message: str = Field(default="hello", max_length=1000)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/{algorithm}")
async def run_work(algorithm: str, payload: WorkRequest) -> dict[str, str]:
    if algorithm not in {"fixed", "sliding", "token"}:
        raise HTTPException(status_code=404, detail="Unknown demo route")
    return {
        "message": payload.message,
        "user_id": payload.user_id,
        "served_by": socket.gethostname(),
    }