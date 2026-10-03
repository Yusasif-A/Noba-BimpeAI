"""
The bank's tools, exposed over HTTP for BimpeAI to call.

WHY THIS FILE EXISTS
Under LiveKit the agent ran in this process, so a tool was a Python method and
`ChallengeFlow` could sit in memory for the length of a call. BimpeAI runs the
agent on its own servers, so a tool is an HTTP endpoint and there is no shared
process to hold state in. Everything the old `@function_tool` methods enforced
in memory has to be enforced here instead.

WHAT MOVED, AND WHAT THAT COSTS
The authority model in the old agent had three independent layers: the prompt
told the model what it may do, the tool refused to act before verification
passed, and `bank_api.py` refused human-only operations regardless. Two of
those three survive unchanged -- this server is the second, `bank_api` is still
the third -- so a model that ignores its instructions still cannot freeze a card
for an unverified caller, and still cannot reverse a transaction at all.

What is genuinely weaker is that the model is now on the far side of a network
boundary we do not control. It can be asked to call these endpoints by anyone
who learns the URL, which is why `require_token` exists: BimpeAI is configured
with a bearer token and an unauthenticated request is refused outright. Treat
that token as the only thing standing between the public internet and
`freeze_card`.

VERIFICATION STATE
Keyed by `session_id`, which BimpeAI passes as the conversation or call id. The
store is in-process and therefore does not survive a restart, and will not work
across more than one worker -- a deliberate limit, not an oversight: a
verification that silently resets to "unverified" is safe, whereas one that
silently persists under a stale key is not. Put this behind a single worker, or
move `_SESSIONS` to Redis before scaling out.

The attempt *limit* stays server-side for the same reason it did before: the
model judges whether an answer matched, because only a reasoning model can tell
"Sent mi Sent Mary" from "blue", but it does not get to decide how many tries
it grants.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import bimpeai
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import card_authorization
from bank_api import NotFound, PermissionDenied, bank
from bimpe_dashboard import DASHBOARD_HTML
from config import settings
from verification import ChallengeFlow, mentions_forbidden_credential

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],
    force=True,
)
logger = logging.getLogger("fraud_agent.bimpe_tools")

app = FastAPI(
    title=f"{settings.bank.name} fraud agent tools",
    description="Bank operations exposed to a BimpeAI-hosted agent.",
    version="1.0.0",
)


# --------------------------------------------------------------------------
# Request logging
# --------------------------------------------------------------------------
#
# BimpeAI's tool calls arrive from its servers, so when one is rejected there is
# nothing on this side saying why -- the first live call produced two 422s on
# get_call_briefing and no clue what shape the body was. These two hooks exist to
# answer that: every /tools/ request logs its raw body, and a validation failure
# logs the body next to the specific field errors.


@app.middleware("http")
async def log_tool_requests(request: Request, call_next):
    """
    Log both halves of every tool exchange, with timing.

    The request half found the first bug (an empty body against a required
    model). The response half matters for the opposite failure: when the agent
    goes quiet on the call, the question is what we handed back and how long we
    took to do it. BimpeAI gives the model a tool-call budget, so a slow reply
    reads as a dead tool and the agent moves on without it -- which on a fraud
    call means proceeding unverified or apologising about a technical problem.
    Latency is therefore logged on every call, not just failures.
    """
    if not (
        request.url.path.startswith("/tools/")
        or request.url.path.startswith("/sessions")
    ):
        return await call_next(request)

    body = await request.body()
    logger.info(
        "-> %s %s from %s\n   content-type: %s\n   body: %s",
        request.method,
        request.url.path,
        request.client.host if request.client else "?",
        request.headers.get("content-type"),
        body.decode("utf-8", "replace")[:2000] or "(empty)",
    )

    started = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - started) * 1000

    # Reading the body off a streaming response consumes it, so capture the
    # chunks and hand back an identical response built from them.
    chunks = [chunk async for chunk in response.body_iterator]
    payload = b"".join(chunks)
    level = logging.INFO if response.status_code < 400 else logging.ERROR
    logger.log(
        level,
        "<- %s %s %s in %.0fms\n   returned: %s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        payload.decode("utf-8", "replace")[:1500] or "(empty)",
    )
    if elapsed_ms > 3000:
        logger.warning(
            "Tool %s took %.1fs. The agent may have given up waiting and "
            "carried on without the result.",
            request.url.path,
            elapsed_ms / 1000,
        )
    return Response(
        content=payload,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError):
    """Say exactly which field was wrong, in the log and in the response."""
    body = exc.body
    logger.error(
        "422 on %s\n   errors: %s\n   body received: %s",
        request.url.path,
        json.dumps(exc.errors(), default=str)[:1500],
        json.dumps(body, default=str)[:1500] if body is not None else "(none)",
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "hint": (
                "This tool expects a flat JSON object. session_id is required on "
                "every tool call -- pass the call id."
            ),
        },
    )


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

# Quotes are stripped because values in this project's .env are quoted
# inconsistently, and a token carrying a stray quote fails every tool call with
# a 401 that looks like a misconfigured integration rather than a typo.
TOOL_TOKEN = os.environ.get("BIMPEAI_TOOL_TOKEN", "").strip().strip('"').strip("'")


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """
    Refuse anything that does not carry the shared bearer token.

    Fails closed: with no token configured the server refuses every request
    rather than serving `freeze_card` to the open internet. An operator who
    genuinely wants it open can set BIMPEAI_TOOL_TOKEN to a known value, which
    is at least a deliberate act.
    """
    if not TOOL_TOKEN:
        raise HTTPException(
            503,
            "BIMPEAI_TOOL_TOKEN is not set; refusing to serve bank tools "
            "unauthenticated.",
        )
    expected = f"Bearer {TOOL_TOKEN}"
    if authorization != expected:
        raise HTTPException(401, "bad or missing bearer token")


# --------------------------------------------------------------------------
# Per-call verification state
# --------------------------------------------------------------------------


@dataclass
class Session:
    """One call's worth of state, standing in for the old agent instance."""

    customer: dict
    signal: dict | None
    card: dict | None
    challenge: ChallengeFlow
    actions_taken: list[str] = field(default_factory=list)
    handed_to_human: bool = False
    # Set once the call is placed, so an escalation can fetch what was said.
    call_id: str | None = None
    case_id: str | None = None
    officer_reported: bool = False
    started_at: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, Session] = {}


@app.get("/debug/sessions", dependencies=[Depends(require_token)])
def debug_sessions() -> dict:
    """
    What the server currently believes about calls in flight.

    Useful mid-call: if the agent claims a technical problem, this says whether
    a briefing exists at all, whether the customer is verified, and how many
    attempts are left -- the three things that decide whether a tool will act.
    """
    distinct: dict[int, dict] = {}
    for key, session in _SESSIONS.items():
        entry = distinct.setdefault(
            id(session),
            {
                "keys": [],
                "customer_id": session.customer.get("customerId"),
                "first_name": session.customer.get("firstName"),
                "signal": session.signal["signalId"] if session.signal else None,
                "card": session.card["cardId"] if session.card else None,
                "verified": session.challenge.verified,
                "attempts": session.challenge.attempts,
                "attempts_remaining": session.challenge.attempts_remaining,
                "questions_asked": [
                    q["question"] for q in session.challenge._asked
                ],
                "actions_taken": session.actions_taken,
                "handed_to_human": session.handed_to_human,
            },
        )
        entry["keys"].append(key)
    return {"live_calls": list(distinct.values())}



def _session(session_id: str) -> Session:
    """
    Load the state for this call, building it on first touch.

    The customer is resolved from the live fraud signals the same way the old
    `caller.py` did it, so an agent that calls a tool without a briefing gets
    the same "no alert waiting" behaviour it got before rather than an error.
    """
    if session_id in _SESSIONS:
        return _SESSIONS[session_id]
    raise HTTPException(
        409,
        "This call has no briefing. Start it with POST /sessions before "
        "calling any tool.",
    )


def _resolve(session_id: str | None) -> Session:
    """
    Find the session for a tool call that did not quote a usable id.

    BimpeAI never substitutes the `{{session_id}}` placeholder -- every live
    call arrives with the literal template string -- so the id is not a usable
    key and the session has to be inferred.

    Earlier this refused whenever more than one call was in flight, on the
    grounds that guessing could read one customer's transactions to another.
    That was right in principle and wrong in practice: pressing Send a few times
    left eight stale sessions, every tool call 409'd, and the agent told a
    customer it was having technical difficulties. The refusal protected nothing
    -- all eight were the same person.

    So: pick the most recent session, and refuse only when the sessions in
    flight belong to genuinely different customers. That keeps the guarantee
    that matters (never cross two customers) without breaking the ordinary case
    of one demo run after another.
    """
    if session_id and session_id in _SESSIONS:
        return _SESSIONS[session_id]

    distinct = list({id(s): s for s in _SESSIONS.values()}.values())
    if not distinct:
        raise HTTPException(
            409,
            "No call is briefed. Place the call from the dashboard, which "
            "briefs this server first.",
        )

    customers = {s.customer.get("customerId") for s in distinct}
    if len(customers) > 1:
        raise HTTPException(
            409,
            f"{len(customers)} different customers have calls in flight and "
            "this request named no session_id, so it cannot be matched safely. "
            "Pass the call id as session_id.",
        )

    newest = max(distinct, key=lambda s: s.started_at)
    if len(distinct) > 1:
        logger.info(
            "%d sessions for customer %s; using the most recent",
            len(distinct),
            newest.customer.get("customerId"),
        )
    return newest


class StartSession(BaseModel):
    session_id: str = Field(description="BimpeAI conversation or call id.")
    customer_id: str | None = None
    phone_number: str | None = None
    signal_id: str | None = None


@app.post("/sessions", dependencies=[Depends(require_token)])
def start_session(body: StartSession) -> dict:
    """
    Brief the agent on one call.

    Called by `bimpe_caller.py` immediately before it dials, so the tools know
    who is on the phone. Replaces the job metadata LiveKit used to carry into
    the room.
    """
    signal = None
    if body.signal_id:
        try:
            signal = bank.get_fraud_signal(body.signal_id)
        except NotFound as exc:
            raise HTTPException(404, f"no such fraud signal: {body.signal_id}") from exc

    try:
        if body.customer_id:
            customer = bank.get_customer_by_id(body.customer_id)
        elif signal is not None:
            customer = bank.get_customer_by_id(signal["customerId"])
        elif body.phone_number:
            customer = bank.get_customer_by_phone(body.phone_number)
        else:
            raise HTTPException(
                422, "one of customer_id, phone_number or signal_id is required"
            )
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    card = None
    if signal is not None and signal.get("cardId"):
        try:
            card = bank.get_card(signal["cardId"])
        except NotFound:
            card = None
    if card is None:
        cards = bank.get_cards_by_customer(customer["customerId"])
        card = cards[0] if cards else None

    _SESSIONS[body.session_id] = Session(
        customer=customer,
        signal=signal,
        card=card,
        challenge=ChallengeFlow(
            customer=customer,
            max_attempts=settings.bank.max_verification_attempts,
        ),
    )
    logger.info(
        "Session %s briefed: customer=%s signal=%s card=%s",
        body.session_id,
        customer["customerId"],
        signal["signalId"] if signal else None,
        card["cardId"] if card else None,
    )
    return {
        "status": "ready",
        "customer_first_name": customer.get("firstName"),
        "has_signal": signal is not None,
    }


class SessionAlias(BaseModel):
    session_id: str
    alias: str


@app.post("/sessions/alias", dependencies=[Depends(require_token)])
def alias_session(body: SessionAlias) -> dict:
    """
    Make one briefing reachable under a second id.

    BimpeAI does not accept metadata at dial time, so the caller has to brief
    the tool server before `calls.make` returns the id the agent will actually
    quote. Both keys point at the same `Session` object -- not a copy -- so
    verification recorded under either is visible through the other.
    """
    session = _SESSIONS.get(body.session_id)
    if session is None:
        raise HTTPException(404, f"no such session: {body.session_id}")
    _SESSIONS[body.alias] = session
    logger.info("Session %s aliased to %s", body.session_id, body.alias)
    return {"status": "ok", "keys": [body.session_id, body.alias]}


# --------------------------------------------------------------------------
# Shared gate
# --------------------------------------------------------------------------


def _require_verified(session: Session) -> str | None:
    """
    The refusal that used to live on the agent class.

    Returned as tool *output* rather than raised, because the model needs to
    read the reason and act on it -- an HTTP error would just look like a broken
    tool and invite a retry.
    """
    if session.challenge.verified:
        return None
    if session.challenge.exhausted:
        return (
            "Verification has failed and this customer cannot be verified. "
            "Do not act on the account. Call transfer_to_human_agent."
        )
    # Name the next tool and the state, because the model retried freeze_card
    # twice in a row on a live call after a bare refusal -- roughly forty
    # seconds of a frightened customer waiting while the agent guessed. A
    # refusal that says what to do instead is acted on; one that only says no
    # gets repeated.
    if session.challenge.pending_unanswered:
        return (
            f"Not yet. You asked: {session.challenge.pending_question}. Pass "
            "their reply to check_security_answer."
        )
    return "Not yet. Call ask_security_question first."


class SessionBody(BaseModel):
    # Optional on every tool body: the model does not reliably know the call id,
    # and a missing id must not fail the call. See _resolve.
    session_id: str | None = None


# --------------------------------------------------------------------------
# Briefing
# --------------------------------------------------------------------------


@app.post("/tools/get_call_briefing", dependencies=[Depends(require_token)])
def get_call_briefing(body: SessionBody = SessionBody()) -> dict:
    """
    Tell the agent who is on the phone and whether anything was flagged.

    This is the per-call half of what `prompts.build_system_prompt` used to bake
    into the instructions before the session started. It cannot live in the
    hosted prompt, because that prompt is one fixed string shared by every call,
    so the agent has to ask for it at the top of each one.

    Deliberately withheld: the security *answers*. The old agent was handed them
    in its briefing so it could judge a misheard reply itself, which is also why
    a model that skipped the tool once asked a customer another customer's
    question. Here the answer never leaves this process -- the agent gets the
    question from `ask_security_question` and submits a verdict, and
    `check_security_answer` is what sees both.
    """
    session = _resolve(body.session_id)
    customer = session.customer
    briefing = {
        "first_name": customer.get("firstName"),
        "full_name": customer.get("fullName") or customer.get("name"),
        "has_flagged_activity": session.signal is not None,
        "verified": session.challenge.verified,
        "attempts_remaining": session.challenge.attempts_remaining,
    }
    if session.card:
        briefing["card_last4"] = session.card.get("last4")
    if session.signal is None:
        briefing["instruction"] = (
            "Nothing has been flagged on this account. Do NOT mention fraud, do "
            "not imply anything is wrong, and do not ask leading questions. Ask "
            "what they need and help with that, inside your limits. Verify them "
            "before acting on the account."
        )
    else:
        first = session.customer.get("firstName") or "there"
        last4 = (session.card or {}).get("last4", "")
        # Hand over the exact sentence rather than a description of it. The
        # model was opening outbound fraud calls with "Hello! How can I help you
        # today?" -- an inbound greeting that leaves a frightened customer to
        # guess why the bank rang. A literal line it can read is harder to drift
        # from than an instruction to compose one.
        # The PIN warning is in the opening line, not a separate field. Handing
        # the model a second sentence to "work in later" gave it something to
        # deliberate over, and it stalled -- re-sending the same tool call while
        # the customer waited. One line to say, one thing to do next.
        briefing["say_this_first"] = (
            f"Hello, am I speaking with {first}? This is "
            f"{settings.bank.agent_display_name} from {settings.bank.name}. "
            f"We saw a suspicious transaction on your card ending {last4}, and "
            "we want to confirm with you whether it was you. I will never ask "
            "you for your P I N or a one time code."
        )
        briefing["instruction"] = (
            "You rang them. Say say_this_first, then stop and listen."
        )
    return {"result": briefing}


# --------------------------------------------------------------------------
# The trigger: a payment attempt
# --------------------------------------------------------------------------


class PaymentAttempt(BaseModel):
    """What the merchant checkout sends when the cardholder presses Send."""

    card_last4: str = Field(description="Last four digits of the card used.")
    amount: str = Field(description='Amount, e.g. "250.00".')
    currency: str = Field(default="USD", description='"USD" or "NGN".')
    merchant: str = Field(default="Online Store", description="Merchant name.")
    country_code: str = Field(default="UA", description="Merchant country, ISO-2.")
    channel: str = Field(default="WEB", description="WEB, POS or ATM.")
    # Ring someone other than the number on file. For a demo where a judge
    # wants the call to reach their own phone: the account stays Yusuf's, only
    # the number dialled changes.
    destination: str | None = Field(
        default=None, description="E.164 number to ring instead of the customer's."
    )


@app.post("/api/payments/attempt")
def payment_attempt(body: PaymentAttempt) -> dict:
    """
    Hold a card payment and, if it looks like fraud, ring the cardholder.

    This is the trigger. Nothing is typed into a terminal: the customer presses
    Send on a checkout, the bank holds the authorization, and the agent calls
    while the money is still stoppable. The authorization stays PENDING
    throughout -- the call decides it, not this endpoint.

    Unauthenticated like the rest of the demo UI, and it can only touch the
    simulated bank in bank_data.py. The destructive operations it can lead to
    (freeze, decline) still run behind the authenticated /tools/ endpoints.
    """
    cards = [
        c
        for c in bank.get_cards_by_customer("CUS-100001")
        if str(c.get("last4")) == body.card_last4.strip()
    ]
    # Fall back to a lookup across the demo customers so any seeded card works.
    if not cards:
        for cust in ("CUS-100002", "CUS-100003"):
            cards = [
                c
                for c in bank.get_cards_by_customer(cust)
                if str(c.get("last4")) == body.card_last4.strip()
            ]
            if cards:
                break
    if not cards:
        raise HTTPException(404, f"no card ending {body.card_last4}")
    card = cards[0]

    if card.get("status") != "ACTIVE":
        return {
            "status": "DECLINED",
            "reason": f"card is {card.get('status')}",
            "called": False,
        }

    try:
        account = bank.get_account(card["accountNumber"])
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        auth = card_authorization.authorize(
            card=card,
            account=account,
            amount=body.amount,
            currency=body.currency,
            merchant=body.merchant,
            country_code=body.country_code,
            channel=body.channel,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if not auth.flagged:
        card_authorization.approve(auth.id, "passed risk checks")
        return {
            "status": "APPROVED",
            "reference": auth.reference_id,
            "called": False,
        }

    # Flagged: brief the tool server on this live signal, then dial.
    signal = card_authorization.signal_from(auth, card)
    session_id = f"live-{auth.id[:8]}"
    customer = bank.get_customer_by_id(auth.customer_id)
    stale = [
        k
        for k, v in _SESSIONS.items()
        if v.customer.get("customerId") == auth.customer_id
    ]
    for key in stale:
        _SESSIONS.pop(key, None)
    if stale:
        logger.info("Cleared %d stale session key(s) for %s", len(stale), auth.customer_id)

    _SESSIONS[session_id] = Session(
        customer=customer,
        signal=signal,
        card=card,
        challenge=ChallengeFlow(
            customer=customer,
            max_attempts=settings.bank.max_verification_attempts,
        ),
    )
    logger.info(
        "Authorization %s flagged (%s) -- briefing session %s and calling %s",
        auth.reference_id,
        auth.severity,
        session_id,
        f"***{(customer.get('phoneNumber') or '')[-4:]}",
    )

    # Dial on a worker thread and answer the browser now. Placing the call
    # inline meant this request stayed open for the round trip to BimpeAI's
    # telephony, and behind the dev tunnel that was long enough to hit the
    # gateway's timeout -- the browser got a 504 with an empty body while the
    # call had in fact been placed. The authorization is already held and
    # visible, so the screen has everything it needs before the phone rings.
    threading.Thread(
        target=_place_call_and_record,
        args=(session_id, customer, auth, body.destination),
        daemon=True,
        name=f"call-{auth.reference_id}",
    ).start()

    return {
        "status": "PENDING",
        "reference": auth.reference_id,
        "severity": auth.severity,
        "reasons": auth.reasons,
        "called": None,  # the dashboard reports this once the call is placed
        "session_id": session_id,
    }


def _place_call_and_record(
    session_id: str,
    customer: dict,
    auth: "card_authorization.PendingAuthorization",
    destination: str | None = None,
) -> None:
    """Place the call off the request thread and record the outcome on the auth."""
    result = _place_call(session_id, customer, destination)
    # Record the call id on the session here, not inside _place_call: the
    # officer report needs it to fetch the transcript, and burying it in the
    # dialling helper meant any change to that helper silently lost the
    # transcript without failing anything.
    session = _SESSIONS.get(session_id)
    if session is not None and result.get("call_id"):
        session.call_id = result["call_id"]
        _SESSIONS[result["call_id"]] = session
    auth.call_placed = result.get("placed", False)
    auth.call_error = result.get("error")
    if not auth.call_placed:
        logger.error(
            "Authorization %s is held but no call was placed: %s",
            auth.reference_id,
            result.get("error") or result.get("status"),
        )


def _place_call(
    session_id: str, customer: dict, destination: str | None = None
) -> dict:
    """
    Ring the cardholder about a held authorization.

    Best-effort: a telephony failure must leave the authorization PENDING and
    visible on the dashboard rather than silently approving a payment nobody
    confirmed. The number dialled is BIMPEAI_DEMO_PHONE when set -- the one
    switch that redirects every outbound contact (this call and the WhatsApp
    message) to the presenter's phone, since bank_data's numbers are fictional
    and dialling them just burns test-call slots on a line nobody answers.
    """
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not agent_id:
        return {"placed": False, "error": "BIMPEAI_AGENT_ID is not set"}
    number = (
        (destination or "").strip()
        or os.environ.get("BIMPEAI_DEMO_PHONE", "").strip()
        or customer.get("phoneNumber", "")
    ).strip()
    if not number:
        return {"placed": False, "error": "no phone number for this customer"}

    live = os.environ.get("BIMPEAI_CALL_LIVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        client = _bimpe_client()
        result = client.calls.make(
            agent_id,
            {"destination": number, "is_test_call": not live},
            idempotency_key=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not place call: %s: %s", type(exc).__name__, exc)
        return {"placed": False, "error": f"{type(exc).__name__}: {exc}"}

    if result.call_id:
        # The agent quotes the call id, so make the briefing reachable by it.
        _SESSIONS[result.call_id] = _SESSIONS[session_id]
        _SESSIONS[session_id].call_id = result.call_id
    return {
        "placed": result.status == "initiated",
        "status": result.status,
        "call_id": result.call_id,
        "detail": result.detail,
    }


class ApproveTransaction(BaseModel):
    session_id: str | None = None
    reference_id: str | None = Field(
        default=None, description="The AUTH- reference the customer confirmed."
    )


@app.post("/tools/approve_transaction", dependencies=[Depends(require_token)])
def approve_transaction(body: ApproveTransaction) -> dict:
    """
    Let a held payment through because the customer says it was them.

    The counterpart to freeze_card, and needed for the same reason: a customer
    who really is buying something abroad must be able to finish, or the agent
    has only made their day worse. Verification is still required -- the whole
    point is that the person confirming is the cardholder.
    """
    session = _resolve(body.session_id)
    if blocked := _require_verified(session):
        return {"result": blocked}
    if not session.card:
        return {"result": "There is no card on this account."}

    pending = card_authorization.pending_for_card(session.card["cardId"])
    if not pending:
        return {"result": "There is no payment waiting on this card."}

    approved: list[str] = []
    for auth in pending:
        if body.reference_id and auth.reference_id != body.reference_id.strip():
            continue
        if card_authorization.approve(auth.id, "customer confirmed on the call"):
            approved.append(auth.reference_id)
    if not approved:
        return {"result": f"No payment matching {body.reference_id} is waiting."}

    session.actions_taken.append(f"approved payment {', '.join(approved)}")
    _schedule_officer_report(session)
    return {
        "result": (
            f"{', '.join(approved)} has been let through and the card stays "
            "active. Tell the customer the payment will complete, and that they "
            "should call us if they see anything they do not recognise."
        )
    }


def _call_transcript(session: Session, wait: bool = False) -> str:
    """
    Fetch what was actually said on the call.

    `wait` polls until BimpeAI reports the call ended, because the transcript is
    only complete once it is. Without that the officer's summary arrived with
    the customer's details and the actions taken but none of the conversation --
    which is the part a human picking up the case actually reads.
    """
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not agent_id or not session.call_id:
        return ""
    deadline = time.monotonic() + (240 if wait else 0)
    while True:
        try:
            detail = _bimpe_client().calls.retrieve(agent_id, session.call_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch transcript: %s", exc)
            return ""
        done = detail.status in {"ended", "failed", "busy", "cancelled"}
        if done or time.monotonic() >= deadline:
            lines = []
            for message in detail.conversation_logs:
                who = "Agent" if message.role == "assistant" else "Customer"
                text = (message.message or "").strip()
                if text:
                    lines.append(f"{who}: {text}")
            if not done:
                lines.append("(call still in progress when this was sent)")
            return "\n".join(lines)
        time.sleep(5)


def _send_officer_report(session: Session, escalation: str | None) -> None:
    """
    Tell the officer what happened, once the call is actually over.

    Waits for BimpeAI to mark the call ended before sending. The summary is
    short -- who, what was done, whether anyone must act -- but it is a report
    of a finished call, so sending it mid-conversation would risk describing a
    state the rest of the call then changes: a card frozen at minute two can
    still be followed by an escalation at minute three.

    The wait is bounded. If BimpeAI never reports the call ended, the report
    goes anyway rather than being lost.
    """
    try:
        _wait_for_call_end(session)
        if escalation is not None:
            text = _human_handover_summary(session, escalation, session.case_id or "?")
        else:
            text = _call_outcome_summary(session)
        result = _notify_human_agent(text)
        logger.info(
            "Officer report for %s sent=%s",
            session.customer.get("customerId"),
            result.get("sent"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Officer report failed: %s: %s", type(exc).__name__, exc)


def _wait_for_call_end(session: Session, timeout_s: float = 300.0) -> bool:
    """
    Block until BimpeAI says the call is over, or the timeout expires.

    Returns True if the call genuinely ended. Polls rather than waiting on a
    webhook because BimpeAI pushes no call-ended event to us.
    """
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not agent_id or not session.call_id:
        # Nothing to wait on -- send immediately rather than stall for the full
        # timeout on a call we cannot see.
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            status = _bimpe_client().calls.retrieve(agent_id, session.call_id).status
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read call status: %s", exc)
            return False
        if status in {"ended", "failed", "busy", "cancelled"}:
            logger.info("Call %s %s; reporting to officer", session.call_id, status)
            return True
        time.sleep(5)
    logger.warning(
        "Call %s still %s after %.0fs; sending the officer report anyway",
        session.call_id,
        status,
        timeout_s,
    )
    return False


def _schedule_officer_report(session: Session, escalation: str | None = None) -> None:
    """Fire the officer report once per call, whichever action triggered it."""
    if session.officer_reported:
        return
    session.officer_reported = True
    threading.Thread(
        target=_send_officer_report,
        args=(session, escalation),
        daemon=True,
        name="officer-report",
    ).start()


def _human_handover_summary(session: Session, reason: str, case_id: str) -> str:
    """
    What the officer needs to pick up a case, and nothing else.

    Read on a phone by someone who may be about to ring the customer, so the
    reason comes first -- it decides whether they call now. The verified flag is
    here because an officer inheriting an unverified caller must not act on
    anything that caller asks for.
    """
    customer = session.customer
    card = session.card or {}
    name = f"{customer.get('firstName','')} {customer.get('lastName','')}".strip()

    parts = [
        f"SORA BANK - ESCALATION {case_id}",
        "",
        f"Reason: {reason}",
        f"Customer: {name}, {customer.get('phoneNumber')}",
        f"Card ending {card.get('last4','?')}: {card.get('status','?')}",
        f"Verified on call: {'yes' if session.challenge.verified else 'NO - verify before acting'}",
    ]

    pending = card_authorization.pending_for_card(card.get("cardId", "")) if card else []
    if pending:
        parts.append(
            "Still held: "
            + ", ".join(
                f"{a.reference_id} {a.amount} {a.currency} at {a.merchant}"
                for a in pending
            )
        )

    if session.actions_taken:
        parts.append("Agent did: " + "; ".join(session.actions_taken))
    else:
        parts.append("Agent did: nothing - escalated before acting")

    parts += ["", "Please call the customer back."]
    return "\n".join(parts)


def _whatsapp_id(number: str) -> str:
    """
    Normalise a number for `channel_user_id`.

    The API requires E.164 *with* the leading plus ("channel_user_id must be
    international E.164 format for whatsapp/telephony"), even though the
    conversation records it returns show the digits bare. Do not be misled by
    the stored form, as I was: that is BimpeAI's internal normalisation, not the
    input format.
    """
    digits = number.strip().lstrip("+").replace(" ", "")
    return f"+{digits}"


def _find_whatsapp_conversation(agent_id: str, number: str) -> str | None:
    """
    Find an existing WhatsApp thread for this number.

    Sending by `conversation_id` sidesteps `channel_user_id` entirely, which is
    worth doing because that field has been the single most expensive thing in
    this integration: with the plus it 400s one way, without it 400s the other,
    and the stored form BimpeAI shows back ("2348020812523") matches neither
    reliably. Once the person has messaged the agent the thread exists, and the
    thread id is unambiguous.
    """
    digits = number.strip().lstrip("+").replace(" ", "")
    try:
        for conv in _bimpe_client().conversations.list(agent_id, limit=50).data:
            if "whatsapp" not in (conv.channel_type or ""):
                continue
            stored = (conv.channel_user_id or "").strip().lstrip("+")
            if stored == digits:
                return conv.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list conversations: %s", exc)
    return None


def _notify_human_agent(text: str) -> dict:
    """
    Send the case to the account officer's WhatsApp.

    A separate conversation from the customer's, keyed on the officer's own
    number, so the two threads never cross -- the customer must never receive
    the internal summary, which names the alert and the account.
    """
    number = os.environ.get("BIMPEAI_HUMAN_AGENT_PHONE", "").strip()
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not number:
        return {"sent": False, "error": "BIMPEAI_HUMAN_AGENT_PHONE is not set"}
    if not agent_id:
        return {"sent": False, "error": "BIMPEAI_AGENT_ID is not set"}
    try:
        client = _bimpe_client()
        conversation_id = _find_whatsapp_conversation(agent_id, number)
        if not conversation_id:
            return {
                "sent": False,
                "error": (
                    f"no WhatsApp thread for {number}. The officer must message "
                    "the agent once (send the start code to the BimpeAI "
                    "WhatsApp number) before the bank can message them."
                ),
            }

        # role="assistant" means "a human is replying on this thread", and
        # BimpeAI only allows that while the AI is paused on it:
        #   "Assistant messages are only allowed when AI is paused"
        # The officer's thread is an internal notification channel, not a
        # conversation the agent should be answering, so pausing it is the
        # correct state anyway -- otherwise the agent would try to reply to its
        # own case summaries.
        try:
            client.conversations.set_ai_status(
                agent_id, conversation_id, is_ai_chat_paused=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not pause officer thread: %s", exc)

        message = client.conversations.messages.send(
            agent_id,
            conversation_id,
            message=text[:4096],
            role="assistant",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Human escalation WhatsApp failed: %s: %s", type(exc).__name__, exc)
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}
    logger.info(
        "Human escalation sent to officer ***%s (message %s)", number[-3:], message.id
    )
    return {"sent": True, "message_id": message.id}


# --------------------------------------------------------------------------
# Customer notification (WhatsApp)
# --------------------------------------------------------------------------


def _bimpe_client() -> "bimpeai.BimpeAI":
    key = os.environ.get("BIMPEAI_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise HTTPException(503, "BIMPEAI_API_KEY is not set on the tool server")
    return bimpeai.BimpeAI(
        api_key=key, base_url=os.environ.get("BIMPEAI_BASE_URL", "").strip() or None
    )


def _notify_whatsapp(
    session: Session, text: str, attachment_url: str | None = None
) -> dict:
    """
    Send the customer a written record of what was done to their card.

    Why this exists at all: a freeze is the moment the customer most needs
    something they can re-read after the call. On the phone they are frightened
    and half-listening, and the one thing they will want an hour later is proof
    that the bank -- not a scammer -- did this. A WhatsApp message is that proof,
    and it survives the call ending.

    Sent with role="assistant" because this is the bank speaking to the
    customer, not the customer speaking to the agent. The channel user id is the
    customer's number in E.164, which is what BimpeAI keys whatsapp
    conversations on.

    Failure here is reported, never raised: the card is already frozen by the
    time this runs, and losing the receipt must not make the agent think the
    freeze failed and try again.
    """
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not agent_id:
        return {"sent": False, "error": "BIMPEAI_AGENT_ID is not set"}

    number = (
        # One switch for both the call and this message, so a demo cannot ring
        # the presenter's phone but text a fixture number.
        os.environ.get("BIMPEAI_DEMO_PHONE", "").strip()
        or session.customer.get("phoneNumber", "")
    ).strip()
    if not number:
        return {"sent": False, "error": "no phone number on file for this customer"}

    body: dict[str, Any] = {
        "message": text,
        "channel_type": "whatsapp",
        "channel_user_id": _whatsapp_id(number),
        "role": "assistant",
        # Test channel unless explicitly told otherwise, so a demo cannot
        # message a real customer by accident.
        "is_test_channel": os.environ.get("BIMPEAI_NOTIFY_LIVE", "").strip().lower()
        not in {"1", "true", "yes"},
    }
    try:
        client = _bimpe_client()
        message = client.conversations.send(agent_id, **body)
    except Exception as exc:  # noqa: BLE001 - the reason matters more than the type
        logger.error("WhatsApp notification failed: %s: %s", type(exc).__name__, exc)
        return {"sent": False, "error": f"{type(exc).__name__}: {exc}"}

    logger.info(
        "WhatsApp notification sent to %s (message %s)",
        f"***{number[-4:]}",
        message.id,
    )
    out = {"sent": True, "message_id": message.id}
    if attachment_url:
        # Recorded for the audit trail. BimpeAI's send body takes no attachment
        # field, so the link rides in the message text instead of as a
        # structured attachment.
        out["attachment_url"] = attachment_url
    return out


class NotifyCustomer(BaseModel):
    session_id: str | None = None
    message: str = Field(
        description=(
            "What to tell the customer in writing. Plain text, no markdown. "
            "Say what was done and what happens next."
        )
    )
    include_transaction_link: bool = Field(
        default=False,
        description=(
            "True to include a link to the flagged transactions page, so the "
            "customer can see exactly what was blocked."
        ),
    )


@app.post("/tools/notify_customer", dependencies=[Depends(require_token)])
def notify_customer(body: NotifyCustomer) -> dict:
    """Send the customer a WhatsApp message recording what was done."""
    session = _resolve(body.session_id)
    text = body.message.strip()
    link = None
    if body.include_transaction_link:
        public = os.environ.get("BIMPEAI_TOOLS_BASE_URL", "").strip().rstrip("/")
        if public:
            link = f"{public}/ui/transactions/{session.customer['customerId']}"
            text = f"{text}\n\nSee the blocked transactions here: {link}"
    result = _notify_whatsapp(session, text, link)
    if not result.get("sent"):
        # Never report this as a failure the model should do something about.
        # Told that a message "could not be sent", it retried the whole
        # sequence -- re-verifying and re-freezing in a loop while a customer
        # listened to "one moment please". The card is already frozen by now;
        # the written copy is a courtesy, not part of the protection.
        logger.warning("Customer notification failed: %s", result.get("error"))
        return {
            "result": (
                "Noted. Nothing further is needed here and everything already "
                "done to the card stands. Tell the customer aloud instead, then "
                "carry on with the call."
            )
        }
    session.actions_taken.append("sent WhatsApp confirmation")
    return {
        "result": (
            "The customer now has it in writing on WhatsApp. Tell them to "
            "expect the message, then carry on."
        )
    }


# --------------------------------------------------------------------------
# Verification tools
# --------------------------------------------------------------------------


@app.post("/tools/ask_security_question", dependencies=[Depends(require_token)])
def ask_security_question(body: SessionBody = SessionBody()) -> dict:
    """Return the question to put to the customer, word for word."""
    session = _resolve(body.session_id)
    if session.challenge.verified:
        return {"result": "This customer is already verified. Do not ask again."}
    if session.challenge.exhausted:
        return {
            "result": (
                "No attempts remain. Do not ask another question. Call "
                "transfer_to_human_agent."
            )
        }
    if session.challenge.pending_unanswered:
        return {
            "result": (
                f"You have already asked: {session.challenge.pending_question}. "
                "Wait for their answer and pass it to check_security_answer."
            )
        }
    try:
        question = session.challenge.next_question()
    except RuntimeError as exc:
        logger.error("Cannot verify %s: %s", session.customer["customerId"], exc)
        return {
            "result": (
                "This customer has no security questions on file and cannot be "
                "verified. Call transfer_to_human_agent."
            )
        }
    return {
        "result": (
            f"Ask the customer exactly this, word for word: {question}\n"
            f"Attempts remaining: {session.challenge.attempts_remaining}."
        )
    }


class CheckAnswer(BaseModel):
    session_id: str | None = None
    answer: str = Field(description="Exactly what the customer said, as heard.")
    # Accepts a real boolean or the string "true"/"false". BimpeAI's
    # body_template substitutes placeholders into a JSON string, so a boolean
    # parameter arrives quoted; rejecting that would fail the verification step
    # of every call.
    matches: bool | str = Field(
        description="Your judgement: did it match the record?"
    )

    @property
    def matched(self) -> bool:
        if isinstance(self.matches, bool):
            return self.matches
        return self.matches.strip().lower() in {"true", "yes", "1", "match"}


@app.post("/tools/check_security_answer", dependencies=[Depends(require_token)])
def check_security_answer(body: CheckAnswer) -> dict:
    """
    Count the attempt and report the outcome.

    The model supplies the verdict; this counts it. See `ChallengeFlow.record`
    for why the judgement and the counting are split.
    """
    session = _resolve(body.session_id)
    if session.challenge.verified:
        # Terminal, and says what to do next. "Carry on with the call" left the
        # model with nowhere to go, so it re-verified and re-froze in a loop.
        return {
            "result": (
                "Already verified. Call freeze_card now."
            )
        }

    verified = session.challenge.record(body.matched, body.answer)
    if verified:
        # Reflect it on any payment this call is about, so the screen shows the
        # agent has got past identity and is now asking the real question.
        if session.card:
            for auth in card_authorization.pending_for_card(session.card["cardId"]):
                auth.verified = True
        return {
            "result": (
                "Correct. Say 'thank you, that is correct', then call "
                "describe_suspicious_activity."
            )
        }
    if session.challenge.exhausted:
        return {
            "result": (
                "That was the last attempt and verification has failed. Do not "
                "act on the account. Call transfer_to_human_agent now."
            )
        }
    return {
        "result": (
            "That did not match. Ask a DIFFERENT question from the record. "
            f"Attempts remaining: {session.challenge.attempts_remaining}."
        )
    }


@app.post("/tools/describe_suspicious_activity", dependencies=[Depends(require_token)])
def describe_suspicious_activity(body: SessionBody = SessionBody()) -> dict:
    """Return the flagged transactions, for the agent to describe once verified."""
    session = _resolve(body.session_id)
    if session.signal is None:
        return {
            "result": (
                "There is no alert on this account and no transactions were "
                "flagged. Do not describe anything. Ask the customer what they "
                "need instead."
            )
        }
    lines = [session.signal.get("summary", "")]
    for trx in session.signal.get("transactions", []):
        lines.append(
            f"- {trx.get('referenceId')}: {trx.get('amount')} "
            f"at {trx.get('merchant')} in {trx.get('location')} "
            f"on {trx.get('timestamp')}"
        )
    return {"result": "\n".join(line for line in lines if line)}


# --------------------------------------------------------------------------
# Pre-approved actions
# --------------------------------------------------------------------------


class FreezeCard(BaseModel):
    session_id: str | None = None
    reason: str = Field(description="Short reason, in the customer's own terms.")


@app.post("/tools/freeze_card", dependencies=[Depends(require_token)])
def freeze_card(body: FreezeCard) -> dict:
    """Temporarily block the card. Pre-approved and reversible by the bank."""
    session = _resolve(body.session_id)
    if blocked := _require_verified(session):
        return {"result": blocked}
    if not session.card:
        return {"result": "There is no card on this account to freeze."}

    # Already frozen: say so and close the subject. Returning the same success
    # text again let the model loop -- freeze, be told to do something else,
    # fail at it, and come back to freeze again. A terminal answer stops that.
    if session.card.get("status") != "ACTIVE":
        return {
            "result": (
                "Already frozen and the payment is already declined. Say so, "
                "then call end_call."
            )
        }

    try:
        card = bank.block_card(
            session.card["cardId"], reason=body.reason, actor="agent"
        )
    except PermissionDenied as exc:
        return {"result": f"The bank refused that: {exc}"}
    except NotFound as exc:
        return {"result": f"Card not found: {exc}"}
    session.actions_taken.append(f"froze card {card['cardId']}: {body.reason}")
    logger.info("Card %s frozen on session %s", card["cardId"], body.session_id)

    # A freeze that left an in-flight payment authorized would let the fraud
    # complete anyway, so the held authorization is declined in the same breath.
    # This is the moment the whole call exists for.
    declined = card_authorization.decline_pending_for_card(
        card["cardId"], f"card frozen: {body.reason}"
    )
    extra = ""
    if declined:
        session.actions_taken.append(
            f"declined pending payment {', '.join(declined)}"
        )
        extra = (
            f" The payment that was being attempted ({', '.join(declined)}) has "
            "been declined and will not go through."
        )

    # No customer WhatsApp: that number is not opted in to BimpeAI's test
    # channel, so every attempt 400s. The officer report is the one that must
    # land, and it goes to a number that can receive it.
    _schedule_officer_report(session)

    return {
        "result": (
            f"Frozen. Say: your card ending "
            f"{str(card.get('last4', '')).strip()} is now frozen and the "
            "payment has been declined. Then call end_call."
        )
    }


def reduce_card_limit(body: ReduceLimit) -> dict:
    """Lower the daily limit. Pre-approved; it can only ever go down."""
    session = _resolve(body.session_id)
    if blocked := _require_verified(session):
        return {"result": blocked}
    if not session.card:
        return {"result": "There is no card on this account."}
    try:
        bank.set_card_limit(
            session.card["cardId"], daily_limit=body.new_daily_limit, actor="agent"
        )
    except PermissionDenied as exc:
        return {"result": f"The bank refused that: {exc}"}
    except (NotFound, ValueError) as exc:
        return {"result": f"That did not work: {exc}"}
    session.actions_taken.append(f"limit lowered to {body.new_daily_limit}")
    return {
        "result": (
            f"The daily limit is now {body.new_daily_limit} Naira. Only a human "
            "can raise it again."
        )
    }


class FlagTransaction(BaseModel):
    session_id: str | None = None
    reference_id: str = Field(description='Transaction reference, e.g. "TRX-9003".')
    note: str = Field(description="What the customer said about it.")


@app.post("/tools/flag_transaction", dependencies=[Depends(require_token)])
def flag_transaction(body: FlagTransaction) -> dict:
    """Record a disputed transaction for the fraud team. Moves no money."""
    session = _resolve(body.session_id)
    if blocked := _require_verified(session):
        return {"result": blocked}
    try:
        bank.flag_transaction(body.reference_id, note=body.note, actor="agent")
    except PermissionDenied as exc:
        return {"result": f"The bank refused that: {exc}"}
    except NotFound as exc:
        return {"result": f"No such transaction: {exc}"}
    session.actions_taken.append(f"flagged {body.reference_id}")
    return {
        "result": (
            f"{body.reference_id} is flagged for the fraud team. Do not promise "
            "the customer a refund; say a human will review it."
        )
    }


# --------------------------------------------------------------------------
# Escalation and close
# --------------------------------------------------------------------------


class Transfer(BaseModel):
    session_id: str | None = None
    reason: str = Field(description="Why, for the human picking it up.")


@app.post("/tools/transfer_to_human_agent", dependencies=[Depends(require_token)])
def transfer_to_human_agent(body: Transfer) -> dict:
    """
    Escalate to the human fraud team.

    Under LiveKit this moved the caller into a room with an analyst. BimpeAI has
    no warm transfer, so this opens a fraud case and reports back that a human
    will call -- which is what the agent should be telling the customer either
    way. Pair it with `conversations.set_ai_status(is_ai_chat_paused=True)` on
    the caller side so the AI stops replying on chat channels.
    """
    session = _resolve(body.session_id)
    case = bank.create_fraud_case(
        customer_id=session.customer["customerId"],
        signal_id=session.signal["signalId"] if session.signal else None,
        summary=f"Escalated by agent: {body.reason}",
        actions_taken=session.actions_taken,
        needs_human=True,
    )
    session.handed_to_human = True
    logger.info(
        "Session %s escalated to human: %s (case %s)",
        body.session_id,
        body.reason,
        case.get("caseId"),
    )

    # BimpeAI has no warm transfer, so the handover is: stop the AI replying on
    # the customer's threads so a human taking over is not talking over a bot,
    # and send the officer the case. The customer is told by the agent on the
    # call, not by WhatsApp -- their number is not opted in to the test channel.
    paused = _pause_ai_for_customer(session)

    # The officer gets the full handover once the call ends, so the transcript
    # is complete. Scheduled rather than sent inline: mid-call there is nothing
    # to read yet.
    session.case_id = case.get("caseId")
    _schedule_officer_report(session, escalation=body.reason)

    return {
        "result": (
            "A human from the fraud team now has this case and will call the "
            "customer back. Tell them that plainly, confirm anything already "
            "done on the card, and end the call. Do not promise a refund or a "
            "timescale you were not given."
        ),
        "case_id": case.get("caseId"),
        "human_agent_notified": "scheduled when the call ends",
        "ai_paused": paused,
    }


def _pause_ai_for_customer(session: Session) -> bool:
    """
    Stop the AI answering this customer's threads so a human can take over.

    Finds the customer's conversations by their phone number rather than
    tracking ids, because the handover can be triggered from a voice call while
    the thread that needs pausing is on WhatsApp. Best-effort by design: a
    failure here leaves the AI answering, which is visible and recoverable,
    whereas raising would make the agent think the escalation itself failed.
    """
    agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    number = (session.customer.get("phoneNumber") or "").strip()
    if not agent_id or not number:
        return False
    try:
        client = _bimpe_client()
        paused_any = False
        for conv in client.conversations.list(agent_id, limit=50).data:
            if (conv.channel_user_id or "").strip() != number:
                continue
            if conv.is_ai_chat_paused:
                paused_any = True
                continue
            client.conversations.set_ai_status(
                agent_id, conv.id, is_ai_chat_paused=True
            )
            logger.info("AI paused on conversation %s for human handover", conv.id)
            paused_any = True
        return paused_any
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not pause AI for handover: %s: %s", type(exc).__name__, exc)
        return False


@app.post("/tools/end_call", dependencies=[Depends(require_token)])
def end_call(body: SessionBody = SessionBody()) -> dict:
    """
    Close the call out.

    BimpeAI hangs up on its own, so this only does the bookkeeping the old
    `end_call` did before tearing down the room: a fraud case recording what
    happened, unless one was already opened by an escalation.
    """
    session = _SESSIONS.get(body.session_id)
    if session is None:
        return {"result": "Call ended."}
    if not session.handed_to_human:
        bank.create_fraud_case(
            customer_id=session.customer["customerId"],
            signal_id=session.signal["signalId"] if session.signal else None,
            summary=(
                session.signal["summary"]
                if session.signal
                else "Customer-initiated call to the security line."
            ),
            actions_taken=session.actions_taken,
            # The agent saw the call through without escalating, so the case is
            # a record rather than a request: AUTO_CONTAINED, not awaiting a
            # human.
            needs_human=False,
        )

    # Report every completed call to the officer, not only escalations. A call
    # that ended well still froze a card and declined a payment on a real
    # customer's account, and the person who owns that relationship should hear
    # it from the system rather than from the customer later.
    # Fallback only: if no decisive action was taken (nothing frozen, nothing
    # approved, no escalation) the officer has heard nothing, so report here.
    if not session.officer_reported:
        _schedule_officer_report(session)
    officer = {"sent": "scheduled"}

    # Drop every key pointing at this call, not just the one the agent quoted:
    # a session reached through an alias would otherwise leave its sibling key
    # behind, and the next call reusing that id would inherit a verified state.
    for key in [k for k, v in _SESSIONS.items() if v is session]:
        _SESSIONS.pop(key, None)
    logger.info(
        "Session %s ended; actions=%s; officer_notified=%s",
        body.session_id,
        session.actions_taken,
        officer.get("sent"),
    )
    return {"result": "Call ended."}


def _call_outcome_summary(session: Session) -> str:
    """
    A one-glance record of a call that needed no human.

    Sent so the person who owns the customer relationship hears about a frozen
    card from the system rather than from the customer.
    """
    customer = session.customer
    card = session.card or {}
    name = f"{customer.get('firstName','')} {customer.get('lastName','')}".strip()
    parts = [
        "SORA BANK - call handled, no action needed",
        "",
        f"Customer: {name}, {customer.get('phoneNumber')}",
        f"Card ending {card.get('last4','?')}: {card.get('status','?')}",
        f"Verified on call: {'yes' if session.challenge.verified else 'no'}",
        "Agent did: "
        + ("; ".join(session.actions_taken) if session.actions_taken else "nothing"),
    ]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Guardrail check, retained from the LiveKit output guard
# --------------------------------------------------------------------------


class GuardCheck(BaseModel):
    text: str


@app.post("/tools/check_utterance", dependencies=[Depends(require_token)])
def check_utterance(body: GuardCheck) -> dict:
    """
    Report whether a line of text asks for a forbidden credential.

    The old agent ran this over every utterance *before* the TTS spoke it, so a
    model that asked for a PIN was never heard. BimpeAI generates and speaks in
    one hosted step, so nothing can intercept it there -- this endpoint cannot
    restore that guarantee. It is useful for auditing a transcript after the
    fact, and for your own tests; do not mistake it for the pre-speech guard it
    replaces.
    """
    found = mentions_forbidden_credential(body.text)
    return {"forbidden": found is not None, "credential": found}


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    """
    Put the demo back to a quiet account.

    Needed because every artefact of a run is sticky by design: a held
    authorization, a frozen card and a briefed session all persist so the screen
    can show what happened. Rehearsing twice without clearing them leaves the
    second run claiming the first run's payment is still in flight.

    Only touches the simulated bank and this server's in-memory state. It
    cannot undo a real phone call or a WhatsApp message that has already gone
    out.
    """
    card_authorization.reset()
    _SESSIONS.clear()
    restored = []
    for card in bank.get_cards_by_customer("CUS-100001"):
        if card.get("status") != "ACTIVE":
            # Straight through the data layer: unblock_card is a human-only
            # operation in bank_api and should stay that way, so the demo reset
            # does not quietly hand the agent a capability it must not have.
            card["status"] = "ACTIVE"
            restored.append(card["cardId"])
    logger.info("Demo reset; cards restored to ACTIVE: %s", restored or "none")
    return {"status": "reset", "cards_reactivated": restored}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "sessions": len(_SESSIONS),
        "token_configured": bool(TOOL_TOKEN),
        "time": datetime.now(UTC).isoformat(),
    }


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
#
# The UI is deliberately read-only and unauthenticated on GET: it shows a
# simulated customer from bank_data.py, never a real one, and making the demo
# screen require a bearer token would mean pasting the tool token into a
# browser -- the same token that can freeze cards. Nothing here can change
# state; every mutation still goes through an authenticated /tools/ endpoint.


def _mask_phone(number: str | None) -> str:
    """
    Show enough of a number to recognise, not enough to dial.

    The dashboard is the thing on a projector during a demo, and the number on
    it is a real phone. Keep the country code and the last three digits so the
    presenter can confirm it is theirs, and hide the middle.
    """
    if not number:
        return "—"
    digits = number.strip()
    if len(digits) < 7:
        return "***"
    return f"{digits[:4]}***{digits[-3:]}"


@app.get("/api/dashboard/{customer_id}")
def dashboard_data(customer_id: str) -> dict:
    """
    Everything the screen needs about one customer, in one call.

    Read straight from bank_api on each request rather than cached, so a freeze
    performed mid-call shows up on the next poll. That is the whole point of the
    screen: the action the agent takes on the phone has to be visible here.
    """
    try:
        customer = bank.get_customer_by_id(customer_id)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc

    accounts = bank.get_accounts_by_customer(customer_id)
    cards = bank.get_cards_by_customer(customer_id)
    account = accounts[0] if accounts else None

    transactions: list[dict] = []
    if account:
        # The seeded Kyiv rows are fixtures for the manual bimpe_caller path. On
        # this screen they would read as fraud that already happened, before the
        # cardholder has pressed anything -- so ordinary history only, and the
        # live attempt appears under `pending` once it exists.
        transactions = [
            t
            for t in bank.get_statement(account["accountNumber"], last_n=8)
            if not t.get("flagged")
        ]

    # Held authorizations first: they are the ones still stoppable, and the
    # screen is for the person deciding, not for reconciliation.
    pending = card_authorization.for_customer(customer_id)

    cases = [k for k in bank.get_fraud_cases() if k["customerId"] == customer_id]

    # Only signals raised by an actual payment attempt. The pre-seeded signals
    # in bank_data are fixtures for bimpe_caller.py's manual path; showing them
    # here made the screen claim a live incident before the cardholder had
    # pressed anything, which is exactly the thing this demo must not do -- a
    # bank inventing an incident is worse than no alert at all.
    signals = [
        s.signal
        for s in {id(v): v for v in _SESSIONS.values()}.values()
        if s.customer.get("customerId") == customer_id
        and s.signal
        and str(s.signal.get("signalId", "")).startswith("LIVE-")
    ]

    live = [
        {
            "verified": s.challenge.verified,
            "attempts_remaining": s.challenge.attempts_remaining,
            "actions_taken": s.actions_taken,
            "handed_to_human": s.handed_to_human,
        }
        for s in {id(v): v for v in _SESSIONS.values()}.values()
        if s.customer.get("customerId") == customer_id
    ]

    return {
        "customer": {
            "id": customer["customerId"],
            "name": f"{customer.get('firstName','')} {customer.get('lastName','')}".strip(),
            "phone": _mask_phone(customer.get("phoneNumber")),
            "city": customer.get("city"),
        },
        "account": account,
        "cards": cards,
        "transactions": transactions,
        "pending": pending,
        "signals": signals,
        "cases": cases,
        "live_calls": live,
        "fetched_at": datetime.now(UTC).isoformat(),
    }


@app.get("/ui/transactions/{customer_id}", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def dashboard(customer_id: str = "CUS-100001") -> HTMLResponse:
    """The operations screen: the card, the flagged transactions, what the agent did."""
    # Branding follows settings.bank.name, so renaming the bank in .env renames
    # it on the screen too rather than leaving a stale name in the markup.
    name = settings.bank.name
    head, _, tail = name.partition(" ")
    brand = f"{head}<span>{tail}</span>" if tail else f"{head}<span>Bank</span>"
    html = (
        DASHBOARD_HTML.replace("__CUSTOMER_ID__", customer_id)
        .replace("__BANK_NAME__", name)
        .replace("__BANK_BRAND__", brand)
    )
    return HTMLResponse(html)
