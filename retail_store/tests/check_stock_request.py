"""Server-side checks for the frontline stock rules and the owner-controlled extra permissions.

Run: bench --site <site> execute retail_store.tests.check_stock_request.run
Needs the DEMO data. Puts the Retail Store Settings grants table back as it found it.
"""

import frappe

results = []
D = "@demo.example"
OWNER, ADMIN, MGR = "owner" + D, "admin" + D, "manager.downtown" + D
CASH, ATT, WHM = "cashier.downtown" + D, "wh.attendant" + D, "wh.manager" + D


def check(name, ok, detail=""):
	results.append((name, bool(ok)))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def as_user(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


def fails(user, fn):
	try:
		as_user(user, fn)
	except Exception:
		frappe.db.rollback()
		return True
	return False


def can(user, doctype, ptype):
	return bool(as_user(user, lambda: frappe.has_permission(doctype, ptype, user=user)))


def set_grants(rows, user="Administrator"):
	frappe.set_user(user)
	try:
		s = frappe.get_doc("Retail Store Settings")
		s.set("staff_grants", [])
		for staff, perm in rows:
			s.append("staff_grants", {"staff": staff, "permission": perm})
		s.save()
	finally:
		frappe.set_user("Administrator")


def run():
	original = [(r.staff, r.permission) for r in frappe.get_doc("Retail Store Settings").staff_grants]
	try:
		_run()
	finally:
		frappe.set_user("Administrator")
		set_grants(original)
		frappe.db.commit()
	bad = [n for n, ok in results if not ok]
	print(f"\n{len(results) - len(bad)}/{len(results)} passed; {len(bad)} failures")


def _run():
	set_grants([])
	frappe.db.commit()
	mine = frappe.db.get_value("User Permission", {"user": CASH, "allow": "Warehouse"}, "for_value")
	item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1, "has_variants": 0}, "name")

	# defaults: frontline can sell and request, nothing else
	for user in (CASH, ATT):
		check(f"{user}: no Item Price write", not can(user, "Item Price", "write"))
		check(f"{user}: no Item write", not can(user, "Item", "write"))
		check(f"{user}: no Stock Entry create", not can(user, "Stock Entry", "create"))
	check("manager keeps Item Price write", can(MGR, "Item Price", "write"))

	# Material Request: transfer only for frontline
	def mr(kind):
		def f():
			d = frappe.get_doc({
				"doctype": "Material Request", "material_request_type": kind, "company": frappe.db.get_value("Warehouse", mine, "company"),
				"schedule_date": frappe.utils.add_days(frappe.utils.today(), 3),
				"items": [{"item_code": item, "qty": 1, "warehouse": mine, "schedule_date": frappe.utils.add_days(frappe.utils.today(), 3)}],
			})
			d.insert()
		return f
	for kind in ("Purchase", "Material Issue", "Manufacture"):
		check(f"cashier cannot raise a {kind} request", fails(CASH, mr(kind)))
	check("manager can still raise a Purchase request", not fails(MGR, mr("Purchase")))

	# the Request Stock page's own API
	ctx = as_user(CASH, lambda: frappe.call("retail_store.stock_request.context"))
	check("store staff see own location + main as source", ctx["locations"] == [mine] and ctx["source"], ctx)
	check("store staff cannot receive by default", not ctx["can_receive"])
	check("main-warehouse staff have no one to ask", as_user(ATT, lambda: frappe.call("retail_store.stock_request.context"))["locations"] == [])
	check("incoming empty without the grant", as_user(ATT, lambda: frappe.call("retail_store.stock_request.incoming")) == [])
	name = as_user(CASH, lambda: frappe.call("retail_store.stock_request.send_request", location=ctx["locations"][0], rows=frappe.as_json([{"item_code": item, "qty": 2}])))
	doc = frappe.get_doc("Material Request", name)
	check("request created as Material Transfer", doc.material_request_type == "Material Transfer" and doc.owner == CASH)
	check("request is waiting for approval", doc.workflow_state == "Pending Approval", doc.workflow_state)
	check("cannot request for another location", fails(CASH, lambda: frappe.call("retail_store.stock_request.send_request", location="Not A Place - X", rows=frappe.as_json([{"item_code": item, "qty": 1}]))))
	check("receive refused without the grant", fails(CASH, lambda: frappe.call("retail_store.stock_request.receive", entry="x")))

	# owner grants: roles follow the table, only the owner may edit it
	check("store admin cannot edit grants", fails(ADMIN, lambda: set_grants([(ATT, "Receive stock")], user=ADMIN)))
	set_grants([(ATT, "Receive stock"), (CASH, "Change prices")], user=OWNER)
	roles = lambda u: set(frappe.get_roles(u))
	check("grant adds Stock Receiver", "Stock Receiver" in roles(ATT))
	check("grant adds Price Editor", "Price Editor" in roles(CASH))
	check("granted receiver can create Stock Entry", can(ATT, "Stock Entry", "create"))
	check("granted price editor can write Item Price", can(CASH, "Item Price", "write"))
	check("granted price editor still cannot write Item", not can(CASH, "Item", "write"))

	att_loc = frappe.db.get_value("User Permission", {"user": ATT, "allow": "Warehouse"}, "for_value")

	def entry(kind):
		def f():
			where = att_loc
			d = frappe.get_doc({
				"doctype": "Stock Entry", "stock_entry_type": kind, "company": frappe.db.get_value("Warehouse", where, "company"),
				"items": [{"item_code": item, "qty": 1, "t_warehouse": where if kind == "Material Receipt" else None,
					"s_warehouse": where if kind == "Material Issue" else None, "basic_rate": 1}],
			})
			d.insert()
		return f
	check("receiver can book a Material Receipt", not fails(ATT, entry("Material Receipt")))
	check("receiver cannot book a Material Issue", fails(ATT, entry("Material Issue")))
	check("receiver cannot book Manufacture", fails(ATT, entry("Manufacture")))
	check("receiver sees the incoming list", isinstance(as_user(ATT, lambda: frappe.call("retail_store.stock_request.incoming")), list))

	# removing the row removes the right
	set_grants([], user=OWNER)
	check("removing grant removes Stock Receiver", "Stock Receiver" not in roles(ATT))
	check("removing grant removes Price Editor", "Price Editor" not in roles(CASH))
	check("cashier back to no Item Price write", not can(CASH, "Item Price", "write"))
	frappe.db.rollback()


def seed_dispatch(requester=CASH):
	"""For the browser test: approve the requester's newest pending request, dispatch it into transit,
	and give the requester the 'Receive stock' right. Run: ...check_stock_request.seed_dispatch"""
	from frappe.model.workflow import apply_workflow
	from erpnext.stock.doctype.material_request.material_request import make_in_transit_stock_entry

	name = frappe.db.get_value("Material Request", {"owner": requester, "workflow_state": "Pending Approval"}, "name", order_by="creation desc")
	frappe.set_user(OWNER)
	mr = apply_workflow(frappe.get_doc("Material Request", name), "Approve")
	transit = frappe.db.get_single_value("Retail Store Settings", "in_transit_warehouse")
	se = make_in_transit_stock_entry(mr.name, transit)
	se.insert()
	se.submit()
	frappe.set_user("Administrator")
	set_grants([(requester, "Receive stock")], user=OWNER)
	frappe.db.commit()
	print("dispatched", se.name, "from", mr.name)


def clear_grants():
	"""Undo seed_dispatch's grant after the browser test."""
	set_grants([], user=OWNER)
	frappe.db.commit()
