"""Opt-in to offers / loyalty messages, per customer and per channel, with when / how / who.

Order messages (confirmation, ready) are transactional: they go to the number on the order. Anything
marketing-like needs the box ticked here (engine.queue refuses otherwise). Ticking it again or unticking it
is stamped; the earlier stamps stay, so there is always a record of when a choice was made.

A local adviser must confirm how the Data Protection Act 2017 and the ICTA treat each kind before real
marketing messages go out: see the README, section "Customer messages"."""

import frappe
from frappe.utils import cint, now_datetime

CHANNELS = {"WhatsApp": "custom_whatsapp_optin", "SMS": "custom_sms_optin"}
STAMPS = {
	"custom_whatsapp_optin": ("custom_whatsapp_optin_on", "custom_whatsapp_optout_on"),
	"custom_sms_optin": ("custom_sms_optin_on", "custom_sms_optout_on"),
}


def stamp_consent(doc, method=None):
	"""Customer validate: when a box changes, record when, how and by whom."""
	before = doc.get_doc_before_save()
	changed = False
	for field, (on_field, off_field) in STAMPS.items():
		now, was = bool(cint(doc.get(field))), bool(cint(before.get(field))) if before else False
		if now and not was:
			doc.set(on_field, now_datetime())
			doc.set(off_field, None)
			changed = True
		elif was and not now:
			doc.set(off_field, now_datetime())
			changed = True
	if changed:
		doc.custom_consent_by = frappe.session.user
		doc.custom_consent_source = frappe.flags.get("rs_consent_source") or "Recorded by staff"


def has_consent(customer, channel):
	field = CHANNELS.get(channel)
	return bool(field and customer and cint(frappe.db.get_value("Customer", customer, field)))


def consent_basis(customer, channel):
	field = CHANNELS[channel]
	when = frappe.db.get_value("Customer", customer, STAMPS[field][0])
	return f"Opt-in recorded {when}" if when else "Opt-in recorded"


def _messaging_on():
	return bool(cint(frappe.db.get_single_value("Retail Store Settings", "enable_messaging")))


def _own_customer():
	from retail_store.storefront import _own_customers

	if frappe.session.user == "Guest":
		return None
	own = _own_customers(frappe.session.user)
	return own[0] if own else None


@frappe.whitelist()
def get_cart_consent():
	"""The storefront cart's two boxes: shown only when messaging is on and the shopper is signed in. A box
	is ticked only if this customer ticked it before; it is never ticked for them."""
	customer = _own_customer()
	if not customer or not _messaging_on():
		return {"enabled": 0}
	return {
		"enabled": 1,
		"whatsapp": cint(frappe.db.get_value("Customer", customer, CHANNELS["WhatsApp"])),
		"sms": cint(frappe.db.get_value("Customer", customer, CHANNELS["SMS"])),
	}


@frappe.whitelist()
def save_cart_consent(whatsapp=0, sms=0):
	"""Called as the shopper presses Place Order: their own ticks (or unticks) become their consent record."""
	customer = _own_customer()
	if not customer or not _messaging_on():
		return
	doc = frappe.get_doc("Customer", customer)
	doc.custom_whatsapp_optin = cint(whatsapp)
	doc.custom_sms_optin = cint(sms)
	frappe.flags.rs_consent_source = "Storefront checkout"
	doc.flags.ignore_permissions = True  # the shopper edits only these two boxes, and only on their own customer
	doc.save()
