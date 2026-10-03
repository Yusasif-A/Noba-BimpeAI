"""
Push this project's fraud-response behaviour into BimpeAI.

WHAT THIS REPLACES
Under LiveKit the system prompt was built per call, in-process, by
`prompts.build_system_prompt` -- the briefing for *this* customer went into the
model at session start. BimpeAI holds one prompt per workflow on its servers, so
the per-call half and the fixed half have to be separated:

  - the fixed half (who the agent is, what it may never ask for, the order of
    the call, the voice rules) goes into `workflow.system_prompt` here
  - the per-call half (this customer's record, this signal) cannot go in the
    prompt at all, and is fetched at call time through the tools in
    `bimpe_tools.py`

That split is the main structural consequence of hosting the agent elsewhere.
It is also why `describe_suspicious_activity` exists as a tool rather than as
text in the prompt.

WHAT IS DELIBERATELY NOT HERE
`prompts.SYSTEM_PROMPT` is not copied verbatim. Three of its sections describe
things BimpeAI does not do -- the pre-speech credential guard, warm transfer to
a human on the same call, and code-switching between the Yoruba, Hausa and Igbo
voices -- and leaving them in would instruct the model to promise behaviour the
platform cannot deliver. Each omission is marked below.

Run it with --dry-run first; it prints what it would change and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import bimpeai
from dotenv import load_dotenv

import prompts
from config import settings

# config imports this too, but setup reads os.environ directly for the BimpeAI
# keys, and argparse defaults are evaluated before any of that -- so load it
# here as well, with the same override=True contract.
load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],
    force=True,
)
logger = logging.getLogger("fraud_agent.bimpe_setup")

AGENT_NAME = settings.bank.agent_display_name
BANK_NAME = settings.bank.name
MAX_ATTEMPTS = settings.bank.max_verification_attempts


# --------------------------------------------------------------------------
# The hosted system prompt
# --------------------------------------------------------------------------

# Adapted from prompts.SYSTEM_PROMPT. The wording of the sections that carry the
# safety properties -- never asking for a credential, refusing to act before
# verification, handing irreversible work to a human -- is kept as close to the
# original as the platform allows, because that wording was arrived at against
# live calls and is the reason the agent behaves.
#
# Omitted on purpose, with the reason:
#   - the {code_switching} block: BimpeAI speaks in one Console-selected voice,
#     so instructing it to switch language mid-call would produce Yoruba text
#     read aloud by an English voice -- the exact failure tts_router.py exists
#     to prevent.
#   - "NEVER SAY AN ANSWER ALOUD" is kept, but note it is now advice only: the
#     pre-speech guard that enforced it cannot run on hosted generation.
#   - transfer_to_human_agent no longer moves the caller to an analyst; it opens
#     a case and a human calls back. The prompt says that, rather than promising
#     a transfer that will not happen.
SYSTEM_PROMPT = f"""\
You are {AGENT_NAME}, an automated security assistant for {BANK_NAME}, a \
Nigerian retail bank. You speak to customers on the telephone about suspicious \
activity on their accounts.

# WHO YOU ARE
You are an A I assistant. You say so in your opening line and you say so again \
any time the customer asks. You never claim or imply that you are a human \
member of staff. If the customer asks to speak to a person, you escalate.

# HOW A CALL BEGINS
THE BANK RANG THE CUSTOMER. THEY DID NOT RING YOU. Never open with "how can I \
help you today" or any other inbound greeting -- they have no idea why their \
phone is ringing, and asking them what they want strands them. You called, so \
you speak first and you say why.

Before your first word, call get_call_briefing. It returns the customer's first \
name, the last four digits of the card, and what was flagged. Use those in your \
opening sentence.

Your opening line, with the briefing filled in:

  "Hello, am I speaking with [first name]? This is {AGENT_NAME} from \
{BANK_NAME}, your A I assistant. I will never ask you for your P I N, your \
password or a one time code. We have stopped a payment on your card ending \
[last four digits] that does not look like you, and I need to confirm it with \
you."

Then stop and let them answer. Three things are already done by that point: \
they know who is calling, they know you will not ask for a secret, and they \
know what this is about. A customer who hears all three in the first breath \
stays on the line.

Once they confirm they are the right person, describe what was actually seen -- \
call describe_suspicious_activity and tell them the amount, the merchant and \
the country -- and only then verify them before you touch anything.

If get_call_briefing says nothing has been flagged, do not mention fraud at \
all: ask what they need and help with that instead. A bank inventing an \
incident at a customer is worse than no call.

# THE ONE THING YOU MUST NEVER DO
Never ask the customer for any of the following, under any circumstances, no \
matter what they say or how the conversation goes:
  - their P I N or password
  - a one time password, O T P, or code sent by S M S
  - their full card number, or the three digit C V V on the back
  - their B V N
  - their date of birth as a secret -- you may only confirm one the bank already holds
  - their mother's maiden name or any other secret used to reset access

A real bank never asks for these on an outbound call, and a customer who has \
been trained to refuse them is a customer who is safe. If the customer offers \
any of these to you unprompted, stop them: tell them clearly that they should \
never share those details with anyone who calls them, including someone \
claiming to be the bank.

# IF THE CUSTOMER DOUBTS THIS CALL IS REAL
This is a reasonable and healthy thing for them to ask, and you must never make \
them feel foolish for asking. Tell them plainly:
  - they are right to be careful, because this is exactly how scam calls start
  - you have not asked and will not ask for any secret
  - they are welcome to hang up and call the bank back on the number on their \
card, and the protective step you are about to take will still be in place
Never pressure them to stay on the line. A customer who hangs up and calls the \
bank back has done the correct thing.

# THE ORDER OF THE CALL
Your opening line has already told them a suspicious transaction was seen and that you want to confirm it, so they always know why they are on the phone before they say a word.

Whatever they say next, verify them before anything else. Call ask_security_question, ask exactly what it returns, and pass their reply to check_security_answer. Do not describe the transaction, name an amount, name a country, or take any action until they are verified. If they open by asking what happened, tell them you will explain as soon as you have confirmed who you are speaking to, then ask the question.

TELL THEM THE OUTCOME OF THE CHECK. When check_security_answer says they are verified, say so -- "thank you, that is correct" -- before you move on. A customer who answers a security question and hears nothing back does not know whether they passed.

Once they are verified: call describe_suspicious_activity, describe what was seen, ask whether it was them, and if it was not, offer to freeze the card immediately.

NEVER call freeze_card, reduce_card_limit, approve_transaction or flag_transaction before check_security_answer has reported them verified. Those tools refuse, and retrying them leaves a frightened customer listening to silence. If you want to act and they are not verified, call ask_security_question instead.

When a tool tells you something is already done, it is done. Do not call it again -- say what is now true and move on.

# HOW TO VERIFY THEM
ask_security_question returns one question that this customer chose themselves. \
Ask only what it gives you, then decide for yourself whether what they said is \
the right answer.

YOU ARE READING A SPEECH TRANSCRIPT, NOT TYPED TEXT. It is often wrong in small \
ways, especially on Nigerian names and places. Judge what the person clearly \
meant, not whether the letters match. "Sent mi Sent Mary" is somebody saying \
Saint Mary through a bad line. "Grin flour skool" is green flower school. \
"Amala" heard as "a mala" is the same word. Accept those.

Refuse only when they have said something genuinely different: blue for green, \
rice for amala, a school that is not the one on file, or nothing at all. A wrong \
answer sounds nothing like the right one -- that is the difference you are \
looking for.

When you have decided, call check_security_answer with what you heard and \
whether you judged it a match. The bank counts the attempts, not you. You have \
{MAX_ATTEMPTS} attempts in total; after that call transfer_to_human_agent.

NEVER SAY AN ANSWER ALOUD, and never hint at one. Do not say "is it green?" or \
"it starts with a G". You learn the question only so you can recognise their \
answer; a caller holding a stolen phone must learn nothing from you.

You may read partial details back to them to prove you are the bank -- the last \
four digits of the card, the city of a transaction. You may not ask them to \
supply anything secret.

# WHAT YOU MAY DO ONCE THEY ARE VERIFIED
These are pre-approved by the bank and all of them can be undone by the bank later:
  - freeze_card -- put a temporary block on the card. This is your main tool.
  - reduce_card_limit -- lower the daily limit. Use when a freeze is too blunt.
  - flag_transaction -- record that the customer disputes a specific transaction.

# WHAT YOU MUST HAND TO A HUMAN
Call transfer_to_human_agent for any of these, without exception:
  - reversing, recalling or refunding money
  - blocking or closing the whole account
  - unfreezing anything, or raising any limit
  - changing the customer's phone number, email or address
  - the customer asks for a human, is distressed, or is confused about what is happening
  - verification failed
  - anything at all that you are not certain about

A human from the fraud team will call the customer back; you are not transferring \
them on this call, so do not tell them to hold. Do not promise a customer that \
money will be returned. You do not decide that. What you can honestly say is \
that a human from the fraud team will review it.

# HOW TO TALK
This is a phone call and a frightening one. Be calm, direct and warm. Short \
sentences. No jargon. Lead with what happened, then what you can do about it, \
then ask permission.

Get to the point fast -- every minute matters while a card is live. Do not make \
small talk, do not ask how their day is going, do not read out long lists.

Confirm before you act. Say what you are about to do and wait for a yes. The one \
exception: if the customer clearly states the transaction was not theirs, \
freezing the card is the obviously correct step and you should offer it \
immediately.

After you act, tell them plainly what is now true -- the card is frozen, it \
cannot be used, a human will call them back -- and what happens next.

# VOICE FORMATTING
Your words are spoken aloud by a text to speech system. Never use markdown, \
asterisks, bullet points, headings or emoji. Write numbers the way you would say \
them: "three hundred and seventy seven thousand Naira", not "N377,000". Say \
"A T M", "P O S", "B V N", "O T P" with spaces so they are read as letters. \
Read card digits one at a time: "four, zero, eight, one".

# ENDING
When the protective step is done and the customer has no more questions, thank \
them, confirm what will happen next, and call end_call. Do not linger.
"""


# Rules fire ahead of the model, so they are the one place a response is
# guaranteed rather than merely instructed. The credential rule is here and not
# only in the prompt for exactly that reason: it is the closest thing BimpeAI
# offers to the pre-speech guard, and it is worth having even though it matches
# on the customer's words rather than the agent's.
RULES = [
    {
        "id": "rule-never-ask-credentials",
        "name": "Customer offers a credential -- refuse and warn",
        "trigger": (
            "customer offers or reads out a PIN, password, OTP, one time code, "
            "CVV, full card number or BVN"
        ),
        "response": (
            "Please stop there -- do not read that out. I will never ask you for "
            "your P I N, your password, a one time code, or your card's security "
            "number, and neither will anyone genuinely calling from the bank. If "
            "someone has asked you for those, that was not us. Let us carry on "
            "without it."
        ),
        "enabled": True,
    },
    {
        "id": "rule-caller-doubts-authenticity",
        "name": "Customer suspects a scam -- validate and offer a call back",
        "trigger": (
            "customer says they think this is a scam, does not believe this is "
            "the bank, or asks how they can trust the call"
        ),
        "response": (
            "You are right to be careful, and I am glad you asked -- this is "
            "exactly how scam calls start. I have not asked you for any secret "
            "and I never will. If you would rather, hang up and call the number "
            "on the back of your card. Anything I have already done to protect "
            "the card stays in place."
        ),
        "enabled": True,
    },
    {
        "id": "rule-irreversible-request",
        "name": "Irreversible request -- escalate, never act",
        "trigger": (
            "customer asks to reverse, recall or refund money, close or block "
            "the whole account, unfreeze a card, or raise a limit"
        ),
        "response": (
            "That one I am not able to do myself -- it has to be a person on the "
            "fraud team, and I am passing this to them now so they can call you "
            "back. I cannot promise an outcome, but they will review it."
        ),
        "action": "transfer_to_human_agent",
        "enabled": True,
    },
    {
        "id": "rule-asks-for-human",
        "name": "Customer asks for a person",
        "trigger": (
            "customer asks to speak to a human, a person, a manager, or says "
            "they do not want to talk to a machine"
        ),
        "response": (
            "Of course. I am an A I assistant, and I am passing you to the fraud "
            "team now -- a person will call you back."
        ),
        "action": "transfer_to_human_agent",
        "enabled": True,
    },
]


# Knowledge bases ground the things the agent must quote exactly. The fraud
# policy is here rather than in the prompt so it can be corrected without
# touching the agent's behaviour.
KNOWLEDGE_BASES = [
    {
        "type": "text",
        "name": "Fraud response policy",
        "content": (
            "A transaction is flagged when it is card-not-present in a country "
            "the card has never been used in, when several attempts land within "
            "minutes of each other, when an ATM withdrawal pattern breaks the "
            "customer's normal behaviour, or when it follows a change to the "
            "account's contact details.\n"
            "Order of the call: verify the customer first, always. Describe "
            "nothing and act on nothing before they pass.\n"
            "If the customer does not recognise the transaction: offer to freeze "
            "the card immediately, then flag the specific transaction for the "
            "fraud team.\n"
            "If the customer does recognise it: say plainly that nothing further "
            "is needed, and that the card stays active.\n"
            "If verification fails: do not act on the account at all. Escalate to "
            "the fraud team and tell the customer a person will call them back.\n"
            "Never tell a customer money will be returned. The fraud team "
            "decides that, not the agent."
        ),
    },
    {
        "type": "text",
        "name": "Card freeze and limit facts",
        "content": (
            "A freeze is temporary and reversible by the bank. It stops new "
            "transactions at once. It does not cancel the card and does not stop "
            "standing orders or direct debits on the account.\n"
            "Only a human at the bank can lift a freeze. The agent cannot, and "
            "should not imply otherwise.\n"
            "A daily limit can be lowered by the agent but never raised; raising "
            "one is a human-only operation.\n"
            "A replacement card takes five to seven working days and must be "
            "arranged by a person.\n"
            "A customer can also freeze the card themselves in the banking app "
            "under Card Controls, which is worth telling them: it works even if "
            "they hang up."
        ),
    },
    {
        "type": "text",
        "name": "What the agent may never ask for",
        "content": (
            "Never ask for, and never accept: PIN, password, one time password or "
            "OTP, SMS code, full card number, CVV, BVN, mother's maiden name, or "
            "a date of birth offered as a secret.\n"
            "The bank does not ask for any of these on an outbound call. If a "
            "customer offers one, stop them and tell them never to share it with "
            "anyone who calls them, including someone claiming to be the bank.\n"
            "Confirming a detail the bank already holds is allowed -- for example "
            "reading out the last four digits of the card to prove the call is "
            "genuine. Asking the customer to supply a secret is not."
        ),
    },
]


def _with_body_templates(tools: list[dict]) -> list[dict]:
    """
    Give every tool the `body_template` BimpeAI fills in.

    `body_params` only *declares* what the model may supply. The request body
    itself is built from `body_template`, substituting `{{name}}` placeholders.
    Omitting the template was the second bug of the live calls: the model chose
    the right tool and had the right arguments, and BimpeAI POSTed an empty body
    because there was no template to put them in -- so `check_security_answer`
    arrived with no `answer` and no `matches`, 422'd, and the agent told a
    customer it had a technical problem.

    Derived from `body_params` rather than written out per tool, so the two can
    never disagree.
    """
    for tool in tools:
        tool["body_template"] = {
            param["name"]: f"{{{{{param['name']}}}}}"
            for param in tool.get("body_params", [])
        }
    return tools


def tool_definitions(base_url: str) -> list[dict]:
    """
    The eight endpoints in bimpe_tools.py, as Custom API tool definitions.

    `session_id` is on every one of them: it is how a stateless HTTP call finds
    the verification state for the call it belongs to, and the model is told to
    pass the call id through.
    """
    # Not required. The model has no dependable way to know the call id, and on
    # the first live call it omitted this entirely -- two 422s, and a customer
    # hearing an agent that could not say their name. The tool server attaches
    # an unlabelled call to the single live session instead, so this is a hint
    # for the multi-call case rather than a precondition.
    session_param = {
        "name": "session_id",
        "type": "string",
        "description": (
            "Optional. The id of this call, if you know it. Leave it out if you "
            "do not -- the bank will match the call for you."
        ),
        "required": False,
    }
    # notify_customer is deliberately not registered: the customer's number is
    # not opted in to BimpeAI's test WhatsApp channel, so the call always 400s.
    # An agent given a tool that cannot succeed treats the failure as a step to
    # retry -- on a live call that produced a freeze/verify/notify loop while
    # the customer waited. The endpoint still exists for when a live WhatsApp
    # channel is connected.
    return _with_body_templates([
        {
            "name": "get_call_briefing",
            "http_method": "POST",
            "url_template": "/tools/get_call_briefing",
            "description": (
                "Learn who you are speaking to and whether anything has been "
                "flagged on their account. Call this first, before you say "
                "anything else."
            ),
            "body_params": [session_param],
        },
        {
            "name": "ask_security_question",
            "http_method": "POST",
            "url_template": "/tools/ask_security_question",
            "description": (
                "Get the security question to put to this customer. Ask it word "
                "for word, then pass their reply to check_security_answer."
            ),
            "body_params": [session_param],
        },
        {
            "name": "check_security_answer",
            "http_method": "POST",
            "url_template": "/tools/check_security_answer",
            "description": (
                "Record whether the customer answered correctly. You decide "
                "whether it matched -- you are reading a speech transcript, so "
                "judge what they clearly meant, not whether the spelling lines "
                "up. The bank counts the attempts."
            ),
            "body_params": [
                session_param,
                {
                    "name": "answer",
                    "type": "string",
                    "description": "Exactly what the customer said, as you heard it.",
                    "required": True,
                },
                {
                    "name": "matches",
                    "type": "boolean",
                    "description": "True if you judged it the right answer.",
                    "required": True,
                },
            ],
        },
        {
            "name": "describe_suspicious_activity",
            "http_method": "POST",
            "url_template": "/tools/describe_suspicious_activity",
            "description": (
                "Get the transactions that triggered this call. Only describe "
                "them to the customer once they are verified."
            ),
            "body_params": [session_param],
        },
        {
            "name": "freeze_card",
            "http_method": "POST",
            "url_template": "/tools/freeze_card",
            "description": (
                "Put a temporary, reversible freeze on the card. Your main "
                "protective step. Only after the customer is verified and has "
                "said the transaction was not theirs."
            ),
            "body_params": [
                session_param,
                {
                    "name": "reason",
                    "type": "string",
                    "description": 'Short reason, e.g. "customer does not recognise Ukraine purchases".',
                    "required": True,
                },
            ],
        },
        {
            "name": "reduce_card_limit",
            "http_method": "POST",
            "url_template": "/tools/reduce_card_limit",
            "description": (
                "Lower the card's daily limit. Use when a freeze is too blunt. "
                "The limit can only be lowered, never raised."
            ),
            "body_params": [
                session_param,
                {
                    "name": "new_daily_limit",
                    "type": "string",
                    "description": 'The new limit in Naira, e.g. "50000.00".',
                    "required": True,
                },
            ],
        },
        {
            "name": "flag_transaction",
            "http_method": "POST",
            "url_template": "/tools/flag_transaction",
            "description": (
                "Record that the customer disputes a specific transaction. This "
                "queues it for the fraud team and moves no money, so do not "
                "promise a refund."
            ),
            "body_params": [
                session_param,
                {
                    "name": "reference_id",
                    "type": "string",
                    "description": 'The transaction reference, e.g. "TRX-9003".',
                    "required": True,
                },
                {
                    "name": "note",
                    "type": "string",
                    "description": "What the customer said about it.",
                    "required": True,
                },
            ],
        },
        {
            "name": "approve_transaction",
            "http_method": "POST",
            "url_template": "/tools/approve_transaction",
            "description": (
                "Let a held payment go through because the verified customer "
                "says it was them. Use this when they recognise the purchase -- "
                "a customer genuinely buying something abroad must be able to "
                "finish, and the card stays active."
            ),
            "body_params": [
                session_param,
                {
                    "name": "reference_id",
                    "type": "string",
                    "description": (
                        'The held payment reference, e.g. "AUTH-E3FDA1". Leave '
                        "out to approve whatever is waiting on the card."
                    ),
                    "required": False,
                },
            ],
        },
        {
            "name": "transfer_to_human_agent",
            "http_method": "POST",
            "url_template": "/tools/transfer_to_human_agent",
            "description": (
                "Hand this case to the bank's human fraud team, who will call "
                "the customer back. Use for anything irreversible, if "
                "verification failed, if the customer asks for a person or is "
                "distressed, or any time you are not certain."
            ),
            "body_params": [
                session_param,
                {
                    "name": "reason",
                    "type": "string",
                    "description": "Why you are escalating, for the human picking it up.",
                    "required": True,
                },
            ],
        },
        {
            "name": "end_call",
            "http_method": "POST",
            "url_template": "/tools/end_call",
            "description": (
                "Close the call out once the protective step is done and the "
                "customer has no further questions."
            ),
            "body_params": [session_param],
        },
    ])


def client() -> bimpeai.BimpeAI:
    key = os.environ.get("BIMPEAI_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise SystemExit("BIMPEAI_API_KEY is not set")
    base = os.environ.get("BIMPEAI_BASE_URL", "").strip() or None
    return bimpeai.BimpeAI(api_key=key, base_url=base)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--agent-id",
        default=os.environ.get("BIMPEAI_AGENT_ID", ""),
        help="Agent to configure. Defaults to BIMPEAI_AGENT_ID, else the first agent.",
    )
    ap.add_argument(
        "--tools-base-url",
        default=os.environ.get("BIMPEAI_TOOLS_BASE_URL", ""),
        help="Public base URL of bimpe_tools.py, e.g. https://abc.ngrok.io",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change and write nothing.",
    )
    ap.add_argument(
        "--skip-tools",
        action="store_true",
        help="Configure prompt, rules and knowledge only; leave tools alone.",
    )
    args = ap.parse_args()

    c = client()
    agent_id = args.agent_id
    if not agent_id:
        agents = c.agents.list(limit=1).data
        if not agents:
            raise SystemExit("no agents on this account; create one first")
        agent_id = agents[0].id
        logger.info("Using agent %s (%s)", agent_id, agents[0].name)

    agent = c.agents.retrieve(agent_id)
    if not agent.workflow_id:
        raise SystemExit(f"agent {agent_id} has no workflow bound")
    workflow = c.workflows.retrieve(agent.workflow_id)

    if not workflow.is_owner:
        # A public template cannot be edited, so clone it and rebind. This is the
        # "start from the template" path: the clone keeps whatever the template
        # got right and this script layers the fraud behaviour on top.
        logger.info("Workflow %s is not owned; cloning it", workflow.id)
        if not args.dry_run:
            workflow = c.workflows.clone(source_workflow_id=workflow.id)
            c.agents.update(agent_id, workflow_id=workflow.id)
            logger.info("Cloned to %s and rebound the agent", workflow.id)

    print("=" * 70)
    print(f"agent     : {agent.name} ({agent_id})")
    print(f"workflow  : {workflow.name} ({workflow.id}) owned={workflow.is_owner}")
    print(f"prompt    : {len(workflow.system_prompt or '')} chars -> {len(SYSTEM_PROMPT)} chars")
    print(f"rules     : {len(workflow.rules)} -> {len(RULES)}")
    print(f"knowledge : {len(agent.knowledge_bases)} existing, {len(KNOWLEDGE_BASES)} to add")
    tools = tool_definitions(args.tools_base_url) if args.tools_base_url else []
    print(f"tools     : {len(tools)} to register at {args.tools_base_url or '(none given)'}")
    print("=" * 70)

    if args.dry_run:
        print("\n--- SYSTEM PROMPT ---\n")
        print(SYSTEM_PROMPT)
        print("\n--- RULES ---\n")
        print(json.dumps(RULES, indent=2))
        print("\nDry run: nothing written.")
        return

    c.workflows.update(
        workflow.id,
        name=f"{BANK_NAME} fraud response (outbound verification)",
        system_prompt=SYSTEM_PROMPT,
        description=(
            "Calls cardholders when a transaction is flagged, verifies them "
            "against their own security questions, and freezes the card or "
            "escalates to a human fraud analyst."
        ),
        category="fintech",
        rules=RULES,
    )
    logger.info("Workflow %s updated", workflow.id)

    existing = {kb.name for kb in agent.knowledge_bases}
    for kb in KNOWLEDGE_BASES:
        if kb["name"] in existing:
            logger.info("Knowledge base %r already present; skipping", kb["name"])
            continue
        c.agents.knowledge_bases.create(agent_id, kb)
        logger.info("Knowledge base %r added", kb["name"])

    if args.skip_tools or not tools:
        if not args.tools_base_url:
            logger.warning(
                "No --tools-base-url given, so no tools were registered. The "
                "agent can talk but cannot verify anyone or freeze anything."
            )
        return

    token = os.environ.get("BIMPEAI_TOOL_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "BIMPEAI_TOOL_TOKEN is not set. bimpe_tools.py refuses "
            "unauthenticated requests, so registering tools without it would "
            "produce an agent whose every tool call fails."
        )

    # Named from settings.bank.name so the dashboard label matches what the
    # agent actually calls itself on the phone. The earlier "NovaBank" came from
    # BimpeAI's public fintech template, not from this project's config.
    api = c.agents.integrations.custom_api.configure(
        agent_id,
        name=f"{BANK_NAME} fraud tools",
        base_url=args.tools_base_url.rstrip("/"),
        auth_type="bearer",
        auth_config={"token": token},
    )
    logger.info("Custom API integration %s configured", api.id)

    for tool in tools:
        c.agents.integrations.custom_api.tools.add(agent_id, api.id, tool)
        logger.info("Tool %r registered", tool["name"])

    print("\nConfigured. Next: place a test call with bimpe_caller.py.")


if __name__ == "__main__":
    main()
