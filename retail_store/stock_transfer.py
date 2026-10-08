"""Stock transfer rules between locations.

Two supported patterns:

(a) Routine replenishment
    Material Request (staff, own store as destination) -> approval workflow
    -> Stock Entry "Material Transfer" into the In-Transit warehouse (dispatch)
    -> "End Transit" Stock Entry at the destination (confirm receipt).

(b) Owner-initiated bulk transfer
    Store Owner / manager creates the Stock Entry directly (no request), either
    straight to the destination or via In-Transit with "Final Destination" set
    so the receiving store can confirm with "End Transit".
"""

import frappe
from frappe import _

from retail_store.location import get_user_warehouses
from retail_store.permissions import FINAL_DESTINATION

LOCATION_SCOPED_MR_TYPES = ("Material Transfer", "Material Issue")


def validate_material_request(doc, method=None):
	if doc.material_request_type == "Material Transfer" and not doc.get("set_from_warehouse"):
		main = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
		if main:
			doc.set_from_warehouse = main
			for d in doc.items:
				d.from_warehouse = d.from_warehouse or main

	warehouses = get_user_warehouses()
	if not warehouses or doc.material_request_type not in LOCATION_SCOPED_MR_TYPES:
		return
	# Only the requester is scoped to their own store. An approver at the source
	# warehouse (e.g. Main) must be able to approve a request destined elsewhere;
	# the permission hooks already limit which requests they can see.
	if not doc.is_new() and doc.owner != frappe.session.user:
		return

	allowed = set(warehouses)
	for d in doc.items:
		if d.warehouse and d.warehouse not in allowed:
			frappe.throw(
				_("Row {0}: you can only request stock for your own location(s): {1}").format(
					d.idx, ", ".join(sorted(allowed))
				),
				frappe.PermissionError,
			)


def validate_stock_entry(doc, method=None):
	if doc.get("add_to_transit") and doc.get(FINAL_DESTINATION):
		transit = {d.t_warehouse for d in doc.items if d.t_warehouse}
		if doc.get(FINAL_DESTINATION) in transit:
			frappe.throw(_("Final Destination must be different from the In-Transit warehouse"))

	warehouses = get_user_warehouses()
	if not warehouses:
		return
	allowed = set(warehouses)
	for d in doc.items:
		touched = {w for w in (d.s_warehouse, d.t_warehouse) if w}
		if touched and not touched & allowed and not _is_receipt_of_own_transfer(doc, d, allowed):
			frappe.throw(
				_("Row {0}: you can only move stock out of or into your own location(s): {1}").format(
					d.idx, ", ".join(sorted(allowed))
				),
				frappe.PermissionError,
			)


def _is_receipt_of_own_transfer(doc, row, allowed):
	"""A dispatch into In-Transit is allowed when the final destination is the user's store."""
	if doc.get(FINAL_DESTINATION) in allowed:
		return True
	if row.get("material_request_item"):
		return frappe.db.get_value("Material Request Item", row.material_request_item, "warehouse") in allowed
	return False


def set_final_destination_on_receipt(doc, method=None):
	"""On the 'End Transit' entry, default empty target warehouses to the final destination."""
	if not doc.get("outgoing_stock_entry") or not doc.is_new():
		return
	destination = frappe.db.get_value("Stock Entry", doc.outgoing_stock_entry, FINAL_DESTINATION)
	if not destination:
		return
	doc.set(FINAL_DESTINATION, destination)
	doc.to_warehouse = doc.to_warehouse or destination
	for d in doc.items:
		d.t_warehouse = d.t_warehouse or destination
