"""Permanently QA-only customer discovery, outside tenant auth and storage."""
import json
import os
import threading
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import FileResponse
from lib import discovery as ledger
from lib.discovery_ops import mutate
from transport.http.security import AuthUnavailable, get_auth_provider


def enabled():
    if os.environ.get("DISCOVERY_ENABLED") != "qa":
        raise HTTPException(404)


router = APIRouter(dependencies=[Depends(enabled)])
THANKS = "Thanks. I'll send the one-page consent form and a calendar link within a day."
SEGMENT_ANSWERS = ("job searching", "career change", "coach", "recruiter or hiring", "school or workforce program", "none of these")
_limits = {}
_limit_lock = threading.Lock()


def check_rate(request):
    # Ingress supplies X-Real-IP; never use the client-supplied X-Forwarded-For chain.
    key = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    with _limit_lock:
        for old in [ip for ip, (_, end) in _limits.items() if end <= now]:
            del _limits[old]
        count, end = _limits.get(key, (0, now + 600))
        if count >= 10 or (key not in _limits and len(_limits) >= 4096):
            raise HTTPException(429, "Please try again in ten minutes.", headers={"Retry-After": "600"})
        _limits[key] = (count + 1, end)


def ledger_path():
    path = ledger.default_ledger_path().resolve()
    from lib.config import DATA_FOLDER
    if path.is_relative_to((Path(str(DATA_FOLDER)) / "users").resolve()):
        raise HTTPException(503, "Discovery storage unavailable")
    return path


def founder(request: Request):
    provider = get_auth_provider()
    try:
        user = provider.authenticate_request(request.headers.get("authorization"), request.cookies.get("jc_session"))
    except AuthUnavailable as exc:
        raise HTTPException(503, "Sign-in temporarily unavailable") from exc
    allowed = {x.strip() for x in os.environ.get("DISCOVERY_ADMIN_OIDS", "").split(",") if x.strip()}
    if not provider.auth_enabled or not user or user.id == "admin" or user.id not in allowed:
        raise HTTPException(404)
    return user


def founder_write(request: Request, user=Depends(founder)):
    origin = urlsplit(request.headers.get("origin", ""))
    if origin.scheme not in ("http", "https") or origin.netloc.lower() != request.headers.get("host", "").lower():
        raise HTTPException(403, "Use the review page to make changes")
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(403, "Use the review page to make changes")
    return user


class Signup(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    segment_answer: str
    current_tools: str = Field(max_length=2000)
    ai_assistant: Literal["ChatGPT", "Claude", "Copilot", "Gemini", "other", "none"]
    best_window: str = Field(min_length=1, max_length=500)
    incentive_preference: Literal["gift_card", "pro_access"]
    channel: str = "other"
    program: Literal["interview", "beta"] = "interview"
    website: str = ""


@router.get("/discovery")
def signup_page():
    return page()


def page():
    from transport.http.app import _SPA_DIST
    index = _SPA_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Discovery page is being prepared")
    return FileResponse(index, headers={"Cache-Control": "no-store"})


@router.post("/api/discovery/signup")
async def signup(request: Request):
    check_rate(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, "Signup is too long")
    try:
        raw = json.loads(body)
        if isinstance(raw, dict) and raw.get("website"):
            return {"message": THANKS}
        data = Signup.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "Please check the signup fields") from exc
    if data.channel not in ledger.CHANNELS or data.segment_answer not in SEGMENT_ANSWERS:
        raise HTTPException(422, "Please choose one of the listed options")
    # Keep blocking disk work off the request loop, without entering a tenant.
    from starlette.concurrency import run_in_threadpool
    await run_in_threadpool(save_signup, data)
    return {"message": THANKS}


def save_signup(data):
    with closing(ledger.connect(ledger_path())) as con:
        ledger.add_signup(con, data.name, data.email, data.segment_answer, data.current_tools,
                          data.ai_assistant, data.channel, data.program,
                          incentive_preference=data.incentive_preference, best_window=data.best_window)


@router.get("/discovery/review", dependencies=[Depends(founder)])
def review_page():
    return page()


@router.get("/api/discovery/review", dependencies=[Depends(founder)])
def review():
    with closing(ledger.connect(ledger_path())) as con:
        with con:
            con.execute("BEGIN")
            data = ledger.load_ledger(con)
    return {"ledger": data, "report": asdict(ledger.build_report(data))}


class Consent(BaseModel):
    participant: int = Field(gt=0)
    version: str = Field(min_length=1, max_length=80)
    recording_ok: bool = False
    quote_ok: bool = False


class Schedule(BaseModel):
    participant: int = Field(gt=0)
    kind: Literal["interview", "beta_session"] = "interview"
    when: datetime


class Complete(BaseModel):
    session: int = Field(gt=0)
    minutes: int = Field(ge=0, le=1440)
    themes: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=1000)
    no_show: bool = False


class Quote(BaseModel):
    session: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    public: bool = False


class Incentive(BaseModel):
    participant: int = Field(gt=0)
    earned_by: str = Field(min_length=1, max_length=80)
    type: Literal["gift_card", "pro_access", "none"] = "gift_card"
    amount: int = Field(default=0, ge=0, le=10000)
    reference: str = Field(default="", max_length=300)
    pending: bool = True


class Status(BaseModel):
    participant: int = Field(gt=0)
    status: Literal["dropped", "declined"]


ACTION_MODELS = {"consent": Consent, "schedule": Schedule, "complete": Complete,
                 "quote": Quote, "incentive": Incentive, "status": Status}


@router.post("/api/discovery/snapshot", dependencies=[Depends(founder_write)])
def snapshot():
    path = ledger_path()
    try:
        out = ledger.write_snapshot(path, ledger.Report(), date.today().isoformat())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    data = json.loads(out.read_text(encoding="utf-8"))
    return {"filename": out.name, "ledger_sha256": data["ledger_sha256"]}


@router.post("/api/discovery/{action}", dependencies=[Depends(founder_write)])
def change(action: str, payload: dict):
    model = ACTION_MODELS.get(action)
    if model is None:
        raise HTTPException(404)
    try:
        values = model.model_validate(payload).model_dump(mode="json")
        with closing(ledger.connect(ledger_path())) as con:
            result = mutate(con, action, values)
        return {"ok": True, "id": result}
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Check the action fields and record identifiers") from exc
