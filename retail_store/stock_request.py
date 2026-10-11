"""Server side of the "Request Stock" page (page/stock_request).

Shop-floor staff get one plain screen for the sanctioned transfer flow instead of the Material
Request / Stock Entry Desk forms: pick products and quantities, send the request, watch its status,
and (only if the Store Owner has allowed them to receive stock) confirm a delivery that arrived.
Everything goes through the normal documents and permission checks, so approval, location scoping
and the transfer-only rule in stock_transfer.py all still apply.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, today

from retail_store.location import get_user_warehouses
from retail_store.permissions import FINAL_DESTINATION

STATUS_WORDS = {
	"Draft": "Not sent yet",
	"Pending Approval": "Waiting for approval",
	"Approved": "Approved, being prepared",
	"Rejected": "Not approved",
	"Pending": "Approved, being prepared",
	"Partially Ordered": "On its way",
	"Ordered": "On its way",
	"Transferred": "Arrived",
	"Received": "Arrived",
	"Stopped": "Stopped",
	"Cancelled": "Cancelled",
}


def _can_receive():
	return bool({"Stock Receiver", "Store Manager", "Warehouse Manager", "Store Owner", "System Manager"} & set(frappe.get_roles()))


def _my_locations():
	"""Locations this person may request for. A restricted user sees their own; an unrestricted one
	(owner) sees every non-group location."""
	mine = get_user_warehouses()
	filters = {"is_group": 0, "disabled": 0}
	if mine:
		filters["name"] = ["in", mine]
	return frappe.get_all("Warehouse", filters=filters, pluck="name", order_by="name")


@frappe.whitelist()
def context():
	main = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
	locations = [w for w in _my_locations() if w != main]  # the main warehouse has no one to ask
	requests = frappe.get_all(
		"Material Request",
		filters={"owner": frappe.session.user, "material_request_type": "Material Transfer"},
		fields=["name", "creation", "status", "workflow_state", "docstatus"],
		order_by="creation desc",
		limit=12,
	)
	for r in requests:
		r["items"] = frappe.get_all(
			"Material Request Item",
			filters={"parent": r.name},
			fields=["item_name", "qty", "warehouse"],
		)
		word = r.workflow_state if r.docstatus == 0 and r.workflow_state else r.status
		r["state"] = _(STATUS_WORDS.get(word, word or "Not sent yet"))
	return {
		"locations": locations,
		"source": main,
		"requests": requests,
		"can_receive": _can_receive(),
	}


@frappe.whitelist()
def search_products(txt="", location=None):
	txt = (txt or "").strip()
	filters = {"disabled": 0, "is_stock_item": 1, "has_variants": 0}
	or_filters = None
	if txt:
		like = f"%{txt}%"
		or_filters = {"name": ["like", like], "item_name": ["like", like]}
	items = frappe.get_list(
		"Item", filters=filters, or_filters=or_filters, fields=["name", "item_name", "stock_uom"], limit=12, order_by="item_name"
	)
	if location and items:
		have = dict(
			frappe.get_all(
				"Bin",
				filters={"warehouse": location, "item_code": ["in", [i.name for i in items]]},
				fields=["item_code", "actual_qty"],
				as_list=True,
			)
		)
		for i in items:
			i["here"] = flt(have.get(i.name))
	return items


@frappe.whitelist()
def send_request(location, rows):
	"""rows: JSON list of {item_code, qty}. Creates the Material Request and sends it for approval."""
	rows = frappe.parse_json(rows) or []
	rows = [r for r in rows if flt(r.get("qty")) > 0]
	if not rows:
		frappe.throw(_("Add at least one product."))
	if location not in _my_locations():
		frappe.throw(_("You can only request stock for your own location."), frappe.PermissionError)
	main = frappe.db.get_single_value("Retail Store Settings", "main_warehouse")
	if not main:
		frappe.throw(_("The main warehouse is not set. Ask the store owner."))
	doc = frappe.get_doc(
		{
			"doctype": "Material Request",
			"material_request_type": "Material Transfer",
			"company": frappe.db.get_value("Warehouse", location, "company"),
			"schedule_date": add_days(today(), 3),
			"set_from_warehouse": main,
			"set_warehouse": location,
			"items": [
				{
					"item_code": r["item_code"],
					"qty": flt(r["qty"]),
					"warehouse": location,
					"from_warehouse": main,
					"schedule_date": add_days(today(), 3),
				}
				for r in rows
			],
		}
	)
	doc.insert()
	frappe.clear_messages()  # ERPNext's "Item rates have been updated..." toast means nothing here
	if frappe.db.get_value("Workflow", {"document_type": "Material Request", "is_active": 1}):
		from frappe.model.workflow import apply_workflow

		doc = apply_workflow(doc, "Submit for Approval")
	elif frappe.has_permission("Material Request", "submit"):
		doc.submit()
	return doc.name


def _destination(entry_name, final, rows):
	if final:
		return final
	for r in rows:
		if r.mr_dest:
			return r.mr_dest
	return None


@frappe.whitelist()
def incoming():
	"""Transfers on their way to this person's location that nobody has confirmed yet."""
	if not _can_receive():
		return []
	mine = set(get_user_warehouses() or [])
	out = []
	for se in frappe.get_all(
		"Stock Entry",
		filters={"docstatus": 1, "add_to_transit": 1, "stock_entry_type": "Material Transfer"},
		fields=["name", "posting_date", FINAL_DESTINATION],
		order_by="creation desc",
		limit=40,
	):
		rows = frappe.db.sql(
			"""select sed.item_name, sed.qty - sed.transferred_qty as left_qty, mri.warehouse as mr_dest
			from `tabStock Entry Detail` sed
			left join `tabMaterial Request Item` mri on mri.name = sed.material_request_item
			where sed.parent = %s and sed.qty > sed.transferred_qty""",
			se.name,
			as_dict=True,
		)
		if not rows:
			continue
		dest = _destination(se.name, se.get(FINAL_DESTINATION), rows)
		if mine and dest not in mine:
			continue
		out.append({"name": se.name, "date": str(se.posting_date), "destination": dest, "items": rows})
	return out


@frappe.whitelist()
def receive(entry):
	"""Confirm that a transfer arrived (Stock Entry 'End Transit')."""
	if not _can_receive():
		frappe.throw(_("You are not allowed to receive stock."), frappe.PermissionError)
	if entry not in {e["name"] for e in incoming()}:
		frappe.throw(_("That delivery is not waiting for your location."), frappe.PermissionError)
	from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry

	doc = make_stock_in_entry(entry)
	doc.insert()
	doc.submit()
	frappe.clear_messages()
	return doc.name
