# Noba - Bimpe AI Banking Voice Agent
A Nigerian voice agent that handles bank fraud response and telecom customer
care, built for the Sahara CodeSwitch Africa Challenge. Now powered by **Bimpe AI** infrastructure.

## The Problem
A Nigerian caller under stress does not speak one language. They move between
English, Pidgin, Yoruba, Hausa and Igbo inside a single sentence, without
noticing they are doing it. Every automated phone line in the country handles
one language at a time, so the caller has to translate their own emergency
before anyone will help them.

Two places where that costs the most:

**Fraud.** Banks wait for fraud to complete before flagging it. By the time a
customer reaches anyone, the money has gone and the remaining options are a
written dispute and weeks of waiting.

**Telecom care.** The path to a person runs through a menu — press 1, press 2,
press 3 — designed around the company's departments rather than the caller's
problem.

## What Noba Does

One number answers both lines. It asks which one you need and routes you.
It understands a sentence that mixes languages and answers in the way the caller
spoke, rather than correcting them into English. It verifies a caller without
ever asking for a PIN, a password or a one-time code, takes a protective action
the bank has pre-approved, and hands anything irreversible to a human.
It reaches people on a normal phone call or on WhatsApp, so it works whether
or not the caller has a smartphone and data.

## What It Can Act On

The agent does not only talk. On the bank line it can verify the caller against
the questions the bank already holds, tell them what was seen on their account,
freeze a card, reduce a daily limit, and flag a transaction for review. On the
telecom line it can diagnose a fault on the line, check balances and recent
transactions, restore a bundle that was paid for but never delivered, credit a
recharge that did not land, and send network settings.

Every one of those is reversible, and every one is recorded against the account
with a note saying the agent did it.

## Where It Stops

Verification never involves a secret. The agent does not ask for a PIN, a
password, a one-time code or a card number, and it will not accept one if it is
offered — it says so in the first line of the call, before anything is asked.

Anything that cannot be undone goes to a person. That means reversing money,
closing or blocking an account, unfreezing what was frozen, and changing the
contact details on file. The agent has no way to do any of it: the capability
does not exist for it to reach for.

It also hands over when verification fails, when the caller asks for a human,
when someone is distressed, and whenever it is not certain. A case is opened
with what the agent already did and why it stepped back, so the person picking
it up starts with the context instead of asking the customer to repeat
everything.

---

## Bimpe AI Architecture

Noba now runs on **Bimpe AI's hosted infrastructure**, moving the agent execution from a local LiveKit worker to Bimpe AI's servers. This architecture provides scalability and reliability while maintaining the security boundaries that protect customer data.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Customer                                 │
│                      (Phone / WhatsApp)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Bimpe AI Platform                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Speech Pipeline (STT/TTS)                               │   │
│  │  - Speech-to-Text conversion                             │   │
│  │  - Text-to-Speech synthesis                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                    │
│  ┌──────────────────────────▼──────────────────────────────┐   │
│  │  LLM Agent (Reasoning & Conversation)                    │   │
│  │  - Understands code-switched Nigerian languages          │   │
│  │  - Makes decisions on customer verification              │   │
│  │  - Determines protective actions                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                    │
│                             │ (HTTP Tool Calls)                  │
└─────────────────────────────┼────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Bank Tools API Server                           │
│                  (bimpe_tools.py)                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Authentication Layer (Bearer Token)                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Verification State Management                           │   │
│  │  - Per-session challenge tracking                        │   │
│  │  - Attempt limits enforcement                            │   │
│  │  - Security question validation                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Tool Endpoints                                          │   │
│  │  - ask_security_question                                 │   │
│  │  - check_security_answer                                 │   │
│  │  - describe_suspicious_activity                          │   │
│  │  - freeze_card                                           │   │
│  │  - reduce_card_limit                                     │   │
│  │  - flag_transaction                                      │   │
│  │  - transfer_to_human_agent                               │   │
│  │  - approve_transaction                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Bank API (bank_api.py)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Authorization Layer                                     │   │
│  │  - Pre-approved actions only                             │   │
│  │  - Human-only operations blocked                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Bank Operations                                         │   │
│  │  - Customer & account management                         │   │
│  │  - Card operations                                       │   │
│  │  - Transaction management                                │   │
│  │  - Fraud case creation                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│               Bank Data Store (bank_data.py)                     │
│  - Customer records                                              │
│  - Account balances                                              │
│  - Card details                                                  │
│  - Transaction history                                           │
│  - Security questions & answers                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

#### 1. **Bimpe AI Platform** (Hosted)
- **Speech Processing**: Handles STT (Speech-to-Text) and TTS (Text-to-Speech)
- **LLM Agent**: Runs the conversational AI, understands code-switched Nigerian languages
- **Telephony**: Manages phone calls and WhatsApp connections

#### 2. **Bank Tools API Server** (`bimpe_tools.py`)
**Why it exists**: Bimpe AI runs the agent remotely, so tools must be HTTP endpoints rather than local Python functions.

**Security**:
- Bearer token authentication (`BIMPEAI_TOOL_TOKEN`)
- Must be publicly accessible (use ngrok for testing)
- **Critical**: This server can freeze cards - treat the token as the only barrier

**Responsibilities**:
- Session management (verification state per call)
- Enforces attempt limits on security questions
- Exposes bank operations as HTTP endpoints
- Logs all requests and responses with timing

**Key Endpoints**:
- `POST /sessions` - Brief the agent on a new call
- `POST /sessions/alias` - Link session IDs when call is placed
- `POST /tools/ask_security_question` - Get next verification question
- `POST /tools/check_security_answer` - Validate customer answer
- `POST /tools/freeze_card` - Temporarily freeze suspicious card
- `POST /tools/flag_transaction` - Mark transaction for fraud review
- `POST /tools/transfer_to_human_agent` - Escalate to human operator

#### 3. **Three-Layer Security Model**

The system protects against unauthorized actions through three independent layers:

**Layer 1: Prompt & Rules** (in Bimpe AI workflow)
- Tells the model what it may and may not do
- Defines when to transfer to human
- Never request credentials from customers

**Layer 2: Tool Verification** (in `bimpe_tools.py`)
- Refuses to act before customer is verified
- Enforces attempt limits on security questions
- Checks verification state on every protected action

**Layer 3: Bank API Authorization** (in `bank_api.py`)
- Blocks human-only operations (money reversals, account closures)
- Validates all operations regardless of tool layer
- Final authority on what can be done

Even if the model ignores instructions, it still cannot:
- Freeze a card for an unverified caller (Layer 2 blocks it)
- Reverse a transaction (Layer 3 blocks it)
- Access another customer's data (Session isolation)

#### 4. **Bank API** (`bank_api.py`)
The interface to the bank's systems. Enforces authorization rules:
- **Pre-approved actions**: freeze card, reduce limits, flag transactions
- **Human-only operations**: reverse transactions, close accounts, unfreeze cards
- All actions are logged with actor="agent"

#### 5. **Verification System** (`verification.py`)
Handles customer identity verification:
- Uses security questions the customer chose themselves
- Never involves PINs, passwords, or OTPs
- Tracks attempts per session (default: 3 attempts max)
- Guards against credential requests in agent speech

#### 6. **Call Flow Manager** (`bimpe_caller.py`)
Initiates outbound fraud calls:
1. Briefs the tool server with customer & signal data
2. Places the call via Bimpe AI
3. Links the returned `call_id` to the session
4. Monitors call status

### Data Flow: Fraud Detection to Call

```
1. Payment Attempt
   Customer tries to pay → POST /api/payments/attempt
   
2. Risk Analysis
   Transaction analyzed → card_authorization.authorize()
   
3. If Flagged
   a. Authorization held as PENDING
   b. Session briefed: POST /sessions with signal_id
   c. Call placed: bimpeai.calls.make()
   d. Call ID aliased: POST /sessions/alias
   
4. Agent Conversation
   Agent: GET /tools/get_call_briefing
        → Learns customer name, card details, what was flagged
   
   Agent: POST /tools/ask_security_question
        → Receives verification question
   
   Customer: [Answers question]
   
   Agent: POST /tools/check_security_answer
        → Verification passes/fails
   
5. Protective Action (if verified)
   Agent: POST /tools/freeze_card
        → Card frozen, customer notified
   
   OR
   
   Agent: POST /tools/transfer_to_human_agent
        → Case opened, call transferred/callback scheduled
   
6. Call Ends
   Agent: POST /tools/end_call
        → Fraud case created with actions taken
   
7. Resolution
   Authorization approved or declined based on outcome
```

### Session & State Management

**Challenge**: Bimpe AI runs remotely, so verification state cannot live in the agent's memory.

**Solution**: In-process session store (`_SESSIONS` dict in `bimpe_tools.py`)
- Keyed by `session_id` (conversation or call ID)
- Stores: customer data, signal details, verification state, actions taken
- **Single worker only** - does not survive restarts
- For production: move to Redis for persistence and horizontal scaling

**Session Lifecycle**:
1. `POST /sessions` creates session before call is placed
2. `POST /sessions/alias` links pre-call ID to actual `call_id`
3. Tools resolve session from `session_id` parameter
4. Session persists until server restart

### Setup & Deployment

#### Prerequisites
```bash
pip install fastapi uvicorn httpx bimpeai
```

#### Environment Variables (.env)
```bash
# Bimpe AI credentials
BIMPEAI_API_KEY=sk_...
BIMPEAI_AGENT_ID=cmumd4r0x005hkt89pu3x4ekp
BIMPEAI_TOOL_TOKEN=<long random secret>
BIMPEAI_TOOLS_BASE_URL=https://your-public-host

# Bank configuration
BANK_NAME=Noba
AGENT_DISPLAY_NAME=Noba
MAX_VERIFICATION_ATTEMPTS=3

# LLM & Speech (if using custom endpoints)
API_KEY=...
LLM=https://...
ENGLISH_TTS_BASE_URL=https://...
```

#### Running the System

**1. Start the tool server** (single worker only)
```bash
uvicorn bimpe_tools:app --host 0.0.0.0 --port 8080
curl -s localhost:8080/health  # Verify token_configured=true
```

**2. Expose to internet** (for Bimpe AI to reach)
```bash
ngrok http 8080
# Set BIMPEAI_TOOLS_BASE_URL to the https URL
```

**3. Configure Bimpe AI agent**
```bash
python bimpe_setup.py --dry-run  # Preview changes
python bimpe_setup.py --tools-base-url "$BIMPEAI_TOOLS_BASE_URL"
```

**4. Place a test call**
```bash
python bimpe_caller.py FRD-CARD-FOREIGN --to "+234..."  # Test
python bimpe_caller.py FRD-CARD-FOREIGN --live          # Real call
```

### What Changed from LiveKit

The original version ran as a LiveKit worker with tools as Python methods. The Bimpe AI version:

**Kept**:
- All bank API logic (`bank_api.py`, `bank_data.py`)
- Verification system (`verification.py`)
- Three-layer security model
- Prompt engineering (`prompts.py`)

**Changed**:
- Tools moved from `@function_tool` decorators to HTTP endpoints
- Agent execution moved from local process to Bimpe AI servers
- Session state moved from agent instance to HTTP server memory
- Call initiation moved from LiveKit to `bimpeai.calls.make()`

**Lost** (platform limitations):
- Custom STT/TTS providers (Deepgram, PrepAI/Intron)
- Multi-language voice routing (Yoruba, Hausa, Igbo)
- Pre-speech credential guard (utterance interception)
- Warm transfer to human on same call
- Mid-call agent handoff (bank ↔ telecom)
- Fine-grained barge-in control

### Monitoring & Debugging

**Health check**:
```bash
curl https://your-host/health
```

**Active sessions**:
```bash
curl -H "Authorization: Bearer $BIMPEAI_TOOL_TOKEN" \
  https://your-host/debug/sessions
```

**Logs**:
Every tool call logs:
- Request body and headers
- Response status and body
- Latency (warns if >3s)
- Validation errors with specific fields

### Security Considerations

1. **Tool server must be authenticated**
   - Set `BIMPEAI_TOOL_TOKEN` to a strong secret
   - Rotate if compromised
   - Server refuses to start without it

2. **Public exposure**
   - Tool server must be internet-accessible
   - Use HTTPS in production (ngrok provides this)
   - Consider IP allowlisting for Bimpe AI

3. **Session isolation**
   - Each call gets its own session
   - Sessions cannot cross-contaminate
   - Stale sessions cleared on new calls

4. **No credential storage**
   - Security answers never sent to Bimpe AI
   - Verification happens server-side
   - Agent only receives pass/fail verdicts

---

## Benchmarks

Speech recognition and text-to-speech were measured on code-switched Nigerian
audio — word and character error rates per language for ASR, and a
synthesise-then-transcribe round trip for TTS.

Results, scored clips and methodology:
**[huggingface.co/datasets/yusasif/intron-stt_tts-benchmark](https://huggingface.co/datasets/yusasif/intron-stt_tts-benchmark)**

The raw scores are also in this repository as `benchmark_results.json` (ASR) and
`tts_results.json` (TTS).

## Demo

A recorded walkthrough of both lines is linked from the challenge submission.




