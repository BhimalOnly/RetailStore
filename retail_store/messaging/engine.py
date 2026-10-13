"""Rules -> consent -> Retail Message Log row -> background send -> retry.

queue() runs inside the sale / delivery (so it must be quick and must never raise): it writes the log row and
hands the actual sending to a background job. deliver() sends one row; retry_due() (scheduler) picks up
rows that failed for a reason worth retrying, with a growing wait, and gives up after MAX_ATTEMPTS."""

import re

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from retail_store.messaging import consent, providers
from retail_store.messaging.phone import normalize

MAX_ATTEMPTS = 3
BACKOFF_MINUTES = [5, 30]  # wait after the 1st and 2nd failed attempt
EVENTS = ("Order confirmation", "Order ready")
PLACEHOLDERS = ("customer", "order", "store", "total")
_TOKEN = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


def render(body, ctx):
	"""Only the four known placeholders are replaced (no str.format: owners edit this text)."""
	return _TOKEN.sub(lambda m: str(ctx.get(m.group(1), "")), body or "")


def variables(body, ctx):
	"""The placeholders' values in the order they appear: WhatsApp templates take them as {{1}}, {{2}}..."""
	return [str(ctx.get(name, "")) for name in _TOKEN.findall(body or "")]


def queue(event, ctx, kind="Transactional"):
	"""ctx: customer (first name), customer_id, order, store, total, phone, reference_doctype, reference_name."""
	try:
		_queue(event, ctx, kind)
	except Exception:
		frappe.log_error(title=f"Customer messages: could not queue '{event}'")


def _queue(event, ctx, kind):
	settings = frappe.get_single("Retail Store Settings")
	if not cint(settings.enable_messaging):
		return
	phone = normalize(ctx.get("phone"), settings.messaging_country_code)
	for rule in settings.get("message_rules") or []:
		if rule.event != event or not cint(rule.enabled):
			continue
		same = {"event": event, "channel": rule.channel, "reference_doctype": ctx["reference_doctype"], "reference_name": ctx["reference_name"]}
		if frappe.db.exists("Retail Message Log", {**same, "status": ["in", ["Queued", "Retry", "Sent"]]}):
			continue  # this event was already sent / is on its way (e.g. the document was amended)
		status, problem, basis = "Queued", "", "Order message, sent to the number on the order"
		if not phone:
			status, problem = "Skipped", "There is no usable phone number on the order."
		elif kind == "Marketing":
			if consent.has_consent(ctx.get("customer_id"), rule.channel):
				basis = consent.consent_basis(ctx["customer_id"], rule.channel)
			else:
				status, problem = "Skipped", f"The customer has not opted in to {rule.channel} offers."
		log = frappe.get_doc(
			{
				"doctype": "Retail Message Log",
				**same,
				"kind": kind,
				"status": status,
				"recipient": phone or ctx.get("phone") or "",
				"customer": ctx.get("customer_id"),
				"body": render(rule.body, ctx),
				"template_name": rule.whatsapp_template if rule.channel == "WhatsApp" else "",
				"template_language": rule.template_language or "en",
				"template_variables": frappe.as_json(variables(rule.body, ctx)),
				"error": problem,
				"consent_basis": basis if status == "Queued" else "",
			}
		)
		log.flags.ignore_links = True  # the log outlives the order it describes: never refuse to write it
		log.insert(ignore_permissions=True)
		if status == "Queued":
			frappe.enqueue("retail_store.messaging.engine.deliver", log=log.name, queue="short", enqueue_after_commit=True)


def deliver(log):
	"""Send one Queued / Retry row. Records the outcome on the row; never raises."""
	doc = frappe.get_doc("Retail Message Log", log)
	if doc.status not in ("Queued", "Retry"):
		return
	settings = frappe.get_single("Retail Store Settings")
	doc.attempts = cint(doc.attempts) + 1
	try:
		provider = providers.get_provider(doc.channel, settings)
		doc.provider = provider.name
		doc.provider_message_id = provider.send(
			doc.recipient,
			doc.body,
			template=doc.template_name or None,
			language=doc.template_language,
			variables=frappe.parse_json(doc.template_variables) if doc.template_variables else [],
		)
		doc.status, doc.sent_on, doc.error, doc.next_attempt_at = "Sent", now_datetime(), "", None
	except providers.ProviderError as e:
		_failed(doc, str(e), e.transient, settings)
	except Exception as e:  # a bug must not lose the message or loop forever
		frappe.log_error(title="Customer messages: unexpected error while sending")
		_failed(doc, f"Unexpected error ({type(e).__name__})", False, settings)
	doc.flags.ignore_links = True
	doc.save(ignore_permissions=True)


def _failed(doc, message, transient, settings):
	for secret in providers.secrets(settings):
		message = message.replace(secret, "***")
	doc.error = message[:400]
	if transient and doc.attempts < MAX_ATTEMPTS:
		doc.status = "Retry"
		doc.next_attempt_at = add_to_date(now_datetime(), minutes=BACKOFF_MINUTES[min(doc.attempts, len(BACKOFF_MINUTES)) - 1])
	else:
		doc.status, doc.next_attempt_at = "Failed", None


def retry_due():
	"""Scheduler (every 5 minutes): rows due for another go, and rows whose background job never ran."""
	now = now_datetime()
	due = frappe.get_all("Retail Message Log", filters={"status": "Retry", "next_attempt_at": ["<=", now]}, pluck="name", limit=50)
	stuck = frappe.get_all("Retail Message Log", filters={"status": "Queued", "creation": ["<", add_to_date(now, minutes=-15)]}, pluck="name", limit=50)
	for name in due + stuck:
		deliver(name)  # (the scheduler commits when the job ends)
