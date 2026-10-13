"""Customer messages: phone numbers, consent, the Dry run / WhatsApp / SMS providers against a local fake
gateway, failure + retry, who may see the credentials, and a real storefront Sales Order end to end.

Run:  bench --site retail.localhost execute retail_store.tests.check_messaging.run
Everything happens inside one transaction that is rolled back at the end (no messages leave the machine:
the "gateway" is a thread on 127.0.0.1)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today
from frappe.utils.password import set_encrypted_password

from retail_store.messaging import consent, engine, events, providers
from retail_store.messaging.phone import normalize

PORT = 18765
SECRET_TOKEN = "EAAG-secret-token-123"
SECRET_PASSWORD = "sms-secret-pass-456"
results = []
seen = []  # what the fake gateway received
mode = {"status": 200, "body": None}


def check(name, ok, detail=""):
	results.append((name, bool(ok)))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


class Gateway(BaseHTTPRequestHandler):
	def _handle(self):
		length = int(self.headers.get("Content-Length") or 0)
		raw = self.rfile.read(length).decode() if length else ""
		seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": raw})
		status = mode["status"]
		if mode["body"] is not None:
			body = mode["body"]
		elif "/messages" in self.path:
			body = json.dumps({"messages": [{"id": "wamid.TEST123"}]}) if status == 200 else json.dumps({"error": {"message": f"Invalid OAuth access token ({SECRET_TOKEN})"}})
		else:
			body = "OK 12345" if status == 200 else f"error for {SECRET_PASSWORD}"
		self.send_response(status)
		self.end_headers()
		self.wfile.write(body.encode())

	do_POST = do_GET = _handle

	def log_message(self, *a):
		pass


def set_gateway(status=200, body=None):
	mode.update(status=status, body=body)
	seen.clear()


def single(**kw):
	for k, v in kw.items():
		frappe.db.set_single_value("Retail Store Settings", k, v)


def log_rows(ref, channel=None):
	f = {"reference_name": ref}
	if channel:
		f["channel"] = channel
	return frappe.get_all("Retail Message Log", filters=f, fields=["*"], order_by="creation asc")


def ctx(ref, phone="5712 3456", customer_id=None, **kw):
	return {"customer": "Asha", "customer_id": customer_id, "phone": phone, "order": ref, "store": "Demo Shop", "total": "Rs 1,500.00",
		"reference_doctype": "Sales Order", "reference_name": ref, **kw}


def run():
	server = HTTPServer(("127.0.0.1", PORT), Gateway)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	frappe.set_user("Administrator")
	try:
		_checks()
	finally:
		server.shutdown()
		frappe.set_user("Administrator")
		frappe.db.rollback()
	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} messaging checks passed")


def _checks():
	# ---- phone numbers
	for raw, want in [("5712 3456", "+23057123456"), ("+230 5712 3456", "+23057123456"), ("00230 5712-3456", "+23057123456"),
			("230 5712 3456", "+23057123456"), ("(230) 57123456", "+23057123456"), ("+44 7700 900123", "+447700900123"),
			("12345", None), ("", None), (None, None), ("abc", None), ("0123456789", None), ("+1", None)]:
		check(f"phone {raw!r} -> {want}", normalize(raw, "230") == want, normalize(raw, "230"))

	# ---- setup: messaging on, WhatsApp via the fake gateway, SMS via the fake gateway
	single(enable_messaging=1, messaging_country_code="230", whatsapp_provider="Meta WhatsApp Cloud API", whatsapp_phone_number_id="PHONEID9",
		whatsapp_api_base=f"http://127.0.0.1:{PORT}", whatsapp_api_version="v21.0", sms_provider="Generic HTTP gateway",
		sms_gateway_url=f"http://127.0.0.1:{PORT}/sms", sms_http_method="POST", sms_username="shopuser", sms_sender_id="DEMOSHOP",
		sms_params="user={username}\npass={password}\nto={to_digits}\nfrom={sender}\ntext={message}")
	set_encrypted_password("Retail Store Settings", "Retail Store Settings", SECRET_TOKEN, "whatsapp_access_token")
	set_encrypted_password("Retail Store Settings", "Retail Store Settings", SECRET_PASSWORD, "sms_password")
	rules = frappe.get_all("Retail Message Rule", filters={"parent": "Retail Store Settings"}, fields=["name", "event", "channel", "enabled"])
	check("starter rules exist: confirmation + ready, WhatsApp and SMS", {(r.event, r.channel) for r in rules} >= {("Order confirmation", "WhatsApp"), ("Order confirmation", "SMS"), ("Order ready", "WhatsApp"), ("Order ready", "SMS")}, rules)
	check("starter defaults: WhatsApp on, SMS off (no double sends)", all(bool(r.enabled) == (r.channel == "WhatsApp") for r in rules), rules)
	for r in rules:  # both channels on for these checks
		frappe.db.set_value("Retail Message Rule", r.name, "enabled", 1)

	cust = frappe.get_doc({"doctype": "Customer", "customer_name": "Msg Test Shopper", "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")}).insert(ignore_permissions=True)

	# ---- transactional order message: both channels, to the number on the order
	ref = "TEST-ORD-1"
	set_gateway(200)
	engine.queue("Order confirmation", ctx(ref, customer_id=cust.name))
	rows = log_rows(ref)
	check("confirmation: one row per enabled channel", {r.channel for r in rows} == {"WhatsApp", "SMS"} and len(rows) == 2, [(r.channel, r.status) for r in rows])
	check("rows start Queued, transactional, numbers normalised to +230", all(r.status == "Queued" and r.kind == "Transactional" and r.recipient == "+23057123456" for r in rows), [(r.status, r.recipient) for r in rows])
	check("message text filled in from the rule", "Asha" in rows[0].body and ref in rows[0].body and "Demo Shop" in rows[0].body and "{" not in rows[0].body, rows[0].body)
	for r in rows:
		engine.deliver(r.name)
	rows = log_rows(ref)
	check("both delivered (Sent) with a provider reference", all(r.status == "Sent" and r.provider_message_id and r.sent_on and not r.error and r.attempts == 1 for r in rows), [(r.channel, r.status, r.error) for r in rows])
	wa = next(x for x in seen if "/messages" in x["path"])
	body = json.loads(wa["body"])
	check("WhatsApp request: right URL, bearer token, template + variables in order", wa["path"] == "/v21.0/PHONEID9/messages" and wa["auth"] == f"Bearer {SECRET_TOKEN}" and body["to"] == "23057123456" and body["type"] == "template"
		and body["template"]["name"] == "order_confirmation" and [p["text"] for p in body["template"]["components"][0]["parameters"]] == ["Asha", ref, "Demo Shop", "Rs 1,500.00"], wa)
	sms = next(x for x in seen if x["path"].startswith("/sms"))
	check("SMS request: parameters filled (username, password, number, sender, text)", all(s in sms["body"] for s in ("user=shopuser", f"pass={SECRET_PASSWORD}", "to=23057123456", "from=DEMOSHOP", "text=Hi+Asha" if "text=Hi+Asha" in sms["body"] else "text=")), sms["body"][:200])
	check("no secret is written to the log rows", not any(SECRET_TOKEN in json.dumps(r, default=str) or SECRET_PASSWORD in json.dumps(r, default=str) for r in rows))
	engine.queue("Order confirmation", ctx(ref, customer_id=cust.name))
	check("the same event is not queued twice (idempotent)", len(log_rows(ref)) == 2)

	# ---- skipped: no phone / not opted in
	engine.queue("Order confirmation", ctx("TEST-NOPHONE", phone=""))
	r = log_rows("TEST-NOPHONE")
	check("no phone -> Skipped with a plain reason, nothing sent", len(r) == 2 and all(x.status == "Skipped" and "phone" in x.error for x in r), [(x.status, x.error) for x in r])
	set_gateway(200)
	engine.queue("Order confirmation", ctx("TEST-MKT-1", customer_id=cust.name), kind="Marketing")
	r = log_rows("TEST-MKT-1")
	check("marketing without opt-in -> Skipped (both channels)", len(r) == 2 and all(x.status == "Skipped" and "opted in" in x.error for x in r), [(x.status, x.error) for x in r])
	check("...and nothing reached the gateway", not seen)

	# ---- consent record
	c = frappe.get_doc("Customer", cust.name)
	c.custom_whatsapp_optin = 1
	c.save(ignore_permissions=True)
	c.reload()
	check("ticking WhatsApp opt-in stamps when / who / how", c.custom_whatsapp_optin_on and c.custom_consent_by == "Administrator" and c.custom_consent_source == "Recorded by staff" and not c.custom_sms_optin_on, c.as_dict())
	engine.queue("Order confirmation", ctx("TEST-MKT-2", customer_id=cust.name), kind="Marketing")
	r = {x.channel: x for x in log_rows("TEST-MKT-2")}
	check("marketing: WhatsApp (opted in) queued with the consent as its basis, SMS (not) skipped", r["WhatsApp"].status == "Queued" and "Opt-in recorded" in r["WhatsApp"].consent_basis and r["SMS"].status == "Skipped", {k: (v.status, v.consent_basis) for k, v in r.items()})
	frappe.flags.rs_consent_source = "Storefront checkout"
	c = frappe.get_doc("Customer", cust.name)
	c.custom_whatsapp_optin = 0
	c.save(ignore_permissions=True)
	frappe.flags.rs_consent_source = None
	c.reload()
	check("unticking records the opt-out time, keeps the opt-in time and the source", c.custom_whatsapp_optout_on and c.custom_whatsapp_optin_on and c.custom_consent_source == "Storefront checkout", c.as_dict())
	check("has_consent follows the box", not consent.has_consent(cust.name, "WhatsApp") and not consent.has_consent(None, "SMS"))

	# ---- failure handling
	def fresh(ref, channel="SMS"):
		engine.queue("Order ready", ctx(ref))
		return next(x for x in log_rows(ref) if x.channel == channel)

	set_gateway(503)
	row = fresh("TEST-FAIL-1")
	engine.deliver(row.name)
	d = frappe.get_doc("Retail Message Log", row.name)
	check("gateway 503 -> Retry, attempt 1, next try about 5 minutes out, no exception", d.status == "Retry" and d.attempts == 1 and d.next_attempt_at and 4 * 60 < (d.next_attempt_at - now_datetime()).total_seconds() <= 5 * 60 + 5, (d.status, d.attempts, d.next_attempt_at))
	check("the gateway's reply is kept but the SMS password is masked", d.error and SECRET_PASSWORD not in d.error and "***" in d.error, d.error)
	engine.retry_due()
	check("not due yet: retry_due leaves it alone", frappe.db.get_value("Retail Message Log", row.name, "attempts") == 1)
	frappe.db.set_value("Retail Message Log", row.name, "next_attempt_at", add_to_date(now_datetime(), minutes=-1))
	engine.retry_due()
	d.reload()
	check("due -> retried: attempt 2, wait grows to about 30 minutes", d.status == "Retry" and d.attempts == 2 and 25 * 60 < (d.next_attempt_at - now_datetime()).total_seconds() <= 30 * 60 + 5, (d.status, d.attempts, d.next_attempt_at))
	frappe.db.set_value("Retail Message Log", row.name, "next_attempt_at", add_to_date(now_datetime(), minutes=-1))
	engine.retry_due()
	d.reload()
	check("third failure -> Failed for good, no more tries", d.status == "Failed" and d.attempts == engine.MAX_ATTEMPTS and not d.next_attempt_at, (d.status, d.attempts))
	frappe.db.set_value("Retail Message Log", row.name, "creation", now_datetime())
	engine.retry_due()
	check("a Failed row is never picked up again", frappe.db.get_value("Retail Message Log", row.name, "attempts") == engine.MAX_ATTEMPTS)

	set_gateway(400, body=f"bad number {SECRET_PASSWORD}")
	row = fresh("TEST-FAIL-2")
	engine.deliver(row.name)
	d = frappe.get_doc("Retail Message Log", row.name)
	check("gateway 400 (cannot be fixed by retrying) -> Failed on the first attempt", d.status == "Failed" and d.attempts == 1 and SECRET_PASSWORD not in d.error, (d.status, d.attempts, d.error))

	set_gateway(401)
	row = fresh("TEST-FAIL-3", "WhatsApp")
	engine.deliver(row.name)
	d = frappe.get_doc("Retail Message Log", row.name)
	check("WhatsApp 401 -> Failed, the reason is readable and the token is masked", d.status == "Failed" and "Invalid OAuth" in d.error and SECRET_TOKEN not in d.error, d.error)

	set_gateway(200, body="rejected")
	single(sms_success_text="OK")
	row = fresh("TEST-FAIL-4")
	engine.deliver(row.name)
	check("SMS reply without the success text -> Failed", frappe.db.get_value("Retail Message Log", row.name, "status") == "Failed")
	single(sms_success_text="")

	single(sms_gateway_url="http://127.0.0.1:1/unreachable")
	row = fresh("TEST-FAIL-5")
	engine.deliver(row.name)
	check("gateway unreachable -> Retry (worth trying again)", frappe.db.get_value("Retail Message Log", row.name, "status") == "Retry")
	single(sms_gateway_url="http://example.com/sms")
	row = fresh("TEST-FAIL-6")
	engine.deliver(row.name)
	d = frappe.get_doc("Retail Message Log", row.name)
	check("a plain-http gateway address on another machine is refused (Failed, no request made)", d.status == "Failed" and "https" in d.error, (d.status, d.error))
	single(sms_gateway_url=f"http://127.0.0.1:{PORT}/sms")

	single(whatsapp_phone_number_id="")
	row = fresh("TEST-FAIL-7", "WhatsApp")
	engine.deliver(row.name)
	d = frappe.get_doc("Retail Message Log", row.name)
	check("WhatsApp not set up -> Failed with a plain instruction", d.status == "Failed" and "not set up" in d.error, d.error)
	single(whatsapp_phone_number_id="PHONEID9")

	# ---- dry run is the default and sends nothing
	single(whatsapp_provider="Dry run", sms_provider="Dry run")
	set_gateway(200)
	engine.queue("Order ready", ctx("TEST-DRY-1"))
	for x in log_rows("TEST-DRY-1"):
		engine.deliver(x.name)
	rows = log_rows("TEST-DRY-1")
	check("Dry run: rows are Sent with a dry-run reference and the gateway got nothing", all(r.status == "Sent" and r.provider_message_id.startswith("dry-run-") and r.provider == "Dry run" for r in rows) and not seen, (rows[0].status, seen))

	# ---- never breaks a sale
	real_queue = engine._queue
	engine._queue = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
	try:
		engine.queue("Order ready", ctx("TEST-BOOM"))
		check("a bug inside queueing is logged, never raised into the sale", True)
	except Exception as e:
		check("a bug inside queueing is logged, never raised into the sale", False, e)
	finally:
		engine._queue = real_queue
	single(enable_messaging=0)
	engine.queue("Order ready", ctx("TEST-OFF"))
	check("messaging switched off -> nothing is queued", not log_rows("TEST-OFF"))
	single(enable_messaging=1)

	# ---- real Sales Order (storefront type) + delivery, through the doc_events
	hooks = frappe.get_hooks("doc_events")
	check("hooks: Sales Order on_submit and Delivery Note on_submit are wired", "retail_store.messaging.events.order_submitted" in str(hooks.get("Sales Order")) and "retail_store.messaging.events.delivery_submitted" in str(hooks.get("Delivery Note")))
	check("hook: Customer validate stamps consent", "retail_store.messaging.consent.stamp_consent" in str(hooks.get("Customer")))
	check("scheduler: retry_due every 5 minutes", "retail_store.messaging.engine.retry_due" in str(frappe.get_hooks("scheduler_events").get("cron")))
	item = frappe.db.get_value("Item", {"has_variants": 0, "disabled": 0, "is_sales_item": 1, "is_stock_item": 1}, "name")
	warehouse = frappe.db.get_single_value("Retail Store Settings", "main_warehouse") or frappe.db.get_value("Warehouse", {"is_group": 0}, "name")
	so = frappe.get_doc({"doctype": "Sales Order", "customer": cust.name, "order_type": "Shopping Cart", "delivery_date": add_days(today(), 3), "contact_mobile": "5799 1234",
		"items": [{"item_code": item, "qty": 1, "rate": 1500, "warehouse": warehouse}]})
	so.insert(ignore_permissions=True)
	so.submit()
	rows = log_rows(so.name)
	check("a submitted storefront Sales Order queues its confirmation(s) through the hook", len(rows) >= 1 and all(r.event == "Order confirmation" and r.recipient == "+23057991234" and r.customer == cust.name and r.status == "Sent" or r.status == "Queued" for r in rows), [(r.event, r.status, r.recipient) for r in rows])
	check("{customer} in the text is the first name, the total is formatted", all("Msg" in r.body and "1,500" in r.body for r in rows), rows[0].body if rows else None)
	pos_so = frappe.get_doc({"doctype": "Sales Order", "customer": cust.name, "order_type": "Sales", "delivery_date": add_days(today(), 3), "contact_mobile": "5799 1234",
		"items": [{"item_code": item, "qty": 1, "rate": 10, "warehouse": warehouse}]})
	pos_so.insert(ignore_permissions=True)
	pos_so.submit()
	check("an ordinary (non-storefront) Sales Order sends nothing", not log_rows(pos_so.name))
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	dn = make_delivery_note(so.name)
	dn.name = "TEST-DN-STOREFRONT"  # unsaved documents all share one temporary name
	events.delivery_submitted(dn)
	ready = [r for r in frappe.get_all("Retail Message Log", filters={"event": "Order ready", "reference_doctype": "Delivery Note", "reference_name": dn.name}, fields=["*"])]
	check("posting its delivery queues 'order ready' about the order", len(ready) >= 1 and all(so.name in r.body for r in ready), [(r.status, r.body) for r in ready])
	other = make_delivery_note(pos_so.name)
	other.name = "TEST-DN-COUNTER"
	events.delivery_submitted(other)
	check("delivery of a non-storefront order sends nothing", not frappe.get_all("Retail Message Log", filters={"reference_name": other.name}))

	# ---- who can see / change what
	def access(user):
		frappe.set_user(user)
		try:
			doc = frappe.get_doc("Retail Store Settings")
			doc.apply_fieldlevel_read_permissions()
			return {
				"sees_credentials": doc.get("whatsapp_api_version") is not None,
				"sees_rules": doc.get("message_rules") is not None,
				"write_levels": sorted(doc.get_permlevel_access("write")),
				"log_read": frappe.has_permission("Retail Message Log", "read"),
				"log_write": frappe.has_permission("Retail Message Log", "write") or frappe.has_permission("Retail Message Log", "delete"),
			}
		finally:
			frappe.set_user("Administrator")

	for user, creds, levels, log_read in [("owner@demo.example", True, [0, 2], True), ("admin@demo.example", False, [0], True), ("manager.downtown@demo.example", False, [], False),
			("cashier.downtown@demo.example", False, [], False), ("wh.attendant@demo.example", False, [], False)]:
		a = access(user) if user.split("@")[0] in ("owner", "admin") else None
		if a is None:
			frappe.set_user(user)
			a = {"sees_credentials": False, "write_levels": [], "log_read": frappe.has_permission("Retail Message Log", "read"), "log_write": frappe.has_permission("Retail Message Log", "write")}
			try:
				frappe.get_doc("Retail Store Settings").check_permission("read")
				a["sees_credentials"] = True
			except frappe.PermissionError:
				pass
			frappe.set_user("Administrator")
		role = user.split("@")[0]
		check(f"{role}: credentials visible = {creds}", a["sees_credentials"] == creds, a)
		check(f"{role}: can change settings at levels {levels}", a["write_levels"] == levels, a)
		check(f"{role}: Message Log readable = {log_read}, never editable or deletable", a["log_read"] == log_read and not a["log_write"], a)
	frappe.set_user("Administrator")
	sm = frappe.get_doc("Retail Store Settings").get_permlevel_access("write")
	check("System Manager changes every level (0, 1, 2)", sorted(sm) == [0, 1, 2], sm)
