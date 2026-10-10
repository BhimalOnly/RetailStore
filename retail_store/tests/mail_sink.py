"""Dev-only SMTP sink: accepts every message on 127.0.0.1:1025 and writes it to $MAIL_OUT/<ms>.eml.

browser_shopper.py reads the signup email from here (Frappe redacts password links in Email Queue).
Point a default-outgoing Email Account at SMTP 127.0.0.1:1025 (no TLS, no auth), then:
    python -m venv /tmp/mailvenv && /tmp/mailvenv/bin/pip install aiosmtpd
    mkdir -p /tmp/retail_mail && MAIL_OUT=/tmp/retail_mail /tmp/mailvenv/bin/python mail_sink.py
Never use on a real site: it swallows all outgoing mail.
"""
import os
import threading
import time

from aiosmtpd.controller import Controller

OUT = os.environ.get("MAIL_OUT", "/tmp/retail_mail")
os.makedirs(OUT, exist_ok=True)


class Sink:
	async def handle_DATA(self, server, session, envelope):
		with open(f"{OUT}/{int(time.time() * 1000)}.eml", "wb") as f:
			f.write(envelope.content)
		return "250 OK"


Controller(Sink(), hostname="127.0.0.1", port=1025).start()
print("mail sink on 127.0.0.1:1025 ->", OUT, flush=True)
threading.Event().wait()
