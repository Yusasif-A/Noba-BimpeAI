"""
Place outbound fraud calls through BimpeAI.

WHAT THIS REPLACES
`caller.py` created a LiveKit room, dispatched the agent into it with the
briefing as job metadata, and *then* dialled -- in that order, so the agent was
already listening when the customer said hello. BimpeAI dials and runs the agent
itself, so there is no room and no dispatch, and the ordering problem is gone.

The briefing is the part that needed rethinking. LiveKit carried it in the job
metadata, which no longer exists, so this brief the tool server first (POST
/sessions) and let the agent fetch it with `get_call_briefing` once the call
connects. `calls.make` is only reached after that briefing is stored -- a call
placed first would land with the agent unable to identify the customer.

ONE REAL LIMITATION
BimpeAI returns a `call_id` from `calls.make`, but the tool server has to be
briefed *before* the call exists, so the session is keyed on a pre-generated id
that is passed to the tools as `session_id`. The agent is told to send the call
id, which will not match. Until BimpeAI supports passing call metadata at dial
time, `/sessions` registers the briefing under both the pre-generated key and,
once known, the real call id -- see `_rekey_session`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid

import bimpeai
import httpx
from dotenv import load_dotenv

from bank_api import NotFound, bank

# Same contract as config.py: .env wins over whatever is already exported, so a
# stale shell variable cannot quietly point this at the wrong tool server.
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],
    force=True,
)
logger = logging.getLogger("fraud_agent.bimpe_caller")


class CallFailed(Exception):
    """The call could not be placed."""


def _mask(number: str) -> str:
    """Never write a full customer number to a log line."""
    return f"***{number[-4:]}" if len(number) >= 4 else "***"


def _client() -> bimpeai.BimpeAI:
    key = os.environ.get("BIMPEAI_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise CallFailed("BIMPEAI_API_KEY is not set")
    return bimpeai.BimpeAI(
        api_key=key, base_url=os.environ.get("BIMPEAI_BASE_URL", "").strip() or None
    )


def _tools_base() -> str:
    url = os.environ.get("BIMPEAI_TOOLS_BASE_URL", "").strip().rstrip("/")
    if not url:
        raise CallFailed(
            "BIMPEAI_TOOLS_BASE_URL is not set, so the agent cannot be briefed "
            "and would call a customer it cannot identify."
        )
    return url


def _brief_tool_server(session_id: str, signal_id: str | None, customer_id: str) -> None:
    """
    Store the briefing before the phone rings.

    Raises rather than warning: an unbriefed call reaches a real customer with
    an agent that cannot name them or verify them, which is worse than no call.
    """
    token = os.environ.get("BIMPEAI_TOOL_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        raise CallFailed("BIMPEAI_TOOL_TOKEN is not set")
    body: dict[str, str] = {"session_id": session_id, "customer_id": customer_id}
    if signal_id:
        body["signal_id"] = signal_id
    try:
        r = httpx.post(
            f"{_tools_base()}/sessions",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except httpx.RequestError as exc:
        raise CallFailed(f"tool server unreachable at {_tools_base()}: {exc}") from exc
    if r.status_code != 200:
        raise CallFailed(f"tool server refused the briefing: {r.status_code} {r.text}")
    logger.info("Tool server briefed for session %s", session_id)


def _rekey_session(session_id: str, call_id: str) -> None:
    """
    Register the same briefing under the real call id.

    The agent is told to pass the call id as `session_id`, and that id does not
    exist until `calls.make` returns. Rather than have the first tool call fail,
    the briefing is stored a second time under the id the agent will actually
    send. Best effort: a failure here is logged, not raised, because the call is
    already placed by this point and the pre-generated key still works.
    """
    token = os.environ.get("BIMPEAI_TOOL_TOKEN", "").strip().strip('"').strip("'")
    try:
        r = httpx.post(
            f"{_tools_base()}/sessions/alias",
            json={"session_id": session_id, "alias": call_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if r.status_code == 200:
            logger.info("Session %s also reachable as %s", session_id, call_id)
        else:
            logger.warning("Could not alias session to call id: %s", r.text)
    except httpx.RequestError as exc:
        logger.warning("Could not alias session to call id: %s", exc)


def place_fraud_call(
    signal_id: str,
    *,
    override_number: str | None = None,
    is_test_call: bool = True,
    agent_id: str | None = None,
) -> dict:
    """
    Ring the customer named on a fraud signal.

    Args:
        signal_id: which signal from the bank's detection engine.
        override_number: dial this instead of the customer's number on file.
            For testing against your own phone -- never set in production, as it
            would read one customer's account details to another number.
        is_test_call: True uses BimpeAI test telephony and consumes no live
            minutes. False requires a live telephony number assigned to the
            agent in the Console.
    """
    try:
        signal = bank.get_fraud_signal(signal_id)
        customer = bank.get_customer_by_id(signal["customerId"])
    except NotFound as exc:
        raise CallFailed(str(exc)) from exc

    to_number = override_number or customer["phoneNumber"]
    if override_number:
        logger.warning(
            "Dialling override number %s instead of the customer on file -- "
            "test mode only",
            _mask(override_number),
        )

    session_id = f"fraud-{signal_id.lower()}-{uuid.uuid4().hex[:6]}"
    _brief_tool_server(session_id, signal_id, customer["customerId"])

    c = _client()
    if not agent_id:
        agent_id = os.environ.get("BIMPEAI_AGENT_ID", "").strip()
    if not agent_id:
        agents = c.agents.list(limit=1).data
        if not agents:
            raise CallFailed("no agents on this account")
        agent_id = agents[0].id

    if not is_test_call:
        # A live call needs a number assigned to the agent. Checking first turns
        # a confusing provider-side failure into a clear one.
        numbers = c.phone_numbers.list(limit=1).data
        if not numbers:
            raise CallFailed(
                "is_test_call=False but no phone numbers are provisioned on this "
                "account. Request one under Team settings -> Phone numbers and "
                "assign it to the agent on the Deploy screen, or use "
                "is_test_call=True."
            )

    logger.info(
        "Placing %s call to %s for signal %s via agent %s",
        "test" if is_test_call else "LIVE",
        _mask(to_number),
        signal_id,
        agent_id,
    )
    try:
        result = c.calls.make(
            agent_id,
            {"destination": to_number, "is_test_call": is_test_call},
            idempotency_key=session_id,
        )
    except bimpeai.BimpeAIError as exc:
        raise CallFailed(f"BimpeAI refused the call: {exc}") from exc

    if result.call_id:
        _rekey_session(session_id, result.call_id)

    logger.info(
        "Call %s: status=%s detail=%s", result.call_id, result.status, result.detail
    )
    return {
        "session_id": session_id,
        "call_id": result.call_id,
        "status": result.status,
        "detail": result.detail,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Place a BimpeAI fraud call.")
    ap.add_argument("signal_id", help='Fraud signal id, e.g. "FRD-CARD-FOREIGN"')
    ap.add_argument(
        "--to",
        dest="override_number",
        help="Dial this number instead of the customer on file (testing only).",
    )
    ap.add_argument(
        "--live",
        action="store_true",
        help="Place a real call. Without this the call is a test call.",
    )
    ap.add_argument("--agent-id", default=None)
    ap.add_argument(
        "--list-signals", action="store_true", help="List fraud signals and exit."
    )
    args = ap.parse_args()

    if args.list_signals:
        for s in bank.list_fraud_signals():
            print(f"{s['signalId']:24} {s['customerId']:12} {s.get('summary', '')[:60]}")
        return

    try:
        out = place_fraud_call(
            args.signal_id,
            override_number=args.override_number,
            is_test_call=not args.live,
            agent_id=args.agent_id,
        )
    except CallFailed as exc:
        raise SystemExit(f"call failed: {exc}") from exc
    print(out)


if __name__ == "__main__":
    main()
