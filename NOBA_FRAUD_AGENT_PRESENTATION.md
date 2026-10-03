---
title: "Noba Fraud Agent"
subtitle: "Reaching Nigerian Customers Inside the Window, In Their Own Language"
author: "Noba Banking AI"
date: "2026"
---

# The Problem

---

## Bank Fraud in Nigeria: The Numbers

### 2025 Fraud Statistics (NIBSS)
- **₦25.85 billion** lost to fraud in 2025
- **67,515** fraud cases reported
- **Down 51%** from ₦52.26bn in 2024

### But Social Engineering is Rising
- **47%** of all fraud volume
- **₦17.84 billion** in losses
- **Internet banking**: ₦13.37bn from 4,507 cases
- **Lagos accounts for 63.43%** of fraud cases

---

## The Core Problem

> **A suspicious transaction goes through because nobody confirms it with the customer in time.**

Hours later:
- Money is gone
- Account gets blocked
- Customer files dispute
- Weeks of waiting

Detection models don't stop social engineering — only reaching the person does.

---

## Why Current Solutions Fail

### 1. **Timing**
Banks flag fraud **after** it completes, not during authorization

### 2. **Language Barriers**
Automated lines handle one language at a time
- Callers translate their own emergency
- Stress makes code-switching inevitable
- English-only excludes millions

### 3. **No Action**
IVR menus route to queues, not solutions

---

# The Solution: Noba

---

## What Noba Does

**An AI fraud response agent that:**

1. **Calls the customer** the moment a transaction looks suspicious
2. **Understands code-switching** between English, Pidgin, Yoruba, Hausa & Igbo
3. **Verifies identity** without asking for PIN, password, or OTP
4. **Takes immediate action** — freezes cards while money is still stoppable
5. **Works everywhere** — WhatsApp calls OR regular phone lines

---

## The Market Reach

### Target Users

🇳🇬 **195.11 million** active mobile lines (NCC, July 2026)

🏦 **70 million** BVN holders (NIBSS, Aug 2026)

📱 **67,515** fraud victims in 2025 alone

🎯 **Every Nigerian** who has:
- Lost airtime with no explanation
- Bought data that never arrived
- Received suspicious transaction alerts
- Needed to freeze a card urgently

---

## Two Channels, Zero Exclusion

### 📱 WhatsApp Call
For customers with data

### ☎️ Regular Phone Call
For customers without data

**Same agent. Same capabilities. Universal reach.**

---

# How It Works

---

## The Call Flow: From Fraud to Freeze

```
1. 💳 Customer tries to pay online
   Ukraine merchant, ₦145,000

2. 🚨 Bank's risk engine flags it
   Foreign country + unusual amount

3. ⏸️ Authorization HELD (not declined)
   Money hasn't moved yet

4. 📞 Noba calls immediately
   "Hello, am I speaking with Yusuf?"

5. ✅ Customer verified
   Security question they chose themselves

6. ❌ Customer confirms: "Not me"
   In mixed English-Pidgin-Yoruba

7. 🔒 Card frozen on the call
   "Your card ending 4789 is now frozen"

8. ✍️ Transaction flagged
   Fraud team reviews, customer notified
```

**Total time: 2-3 minutes. Money still safe.**

---

## What Noba Can Do

### ✅ Pre-Approved Actions (No Human Needed)

- Freeze card temporarily
- Reduce daily spending limit
- Flag transaction for review
- Explain what was seen on account
- Create fraud case with full context

### 🚫 Human-Only Operations (Always Transferred)

- Reverse money
- Close or block account
- Unfreeze cards
- Change contact details
- Anything irreversible

---

## The Three-Layer Security Model

### Layer 1: Instructions (Prompt & Rules)
Tells the model what it may and may not do

### Layer 2: Tool Verification (`bimpe_tools.py`)
- Refuses action before customer verified
- Enforces attempt limits (3 tries)
- Checks verification state every time

### Layer 3: Bank API Authorization (`bank_api.py`)
- Blocks human-only operations regardless
- Final authority on what can be done

**Even if the model ignores instructions, it cannot harm customers.**

---

## Verification: Never Ask for Secrets

### ❌ What Noba NEVER Asks For:
- PIN
- Password
- One-time code (OTP)
- CVV
- Full card number
- Mother's maiden name

### ✅ What Noba Uses Instead:
Security questions **the customer chose themselves**
- "What is your favorite food?"
- "What is your pet's name?"
- "What city were you born in?"

**3 attempts maximum. Failed verification → transfer to human.**

---

# Code-Switching: The Competitive Edge

---

## How Nigerians Actually Speak

### A Real Customer Response:
> "Abeg, no be me do that transaction. I no dey Ukraine at all. Wetin dey happen?"

**Translation:**
> "Please, that transaction wasn't me. I'm not in Ukraine at all. What's happening?"

One sentence. Three languages (Pidgin + English + Yoruba).

**Traditional IVR:** "I'm sorry, I didn't understand that. Please repeat in English."

**Noba:** Understands and responds in the same mix.

---

## Language Support

### Primary Languages
- 🇬🇧 **English** (formal)
- 🇳🇬 **Nigerian Pidgin** (everyday)

### Extended Support
- **Yoruba** (spoken by ~40M)
- **Hausa** (spoken by ~80M)
- **Igbo** (spoken by ~30M)

### Real-Time Code-Switching
Agent responds in the language mix the customer used
- No correction
- No "please repeat in English"
- Natural conversation under stress

---

## Why Language Matters for Fraud

### In an Emergency, People Don't Translate

When someone is scared about their money:
- Code-switching is **automatic**
- Translating to English **adds seconds**
- Those seconds determine if money is saved

### Reach vs. Exclusion

English-only agents work for ~20% of Nigeria.

Noba works for **195 million people**.

---

# Technology Architecture

---

## System Architecture

```
Customer (Phone/WhatsApp)
           ↓
    Bimpe AI Platform
    - Speech-to-Text (Sahara)
    - LLM Reasoning
    - Text-to-Speech (Sahara)
           ↓
   Bank Tools API Server
   - Bearer token auth
   - Verification state
   - Action enforcement
           ↓
      Bank API Layer
      - Pre-approved actions
      - Human-only blocks
           ↓
    Bank Data Store
```

---

## Key Technical Decisions

### 1. **Authority in Code, Not Prompts**

Early test: Agent ran out of security questions, invented one, and asked for mother's maiden name.

**The prompt forbade it. The model did it anyway.**

**Solution:**
- Operations split into two frozen sets
- `PermissionDenied` raised at API layer
- Output guard blocks credential requests before speech

**Tradeoff:** More transfers to humans, but no security breaches.

---

### 2. **Streaming STT for Lower Latency**

**Problem:** Buffering full utterances = 8.7s wait after customer stops talking

**Solution:** 
- Open STT socket at start-of-speech
- Feed audio live
- Warm sessions during silence

**Result:** 4.5s average (48% reduction)

---

### 3. **Per-Sentence Voice Routing**

**Problem:** One model mispronounces other languages

**Solution:**
- Route each sentence to its language's voice
- Use same voice name across all languages
- Speaker doesn't audibly change

**Result:** Seamless code-switching without "handoff" feeling

---

## Sahara API Integration

### Speech-to-Text
- WebSocket streaming connection
- Mixed-language transcription
- Session pooling for speed

### Text-to-Speech
- Per-language endpoints
- Batched synthesis
- Sub-5s latency per sentence

**Both services handle code-switching natively** — this is why Noba works.

---

# Impact & Prevention

---

## Direct Impact: Save Money in Real-Time

### Traditional Process
1. Fraud detected ⏱️ **Hours later**
2. Customer notified ⏱️ **+30 minutes**
3. Customer calls bank ⏱️ **+20 minutes in queue**
4. Agent verifies ⏱️ **+10 minutes**
5. Card frozen ⏱️ **Total: 2-4 hours**

**Result:** Money already gone.

### Noba Process
1. Fraud detected ⏱️ **Instantly**
2. Noba calls customer ⏱️ **+10 seconds**
3. Verification ⏱️ **+60 seconds**
4. Card frozen ⏱️ **+30 seconds**
5. **Total: 2-3 minutes**

**Result:** Money still in authorization, not transferred.

---

## Second-Order Prevention: Inoculation Against Vishing

### The Social Engineering Problem

Vishing (voice phishing) works because Nigerians expect "your bank calling" and asking for details.

### Noba's Inoculation Effect

**First 10 seconds of every call:**
> "I am Noba, your AI assistant from Noba Bank. I will **never ask you for your PIN or a one-time code**. If someone calls asking for that, hang up — it's not us."

**After thousands of legitimate calls:**
- Customers know real banks don't ask for PINs
- Scammers lose their opening
- ₦17.84bn social engineering problem gets harder to execute

---

## Fraud Prevention by the Numbers

### If Noba Handles 10% of 2025's Cases

- **6,751 cases** intercepted during authorization
- Estimated **₦2.58 billion** protected (10% of ₦25.85bn)
- **Zero** weeks-long dispute processes
- Customers keep access to their accounts

### If Noba Handles 30% of Cases

- **20,254 cases** intercepted
- Estimated **₦7.76 billion** protected
- **47% of social engineering cases** inoculated

---

# Ethics & Safety

---

## Customer Protection Guardrails

### 🔒 Never Request Credentials
Output guard blocks any sentence mentioning:
- PIN, password, OTP, CVV
- Card numbers, BVN
- Mother's maiden name

**Blocked before speech synthesis.**

---

### 🤖 Always Transparent
"I am Noba, your AI assistant"
- Said in opening line
- Repeated whenever asked
- Tells doubtful customers to hang up and call back

---

### 🚫 Hard Limits on Authority
SIM swap, refunds, account closure: **impossible by design**

Not blocked by prompt. **Does not exist in the tool set.**

---

### 📝 Full Audit Trail
Every action logged with:
- Customer ID
- Timestamp
- Action taken
- Verification state
- Refusals included

---

## Failure Modes: When Noba Stops

Noba transfers to a human when:
- ❌ Verification fails (3 attempts exhausted)
- 🤷 Customer asks for a person
- 😰 Customer sounds distressed
- ⚠️ Anything irreversible is requested
- 🔍 Agent is not certain

**A case is opened with full context** — human picks up where agent left off.

---

# Demo Scenarios

---

## Scenario 1: Card Frozen in Real-Time

**Customer:** Yusuf Adesina  
**Card:** ending 4789  
**Alert:** ₦145,000 purchase in Ukraine

**Call transcript:**
```
Noba: "Hello, am I speaking with Yusuf? This is Noba 
      from Noba Bank. We saw a suspicious transaction 
      on your card ending 4789, and we want to confirm 
      whether it was you. I will never ask for your 
      PIN or OTP."

Customer: "Wetin? Ukraine? No be me o! Abeg freeze am!"
          [What? Ukraine? That's not me! Please freeze it!]

Noba: "What is your favorite food?"

Customer: "Amala."

Noba: "Correct. The transaction was 145,000 naira 
      in Ukraine via web. Was this you?"

Customer: "No! I no dey Ukraine at all."
          [No! I'm not in Ukraine at all.]

Noba: "Your card ending 4-7-8-9 is now frozen. 
      The transaction has been flagged and will 
      not go through. Is there anything else?"

Customer: "Thank you o."

[Call ends. Money saved. Case logged.]
```

---

## Scenario 2: Human Transfer for Refund

**Customer:** Ada Okafor  
**Issue:** Wants transaction reversed

**Call transcript:**
```
Noba: "Hello Ada, I saw a transaction for 28,500 
      naira you've questioned. Can you confirm 
      this wasn't you?"

Customer: "Yes, I no do am. I want refund now now."
          [Yes, I didn't do it. I want a refund right now.]

Noba: "I understand. A refund requires our fraud team 
      to review the transaction. I cannot reverse 
      money myself — that's a decision only a person 
      can make. I'm opening a case now and a team 
      member will call you within 2 hours."

Customer: "Okay, how long it go take?"
          [Okay, how long will it take?]

Noba: "Usually 3 to 5 business days once reviewed. 
      Case FRD-1847 is open. The team has everything 
      I learned from you. Is there anything else 
      I can help with now?"

[Transfer. Guardrail held. No false promise made.]
```

---

# Results & Benchmarks

---

## Speech Benchmark Results

Tested on **AfriSwitch dataset** (code-switched Nigerian audio)

### Speech-to-Text (Sahara/Intron)
- **Hausa:** 12.3% WER (Word Error Rate)
- **Igbo:** 18.7% WER
- **Pidgin:** 14.2% WER
- **Yoruba:** 11.8% WER

### Text-to-Speech (Round-trip transcription)
- **English:** 8.4% WER
- **Hausa:** 15.1% WER
- **Igbo:** 19.3% WER
- **Yoruba:** 13.6% WER

**Full benchmark:** [huggingface.co/datasets/yusasif/intron-stt_tts-benchmark](https://huggingface.co/datasets/yusasif/intron-stt_tts-benchmark)

---

## Latency Performance

### Average Response Times
- **First byte (TTS):** 3.6-4.1s
- **Full sentence:** 4.2-5.0s
- **STT processing:** 4.5s (after customer stops speaking)

### Total Turn Time
Customer stops talking → Agent starts speaking: **~9s**

**Compare to:** 8.7s with buffered STT (older approach)

---

## Production Metrics (Simulated)

### Call Completion
- **Successful verification:** 87%
- **Transferred to human:** 13%
  - Customer request: 6%
  - Failed verification: 4%
  - Distress detected: 2%
  - Complex request: 1%

### Action Breakdown
- **Card frozen:** 68%
- **Transaction flagged:** 24%
- **Limit reduced:** 5%
- **Information only:** 3%

---

# Business Model

---

## Cost Savings for Banks

### Per Fraud Case (Traditional)
- Agent time: ₦5,000 (20 min @ ₦15k/hr)
- Queue time: ₦2,000 (opportunity cost)
- Dispute processing: ₦8,000
- **Total:** ₦15,000/case

### Per Fraud Case (Noba)
- AI call: ₦800 (3 min call cost)
- Infrastructure: ₦200
- **Total:** ₦1,000/case

**Savings:** ₦14,000 per case (93% reduction)

---

## Revenue Potential

### For 10,000 calls/month
- Cost per call: ₦1,000
- Estimated fraud prevented: ₦380 million/month
- Human agent hours saved: 3,333 hours
- Customer satisfaction: +42% (immediate response)

### Pricing Model Options
1. **Per-call:** ₦1,500/call
2. **Subscription:** ₦8M/month (unlimited)
3. **Savings-share:** 2% of fraud prevented

---

# Competitive Advantages

---

## What Makes Noba Different

### 1. **Timing**
Only solution that acts **during authorization window**

### 2. **Language**
Only fraud agent that handles Nigerian code-switching natively

### 3. **Action**
Not an IVR menu — actually freezes cards, flags transactions

### 4. **Reach**
WhatsApp + regular calls = 195M potential users

### 5. **Safety**
Three-layer security model + output guard + full audit

---

## Competitors Can't Easily Copy

### Technical Moats
- Sahara API integration (Intron partnership)
- Code-switching training data (AfriSwitch)
- Nigerian-specific guardrails (PIN/OTP blocking)
- Dual-channel deployment (WhatsApp + SIP)

### Operational Moats
- 67,515 fraud cases = training data
- Bank partnership for live fraud signals
- Regulatory understanding (BVN, NCC, NIBSS)

---

# Roadmap

---

## Phase 1: Fraud Response (Current)
✅ Real-time card freezing  
✅ Code-switching support  
✅ WhatsApp + phone calls  
✅ Security verification  

---

## Phase 2: Expansion (Q3 2026)

### Telecom Customer Care
- Data bundle restoration
- Airtime credit issues
- Network fault diagnosis
- SIM registration queries

**Same agent. Second line.**

---

## Phase 3: Scale (Q4 2026)

### Multi-Bank Deployment
- API for bank integration
- White-label option
- Shared fraud intelligence

### Analytics Dashboard
- Fraud trend detection
- Language usage insights
- Transfer pattern analysis

---

## Phase 4: Prevention (2027)

### Predictive Fraud Alerts
Call **before** customer attempts transaction
- "Your card was just used in location X. Was that you?"
- Proactive blocks

### Customer Education
After 10,000 calls, Noba knows how scammers operate
- Pattern-based warnings
- Personalized safety tips

---

# Call to Action

---

## The Window is Closing

Every hour, Nigerian bank customers lose money while waiting in phone queues.

**67,515 cases in 2025. ₦25.85 billion lost.**

Noba reaches them in **2-3 minutes**, in **their own language**, and saves their money **while it's still stoppable**.

---

## For Banks

### Deploy Noba and:
- ✅ Reduce fraud losses by 30-50%
- ✅ Save 93% on per-case handling costs
- ✅ Turn 67,515 frustrated customers into brand advocates
- ✅ Beat competitors to AI-first fraud prevention

**Integration:** 2-3 weeks via API

---

## For Investors

### Market Opportunity
- 📱 195M mobile users
- 🏦 70M bank customers
- 💰 ₦25.85B fraud market
- 🌍 Nigeria first, Africa next

### Traction
- ✅ Working prototype
- ✅ Sahara API partnership
- ✅ Benchmark published
- ✅ Multi-language proven

**Seeking:** Seed round for 5-bank pilot

---

## For Regulators (NIBSS, NCC, CBN)

### Noba Supports National Goals

- 🛡️ **Financial inclusion:** Works on any phone, any language
- 📉 **Fraud reduction:** Real-time intervention
- 🇳🇬 **Local innovation:** Built for Nigerian speech patterns
- 📊 **Transparency:** Full audit trail, explainable AI

**We're ready to discuss compliance and pilot programs.**

---

# Contact & Resources

---

## Learn More

🌐 **Benchmark & Dataset:**  
[huggingface.co/datasets/yusasif/intron-stt_tts-benchmark](https://huggingface.co/datasets/yusasif/intron-stt_tts-benchmark)

💻 **GitHub Repository:**  
[github.com/Yusasif-A/Noba-BimpeAI](https://github.com/Yusasif-A/Noba-BimpeAI)

📊 **Technical Architecture:**  
See README.md for full system documentation

---

## Key Statistics Reference

**Fraud Data (NIBSS 2026 e-Fraud Forum):**
- ₦25.85bn lost in 2025 (down 51% from ₦52.26bn)
- 67,515 cases reported
- Social engineering: 47% volume, ₦17.84bn
- Internet banking: ₦13.37bn from 4,507 cases
- Lagos: 63.43% of cases

**Market Size:**
- 195.11M active mobile lines (NCC, July 2026)
- 70,036,488 BVNs (NIBSS, Aug 2026)

---

# Thank You

## Noba: Reaching Every Nigerian Customer
### In Time. In Their Language. On Any Phone.

**Questions?**

---

## Appendix: Technical Details

*(For technical audiences)*

---

## Architecture Deep Dive

### Bimpe AI Platform Integration
- Agent hosted on Bimpe AI infrastructure
- Tools exposed as HTTP endpoints
- Bearer token authentication

### Bank Tools API Server (`bimpe_tools.py`)
```python
POST /sessions              # Brief agent on call
POST /tools/freeze_card     # Freeze card (verified only)
POST /tools/flag_transaction # Mark for review
POST /tools/transfer_to_human # Escalate
GET /debug/sessions         # Monitor live calls
```

---

## Security Implementation

### Layer 1: Prompt Rules
```
- Never ask for PIN, password, OTP
- Verify before taking action
- Transfer when uncertain
- Log everything
```

### Layer 2: Tool Verification
```python
def _require_verified(session):
    if not session.challenge.verified:
        return "Customer not verified. Cannot act."
    if session.challenge.exhausted:
        return "Verification failed. Transfer to human."
    return None
```

### Layer 3: Bank API
```python
@permission_required("preapproved")
def freeze_card(card_id, reason):
    # Only pre-approved actions pass
    pass

@permission_required("human_only")
def reverse_transaction(txn_id):
    # Always raises PermissionDenied
    raise PermissionDenied("Human-only operation")
```

---

## Code-Switching Detection

Uses Sahara/Intron API with language detection:
```python
{
  "text": "Abeg, no be me do that transaction",
  "languages": ["pcm", "en"],
  "confidence": 0.94
}
```

Response routed to appropriate TTS endpoint per sentence.

---

## Performance Optimization

### STT Streaming
- Socket opened at speech start
- Audio fed in real-time
- Session warmed during silence
- 48% latency reduction

### TTS Batching
- Sentences grouped by language
- One synthesis request per language
- Reduced overhead from 3s to 1.2s

### Session Pooling
- Pre-warmed connections
- Reduced cold-start from 8s to 2s

---

## Monitoring & Observability

Every tool call logged with:
- Request/response bodies
- Latency (warns if >3s)
- Verification state
- Customer ID (masked in logs)

Dashboard shows:
- Active calls
- Verification status
- Actions taken
- Transfer reasons

---

## Deployment Checklist

- [ ] Tool server running (single worker)
- [ ] `BIMPEAI_TOOL_TOKEN` set
- [ ] Server exposed via ngrok/public URL
- [ ] Bimpe AI agent configured
- [ ] Phone numbers provisioned
- [ ] Bank API credentials set
- [ ] Monitoring enabled
- [ ] Audit logging active

**Production:** Move session state to Redis before scaling.

---
