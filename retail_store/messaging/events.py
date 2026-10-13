"""doc_events: a storefront order is placed -> confirmation; its delivery is posted -> order ready."""

import frappe
from frappe.utils import fmt_money

from retail_store.messaging.engine import queue

ONLINE_ORDER = "Shopping Cart"  # what webshop sets as Sales Order.order_type


def _phone(so):
	"""The number on the order, then the customer's own, then the delivery / billing address."""
	for number in (so.get("contact_mobile"), so.get("contact_phone")):
		if number:
			return number
	number = frappe.db.get_value("Customer", so.customer, "mobile_no")
	if number:
		return number
	for address in (so.get("shipping_address_name"), so.get("customer_address")):
		number = address and frappe.db.get_value("Address", address, "phone")
		if number:
			return number
	return None


def _store():
	return frappe.db.get_single_value("Retail Store Settings", "brand_name") or frappe.defaults.get_global_default("company") or ""


def _context(so, reference):
	"""What a message can say ({customer} is the first name) and who it is about (customer_id, for consent)."""
	return {
		"customer": (so.customer_name or so.customer or "").strip().split(" ")[0],
		"customer_id": so.customer,
		"phone": _phone(so),
		"order": so.name,
		"store": _store(),
		"total": fmt_money(so.grand_total, currency=so.currency),
		"reference_doctype": reference.doctype,
		"reference_name": reference.name,
	}


def order_submitted(doc, method=None):
	if doc.order_type != ONLINE_ORDER:
		return
	try:
		queue("Order confirmation", _context(doc, doc))
	except Exception:
		frappe.log_error(title="Customer messages: order confirmation")


def delivery_submitted(doc, method=None):
	try:
		for name in {row.against_sales_order for row in doc.get("items") if row.get("against_sales_order")}:
			so = frappe.get_doc("Sales Order", name)
			if so.order_type == ONLINE_ORDER:
				queue("Order ready", _context(so, doc))
	except Exception:
		frappe.log_error(title="Customer messages: order ready")
