# Running the fraud agent on BimpeAI

The agent now runs on BimpeAI's servers instead of as a LiveKit worker in this
process. Three files make that work:

| File | Replaces | What it does |
|---|---|---|
| `bimpe_tools.py` | the `@function_tool` methods in `agent.py` | serves the bank's operations over HTTP for BimpeAI to call |
| `bimpe_setup.py` | `prompts.build_system_prompt` at session start | pushes the prompt, rules, knowledge bases and tool definitions into BimpeAI |
| `bimpe_caller.py` | `caller.py` | briefs the tool server, then places the call with `calls.make` |

`bank_api.py`, `bank_data.py`, `verification.py`, `prompts.py` and `config.py`
are unchanged and still the source of truth.

## Why the tools are an HTTP service

BimpeAI runs the model on its own infrastructure, so a tool cannot be a Python
method any more — it has to be a URL the platform can reach. That has one
consequence worth stating plainly: **`bimpe_tools.py` must be reachable from the
public internet, and it can freeze cards.** It refuses every unauthenticated
request, and refuses to start at all without a token, but the token is the only
thing between the internet and `freeze_card`. Treat it accordingly.

The three-layer authority model from the LiveKit version mostly survives:

1. the prompt and rules tell the model what it may do — now in the workflow
2. the tool refuses to act before verification passes — now in `bimpe_tools.py`
3. `bank_api.py` refuses human-only operations regardless — unchanged

## Setup

```bash
pip install fastapi uvicorn httpx bimpeai

# .env — note BIMPEAI_API_KEY is quote-wrapped in the current file and the
# scripts strip the quotes; removing them from .env is cleaner.
BIMPEAI_API_KEY=sk_...
BIMPEAI_AGENT_ID=cmumd4r0x005hkt89pu3x4ekp   # optional; defaults to first agent
BIMPEAI_TOOL_TOKEN=<a long random string you choose>
BIMPEAI_TOOLS_BASE_URL=https://<public host>  # no trailing slash
```

### 1. Start the tool server

```bash
uvicorn bimpe_tools:app --host 0.0.0.0 --port 8080
curl -s localhost:8080/health      # token_configured must be true
```

Run **one worker only**. Verification state lives in process memory
(`_SESSIONS`), so a second worker would see a caller as unverified half the
time. Move `_SESSIONS` to Redis before scaling out.

### 2. Expose it

BimpeAI has to reach it, so for local testing:

```bash
ngrok http 8080        # then set BIMPEAI_TOOLS_BASE_URL to the https URL
```

### 3. Configure the agent

```bash
python bimpe_setup.py --dry-run        # prints the prompt and rules, writes nothing
python bimpe_setup.py --tools-base-url "$BIMPEAI_TOOLS_BASE_URL"
```

This rewrites the workflow's system prompt, replaces its rules with the four
fraud rules, adds three knowledge bases, and registers nine tools as a Custom
API integration. It is idempotent on knowledge bases (matched by name); rules
and the prompt are overwritten each run.

### 4. Set the voice (Console, not API)

Channels and voice cannot be configured through the API. In the Console:
**Deploy → Telephony → Set up**, then **Settings → Voice** for the voice and
greeting, and **Settings → Agent** for the escalation email.

### 5. Place a call

```bash
python bimpe_caller.py --list-signals
python bimpe_caller.py FRD-CARD-FOREIGN --to "+234..."     # test call
python bimpe_caller.py FRD-CARD-FOREIGN --live             # real call
```

`--to` dials a number other than the one on file; it exists for testing against
your own phone. Never use it in production — it reads one customer's account
details to another number.

Test calls (`is_test_call=true`, the default) use BimpeAI test telephony and
consume no live minutes. `--live` requires a phone number provisioned under
**Team settings → Phone numbers** and assigned to the agent; this account has
none yet, and `bimpe_caller.py` will say so rather than failing obscurely.

## What did not survive the move

These were real capabilities of the LiveKit version and the hosted platform has
no equivalent. None of them is a bug to be fixed later.

- **Deepgram STT and PrepAI/Intron TTS.** BimpeAI does the whole speech loop.
  There is no audio, STT or TTS endpoint in the SDK or the API. Switching to
  PrepAI later means moving the call back into this process, not changing a
  setting.
- **Yoruba, Hausa and Igbo voices, and mid-call code-switching.**
  `tts_router.py`, `intron_tts.py`, `intron_stt.py`, `code_switching.py` and
  `stt_providers.py` are kept on disk for that eventual switch, and are not
  used by anything here. BimpeAI speaks in one Console-selected voice.
- **The pre-speech credential guard.** `mentions_forbidden_credential` used to
  run over every utterance *before* the TTS spoke it, so a model that asked for
  a PIN was never heard. Hosted generation cannot be intercepted.
  `/tools/check_utterance` still exists for auditing a transcript afterwards,
  and the `rule-never-ask-credentials` rule catches the customer *offering* a
  credential — but neither is the same guarantee.
- **Warm transfer to a human on the same call.** `transfer_to_human_agent` now
  opens a fraud case and reports that a person will call back. Pair it with
  `conversations.set_ai_status(is_ai_chat_paused=True)` on chat channels.
- **Handoff between the bank and telecom agents.** `switch_to_telecom` was an
  in-process agent swap. Two BimpeAI agents cannot hand a live call to each
  other; this would need two phone numbers, or one merged agent.
- **Barge-in and turn control.** `silero` VAD, noise cancellation and
  interrupt handling were LiveKit owning the audio.

## Known rough edge

BimpeAI accepts no metadata at dial time, so `bimpe_caller.py` briefs the tool
server under an id it generates, then calls `/sessions/alias` to register the
same briefing under the real `call_id` once `calls.make` returns. Both keys
point at one session object. If BimpeAI later supports call metadata, the alias
step can go.
