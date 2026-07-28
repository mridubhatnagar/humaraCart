#!/usr/bin/env python3
"""
Throwaway diagnostic (NOT product code) — proves the Twilio WhatsApp transport:
inbound webhook + outbound reply + broadcast to the OTHER phone.

Flow: a phone texts the Sandbox number -> Twilio POSTs this webhook -> we reply to
the sender AND broadcast to the other configured phone. If BOTH phones see a message,
the whole transport layer is proven (webhook in, REST out, reaching a second member).

Stdlib only (no pip install). You need a public tunnel (cloudflared / ngrok) pointing
at this server's PORT, set as the Sandbox "When a message comes in" webhook (-> /webhook).

Config comes from environment variables (never hardcode secrets):
  TWILIO_ACCOUNT_SID     e.g. ACxxxxxxxx...        (Console dashboard)
  TWILIO_AUTH_TOKEN      the auth token            (Console dashboard)
  TWILIO_WHATSAPP_FROM   whatsapp:+14155238886     (your Sandbox number; verify in console)
  PHONE_A                whatsapp:+9198xxxxxxxx     (phone 1 — must have joined the sandbox)
  PHONE_B                whatsapp:+9199xxxxxxxx     (phone 2 — must have joined the sandbox)
  PORT                   8000                       (optional; the port to tunnel to)

Run:  export the vars above, then `python3 scripts/verify_twilio.py`
"""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
PHONE_A = os.environ.get("PHONE_A", "")
PHONE_B = os.environ.get("PHONE_B", "")
PORT = int(os.environ.get("PORT", "8000"))

API = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json"


def send(to, body):
    """Send one WhatsApp message via Twilio's REST API (stdlib + HTTP Basic auth)."""
    data = urllib.parse.urlencode({"From": FROM, "To": to, "Body": body}).encode()
    req = urllib.request.Request(API, data=data, method="POST")
    token = base64.b64encode(f"{ACCOUNT_SID}:{AUTH_TOKEN}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            out = json.loads(r.read().decode())
            print(f"  -> sent to {to}: sid={out.get('sid')} status={out.get('status')}")
    except urllib.error.HTTPError as e:
        print(f"  x send to {to} FAILED {e.code}: {e.read().decode()[:300]}")


def other(sender):
    """The other household phone, for the broadcast."""
    if sender == PHONE_A:
        return PHONE_B
    if sender == PHONE_B:
        return PHONE_A
    return None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        sender = params.get("From", "")
        text = params.get("Body", "")
        print(f"\nINBOUND from {sender}: {text!r}")

        # 1. Reply to the sender (proves outbound reply).
        send(sender, f"HumaraCart test: got your '{text}' ✓")

        # 2. Broadcast to the other phone (proves reaching the OTHER member).
        peer = other(sender)
        if peer:
            who = sender.split(":")[-1]
            send(peer, f"[broadcast] {who} said: {text}")
        else:
            print(f"  (sender {sender} is not PHONE_A/PHONE_B — no broadcast target)")

        # Ack Twilio (we already sent via REST, so an empty TwiML 200 is enough).
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.end_headers()
        self.wfile.write(b"<Response></Response>")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"verify_twilio is up. Twilio POSTs to this URL as the webhook.")

    def log_message(self, *_):
        pass


def main():
    missing = [
        name
        for name, val in [
            ("TWILIO_ACCOUNT_SID", ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", AUTH_TOKEN),
            ("PHONE_A", PHONE_A),
            ("PHONE_B", PHONE_B),
        ]
        if not val
    ]
    if missing:
        print("Missing env vars:", ", ".join(missing))
        print("Set them (see this file's header), then re-run.")
        return
    print(f"Listening on :{PORT}")
    print("Point your tunnel here, set Sandbox webhook -> <tunnel-url>/webhook, then text 'Hi'.")
    print(f"FROM={FROM}  PHONE_A={PHONE_A}  PHONE_B={PHONE_B}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
