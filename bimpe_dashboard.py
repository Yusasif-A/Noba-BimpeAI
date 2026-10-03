"""
The operations screen's markup, kept out of bimpe_tools.py so the tool server
stays readable.

One inline template, no build step, no external assets: the screen has to work
behind the same tunnel as the tools with nothing extra to deploy. It polls
/api/dashboard every two seconds because the freeze the agent performs on the
phone has to appear here within a breath of being spoken -- that simultaneity is
the thing being demonstrated, and a page you have to refresh by hand does not
show it.
"""

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__BANK_NAME__ Fraud Operations</title>
<style>
  :root {
    --bg:#0b1014; --panel:#141b21; --line:#223039; --ink:#e8eef2;
    --muted:#8da2b0; --green:#2ea06a; --amber:#d9a21b; --red:#d6454a; --accent:#3d8bfd;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { padding:18px 22px; border-bottom:1px solid var(--line);
    display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .brand { font-weight:700; font-size:18px; }
  .brand span { color:var(--accent); }
  .spacer { flex:1; }
  .pill { font-size:12px; padding:4px 10px; border-radius:999px;
    border:1px solid var(--line); color:var(--muted); }
  .wrap { padding:22px; display:grid; gap:18px; max-width:1100px; margin:0 auto; }
  .grid2 { display:grid; gap:18px; grid-template-columns:1fr 1fr; }
  @media (max-width:820px) { .grid2 { grid-template-columns:1fr; } }
  .card { background:var(--panel); border:1px solid var(--line);
    border-radius:12px; padding:16px 18px; }
  h2 { margin:0 0 12px; font-size:13px; text-transform:uppercase;
    letter-spacing:.09em; color:var(--muted); font-weight:600; }
  .row { display:flex; justify-content:space-between; gap:12px; padding:6px 0; }
  .row + .row { border-top:1px solid rgba(255,255,255,.04); }
  .k { color:var(--muted); }
  .v { font-variant-numeric:tabular-nums; text-align:right; }
  .big { font-size:26px; font-weight:700; font-variant-numeric:tabular-nums; }
  .status { display:inline-flex; align-items:center; gap:7px; font-weight:600; }
  .dot { width:9px; height:9px; border-radius:50%; }
  .ok { color:var(--green); } .ok .dot { background:var(--green); }
  .warn { color:var(--amber); } .warn .dot { background:var(--amber); }
  .bad { color:var(--red); } .bad .dot { background:var(--red); }
  .pan { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.14em; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:9px 8px; border-bottom:1px solid var(--line); }
  th { font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); }
  td.amt { text-align:right; font-variant-numeric:tabular-nums; }
  tr.flagged { background:rgba(214,69,74,.09); }
  tr.flagged td:first-child { box-shadow:inset 3px 0 0 var(--red); }
  .tag { font-size:11px; padding:2px 7px; border-radius:5px;
    border:1px solid currentColor; white-space:nowrap; }
  ul.log { list-style:none; margin:0; padding:0; }
  ul.log li { padding:7px 0 7px 16px; position:relative;
    border-bottom:1px solid rgba(255,255,255,.04); }
  ul.log li::before { content:""; position:absolute; left:0; top:15px;
    width:6px; height:6px; border-radius:50%; background:var(--accent); }
  .empty { color:var(--muted); font-style:italic; }
  .sev { font-size:11px; font-weight:700; letter-spacing:.06em; }
  .flash { animation:flash 1.1s ease-out; }
  @keyframes flash { from { background:rgba(214,69,74,.42); } to { background:transparent; } }
  .pay { display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; }
  .pay label { display:flex; flex-direction:column; gap:5px; font-size:12px;
    color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
  .pay input, .pay select {
    background:#0d1317; color:var(--ink); border:1px solid var(--line);
    border-radius:7px; padding:9px 11px; font-size:15px; min-width:120px;
    font-family:inherit;
  }
  .pay button {
    background:var(--accent); color:#fff; border:0; border-radius:7px;
    padding:11px 20px; font-size:15px; font-weight:600; cursor:pointer;
  }
  .pay button:hover { filter:brightness(1.1); }
  .pay button:disabled { opacity:.55; cursor:default; }
  .pay button.ghost { background:transparent; color:var(--muted);
    border:1px solid var(--line); font-weight:500; }
  .pay button.ghost:hover { color:var(--ink); }
  .payout { margin-top:14px; font-size:14px; }
  .payout.held { color:var(--amber); }
  .payout.okd { color:var(--green); }
  .payout.err { color:var(--red); }
  .why { font-size:12px; color:var(--muted); }
</style>
</head>
<body>
<header>
  <div class="brand">__BANK_BRAND__ &middot; Fraud Operations</div>
  <div class="spacer"></div>
  <div class="pill" id="clock">&mdash;</div>
  <div class="pill" id="poll">live</div>
</header>

<div class="wrap">
  <div class="grid2">
    <div class="card">
      <h2>Cardholder</h2>
      <div class="row"><span class="k">Name</span><span class="v" id="c-name">&mdash;</span></div>
      <div class="row"><span class="k">Customer ID</span><span class="v" id="c-id">&mdash;</span></div>
      <div class="row"><span class="k">Phone</span><span class="v" id="c-phone">&mdash;</span></div>
      <div class="row"><span class="k">City</span><span class="v" id="c-city">&mdash;</span></div>
      <div class="row"><span class="k">Account</span><span class="v" id="a-no">&mdash;</span></div>
      <div class="row"><span class="k">Available balance</span><span class="v big" id="a-bal">&mdash;</span></div>
    </div>
    <div class="card">
      <h2>Card</h2>
      <div class="row"><span class="k">Number</span><span class="v pan" id="k-pan">&mdash;</span></div>
      <div class="row"><span class="k">Brand</span><span class="v" id="k-brand">&mdash;</span></div>
      <div class="row"><span class="k">Status</span><span class="v" id="k-status">&mdash;</span></div>
      <div class="row"><span class="k">Daily limit</span><span class="v" id="k-limit">&mdash;</span></div>
      <div class="row"><span class="k">Channels</span><span class="v" id="k-chan">&mdash;</span></div>
    </div>
  </div>

  <div class="card">
    <h2>Checkout</h2>
    <div class="pay">
      <label>Card ending<input id="f-last4" value="4081" maxlength="4"></label>
      <label>Amount<input id="f-amount" value="250.00"></label>
      <label>Currency
        <select id="f-currency">
          <option value="USD" selected>USD</option>
          <option value="NGN">NGN</option>
        </select>
      </label>
      <label>Merchant<input id="f-merchant" value="Kyiv Electronics"></label>
      <label>Country
        <select id="f-country">
          <option value="UA" selected>UA &mdash; Ukraine</option>
          <option value="NG">NG &mdash; Nigeria</option>
          <option value="US">US &mdash; United States</option>
        </select>
      </label>
      <label>Call this number<input id="f-dest" placeholder="leave blank for the cardholder"></label>
      <button id="f-send">Send payment</button>
      <button id="f-reset" class="ghost" title="Clear the demo back to a quiet account">Reset demo</button>
    </div>
    <div id="pay-out" class="payout"></div>
  </div>

  <div class="card">
    <h2>Pending authorisations</h2>
    <table>
      <thead><tr><th>Reference</th><th>Merchant</th><th>Amount</th><th>Status</th><th>Why</th></tr></thead>
      <tbody id="pend"><tr><td colspan="5" class="empty">Nothing held.</td></tr></tbody>
    </table>
  </div>

  <div class="card">
    <h2>Risk signal</h2>
    <div id="sig" class="empty">No signal on this account.</div>
  </div>

  <div class="card">
    <h2>Recent transactions</h2>
    <table>
      <thead><tr><th>Reference</th><th>Narration</th><th>Channel</th><th>When</th><th class="amt">Amount</th></tr></thead>
      <tbody id="trx"><tr><td colspan="5" class="empty">Loading&hellip;</td></tr></tbody>
    </table>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Agent activity</h2>
      <div id="live" class="empty">No call in progress.</div>
    </div>
    <div class="card">
      <h2>Fraud cases</h2>
      <ul class="log" id="cases"></ul>
      <div id="cases-empty" class="empty">No cases opened.</div>
    </div>
  </div>
</div>

<script>
const CUSTOMER = "__CUSTOMER_ID__";
const naira = n => "\\u20A6" + Number(n || 0).toLocaleString("en-NG", {minimumFractionDigits: 2});
const txt = (id, v) => { document.getElementById(id).textContent = (v === undefined || v === null) ? "\\u2014" : v; };
let lastCardStatus = null;

function cardStatus(s) {
  const cls = s === "ACTIVE" ? "ok" : (s === "BLOCKED" || s === "FROZEN") ? "bad" : "warn";
  const label = s === "BLOCKED" ? "FROZEN BY AGENT" : s;
  return '<span class="status ' + cls + '"><span class="dot"></span>' + label + '</span>';
}

async function tick() {
  let d;
  try {
    const r = await fetch("/api/dashboard/" + CUSTOMER, {cache: "no-store"});
    // A tunnel 504 returns an empty body, so r.json() throws "Unexpected end
    // of JSON input" and hides the real cause -- the gateway, not the bank.
    // Read as text and only parse when there is something to parse.
    const body = await r.text();
    if (!r.ok || !body) throw new Error("HTTP " + r.status);
    d = JSON.parse(body);
    failures = 0;
    document.getElementById("poll").textContent = "live";
  } catch (e) {
    // Back off instead of hammering: each retry through a struggling tunnel
    // makes the next one likelier to fail too.
    failures += 1;
    document.getElementById("poll").textContent =
      failures > 2 ? "offline \\u00B7 retrying" : "reconnecting\\u2026";
    schedule();
    return;
  }
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-NG");

  txt("c-name", d.customer.name); txt("c-id", d.customer.id);
  txt("c-phone", d.customer.phone); txt("c-city", d.customer.city);
  if (d.account) {
    txt("a-no", d.account.accountNumber);
    txt("a-bal", naira(d.account.availableBalance));
  }

  const k = (d.cards || [])[0];
  if (k) {
    txt("k-pan", k.maskedPan);
    txt("k-brand", (k.brand || "").toUpperCase());
    const el = document.getElementById("k-status");
    el.innerHTML = cardStatus(k.status);
    // Flash the moment the agent's freeze lands, so the change is not missed.
    if (lastCardStatus !== null && lastCardStatus !== k.status) {
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
    lastCardStatus = k.status;
    txt("k-limit", naira(k.dailyLimit));
    txt("k-chan", (k.channelsEnabled || []).join(" \\u00B7 "));
  }

  const s = (d.signals || [])[0];
  const sig = document.getElementById("sig");
  if (s) {
    sig.className = "";
    sig.innerHTML =
      '<div class="row"><span class="sev bad">' + s.severity + " \\u00B7 " +
      s.riskType.replace(/_/g, " ") + '</span><span class="v tag warn">' +
      s.recommendedAction.replace(/_/g, " ") + "</span></div>" +
      '<p style="margin:10px 0 0">' + s.summary + "</p>";
  } else {
    sig.className = "empty";
    sig.textContent = "No signal on this account.";
  }

  const rows = (d.transactions || []).map(function (t) {    const foreign = t.countryCode && t.countryCode !== "NG";
    const flag = foreign ? "\\uD83C\\uDDFA\\uD83C\\uDDE6 " : "\\uD83C\\uDDF3\\uD83C\\uDDEC ";
    return '<tr class="' + (t.flagged ? "flagged" : "") + '"><td>' + t.referenceId +
      "</td><td>" + flag + t.narration + "</td><td>" + t.channel + "</td><td>" +
      new Date(t.bookDate).toLocaleTimeString("en-NG") + '</td><td class="amt">' +
      (t.debitOrCredit === "DEBIT" ? "-" : "+") + naira(t.amount) + "</td></tr>";
  });
  document.getElementById("trx").innerHTML = rows.length
    ? rows.join("")
    : '<tr><td colspan="5" class="empty">No transactions.</td></tr>';

  // The live banner is rendered from polled state, never from what the click
  // returned: a payment that has since been declined or approved must stop
  // claiming it is held, and a stale "the agent is calling" line is a lie the
  // screen would otherwise tell for the rest of the session.
  const held = (d.pending || []).filter(p => p.pending);
  const out = document.getElementById("pay-out");
  if (held.length && !out.dataset.sticky) {
    const h = held[0];
    const calling = (d.live_calls || []).length
      ? "The agent is on the call with the cardholder now."
      : "Waiting for the cardholder to answer.";
    out.className = "payout held";
    out.innerHTML = "<strong>Held for verification</strong> · " + h.referenceId +
      " · " + (h.severity || "") + "<br>" + calling +
      '<div class="why">' + (h.reasons || []).join("; ") + "</div>";
  } else if (!held.length && out.className === "payout held") {
    // Nothing is in flight any more: the pending table below now tells the
    // whole story, so stop asserting anything up here.
    out.className = "payout";
    out.textContent = "";
  }

  const pend = (d.pending || []).map(function (p) {
    const cls = p.status === "DECLINED" ? "bad" : p.status === "APPROVED" ? "ok" : "warn";
    const money = p.currency === "NGN"
      ? naira(p.amount)
      : p.amount + " " + p.currency + " (" + naira(p.naira_amount) + ")";
    return '<tr class="' + (p.pending ? "flagged" : "") + '"><td>' + p.referenceId +
      "</td><td>" + p.narration + '</td><td class="amt">' + money +
      '</td><td><span class="status ' + cls + '"><span class="dot"></span>' +
      (p.stage || p.status) + '</span></td><td class="why">' +
      ((p.reasons || []).join("; ") || (p.resolution || "")) + "</td></tr>";
  });
  document.getElementById("pend").innerHTML = pend.length
    ? pend.join("")
    : '<tr><td colspan="5" class="empty">Nothing held.</td></tr>';

  const live = (d.live_calls || [])[0];
  const lv = document.getElementById("live");
  if (live) {
    lv.className = "";
    const acts = (live.actions_taken || []).map(a => "<li>" + a + "</li>").join("")
      || '<li class="empty">No actions yet.</li>';
    lv.innerHTML =
      '<div class="row"><span class="k">Identity verified</span><span class="v">' +
      (live.verified
        ? '<span class="status ok"><span class="dot"></span>YES</span>'
        : '<span class="status warn"><span class="dot"></span>NOT YET</span>') +
      "</span></div>" +
      '<div class="row"><span class="k">Attempts remaining</span><span class="v">' +
      live.attempts_remaining + "</span></div>" +
      '<div class="row"><span class="k">Handed to human</span><span class="v">' +
      (live.handed_to_human ? "YES" : "no") + "</span></div>" +
      '<ul class="log">' + acts + "</ul>";
  } else {
    lv.className = "empty";
    lv.textContent = "No call in progress.";
  }

  const cs = d.cases || [];
  document.getElementById("cases").innerHTML = cs.map(function (c) {
    return "<li><strong>" + c.caseId + "</strong> &middot; " +
      c.status.replace(/_/g, " ") + '<br><span class="k">' + c.summary + "</span></li>";
  }).join("");
  document.getElementById("cases-empty").style.display = cs.length ? "none" : "block";

  // Something in flight (a held payment or a live call) means poll fast;
  // otherwise idle slowly so the tunnel is left alone between demos.
  busy = held.length > 0 || (d.live_calls || []).length > 0;
  schedule();
}

document.getElementById("f-send").addEventListener("click", async function () {
  const btn = this;
  const out = document.getElementById("pay-out");
  btn.disabled = true;
  btn.textContent = "Authorising\u2026";
  out.className = "payout";
  out.textContent = "Asking the bank to authorise\u2026";
  try {
    const r = await fetch("/api/payments/attempt", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        card_last4: document.getElementById("f-last4").value.trim(),
        amount: document.getElementById("f-amount").value.trim(),
        currency: document.getElementById("f-currency").value,
        merchant: document.getElementById("f-merchant").value.trim(),
        country_code: document.getElementById("f-country").value,
        destination: document.getElementById("f-dest").value.trim() || null
      })
    });
    const raw = await r.text();
    if (!raw) {
      out.className = "payout err";
      out.textContent = "No reply from the bank (HTTP " + r.status +
        "). The payment may still have been held — watch the table below.";
      btn.disabled = false;
      btn.textContent = "Send payment";
      tick();
      return;
    }
    const j = JSON.parse(raw);
    if (!r.ok) {
      out.className = "payout err";
      out.textContent = "Rejected: " + (j.detail || r.status);
    } else if (j.status === "APPROVED") {
      out.className = "payout okd";
      out.textContent = "Approved \u00B7 " + j.reference + " \u2014 nothing suspicious.";
    } else if (j.status === "DECLINED") {
      out.className = "payout err";
      out.textContent = "Declined \u00B7 " + (j.reason || "");
    } else if (!j.called) {
      // Held, but nobody was rung -- say so plainly rather than claiming the
      // agent is on the phone.
      out.className = "payout err";
      out.textContent = "Held \u00B7 " + j.reference + " \u2014 but the call failed: " +
        ((j.call && (j.call.error || j.call.status)) || "unknown");
    } else {
      // Held and calling: hand over to tick(), which renders from server state.
      out.className = "payout";
      out.textContent = "";
    }
  } catch (e) {
    out.className = "payout err";
    out.textContent = "Could not reach the bank: " + e.message;
  }
  btn.disabled = false;
  btn.textContent = "Send payment";
  tick();
});

document.getElementById("f-reset").addEventListener("click", async function () {
  await fetch("/api/demo/reset", {method: "POST"});
  document.getElementById("pay-out").textContent = "";
  document.getElementById("pay-out").className = "payout";
  lastCardStatus = null;
  tick();
});

// Adaptive polling. A fixed 2s interval was ~30 requests a minute through the
// dev tunnel, which pushed it into 504s and made the screen look broken while
// the server was answering locally in under half a second. Poll briskly only
// while something is actually in flight, and back off hard on failure.
let failures = 0;
let busy = false;
let timer = null;

function schedule() {
  if (timer) clearTimeout(timer);
  const delay = failures
    ? Math.min(3000 * Math.pow(2, failures - 1), 30000)
    : (busy ? 2500 : 10000);
  timer = setTimeout(tick, delay);
}

tick();
</script>
</body>
</html>
"""
