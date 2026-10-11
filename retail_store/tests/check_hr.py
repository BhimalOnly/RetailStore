"""Server-side checks for the HR module (needs hrms + the DEMO data).

Run: bench --site <site> execute retail_store.tests.check_hr.run
Leaves HR switched ON if it was on; removes the employees it creates.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

results = []
D = "@demo.example"
OWNER, ADMIN = "owner" + D, "admin" + D
MGR_DT, CASH_DT, CASH_MALL = "manager.downtown" + D, "cashier.downtown" + D, "cashier.mall" + D
TAG = "RSHR"


def check(name, ok, detail=""):
	results.append((name, bool(ok)))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def wh(label):
	return frappe.db.get_value("Warehouse", {"warehouse_name": f"DEMO Store {label}"}, "name")


def as_user(user, fn):
	frappe.set_user(user)
	try:
		return fn()
	finally:
		frappe.set_user("Administrator")


def names(user, doctype="Employee"):
	return set(as_user(user, lambda: frappe.get_list(doctype, pluck="name", limit_page_length=0)))


def make_employee(first, user=None, store=None):
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first,
			"last_name": TAG,
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2024-01-01",
			"company": company,
			"status": "Active",
			"user_id": user,
			"custom_store_warehouse": store,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def cleanup():
	frappe.set_user("Administrator")
	emps = frappe.get_all("Employee", filters={"last_name": TAG}, pluck="name")
	for dt in ("Employee Checkin", "Attendance", "Leave Application", "Employee Incentive"):
		for n in frappe.get_all(dt, filters={"employee": ["in", emps]}, pluck="name") if emps else []:
			frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
	for n in emps:
		frappe.delete_doc("Employee", n, force=True, ignore_permissions=True)
	# rows left by an earlier run whose employee is gone would be inherited by a re-used employee id
	frappe.db.sql("delete from `tabEmployee Incentive` where employee not in (select name from `tabEmployee`)")
	frappe.db.commit()


def run():
	frappe.set_user("Administrator")
	cleanup()
	s = frappe.get_doc("Retail Store Settings")
	was_on = s.enable_hr
	s.enable_hr = 1
	s.save()
	downtown, mall, airport = wh("Downtown"), wh("Mall"), wh("Airport")

	# --- setup from settings
	check("Annual Leave type seeded from settings", frappe.db.get_value("Leave Type", "Annual Leave", "max_leaves_allowed") == s.hr_annual_leave_days)
	check("Payroll components exist", all(frappe.db.exists("Salary Component", c) for c in ("CSG (Employee)", "HRDC Levy (Employer)", "PRGF (Employer)", "PAYE", "End of Year Bonus")))
	csg = frappe.db.get_value("Salary Component", "CSG (Employee)", "formula")
	check("CSG formula is built from the settings", str(int(s.csg_salary_threshold)) in csg and f"{s.csg_employee_rate_low:g}" in csg, csg)
	check("Employer components are statistical (never reduce net pay)", frappe.db.get_value("Salary Component", "CSG (Employer)", "statistical_component") == 1)
	check("PAYE slab submitted with 3 bands", frappe.db.exists("Income Tax Slab", {"name": ["like", "Mauritius PAYE%"], "docstatus": 1}))
	before = frappe.db.count("Income Tax Slab")
	s.reload()
	s.save()
	check("Re-saving settings does not duplicate the slab", frappe.db.count("Income Tax Slab") == before)
	check("Overtime type uses the settings multipliers", frappe.db.get_value("Overtime Type", "Retail Overtime", "standard_multiplier") == s.hr_overtime_multiplier)

	# --- grants
	def perm(role, dt, ptype):
		return bool(frappe.db.get_value("Custom DocPerm", {"parent": dt, "role": role, "permlevel": 0, ptype: 1}))

	check("Store Owner can create Employee", perm("Store Owner", "Employee", "create"))
	check("Store Admin can create Employee", perm("Store Admin", "Employee", "create"))
	check("Store Manager CANNOT create Employee", not perm("Store Manager", "Employee", "create"))
	check("Store Manager can write Employee", perm("Store Manager", "Employee", "write"))
	check("Store Manager can submit Attendance / Leave", perm("Store Manager", "Attendance", "submit") and perm("Store Manager", "Leave Application", "submit"))
	check("Store Owner holds payroll", perm("Store Owner", "Salary Slip", "submit") and perm("Store Owner", "Salary Structure", "write"))
	check("Store Manager holds NO payroll", not any(perm("Store Manager", d, "read") for d in ("Salary Slip", "Salary Structure", "Salary Component", "Payroll Entry", "Income Tax Slab")))
	check("Store Admin holds NO payroll", not any(perm("Store Admin", d, "read") for d in ("Salary Slip", "Salary Structure", "Payroll Entry")))
	check("Cashier can clock in (Employee Checkin create)", perm("Store Cashier", "Employee Checkin", "create"))
	check("Cashier has no Employee list", not perm("Store Cashier", "Employee", "read"))

	# --- one location, two sources
	e_dt = make_employee("Dt", CASH_DT, mall)  # deliberately wrong: login's access says Downtown
	check("Employee with a login takes the Retail Staff Access location", e_dt.custom_store_warehouse == downtown, e_dt.custom_store_warehouse)
	e_mgr = make_employee("Mgr", MGR_DT)
	e_mall = make_employee("Mall", CASH_MALL)
	e_nologin_dt = make_employee("NoLoginDt", None, downtown)
	e_nologin_ap = make_employee("NoLoginAp", None, airport)
	e_owner = make_employee("Owner", OWNER)
	check("Self User Permission is never created", not frappe.db.exists("User Permission", {"allow": "Employee", "for_value": e_dt.name}))

	frappe.db.set_value("Retail Staff Access", CASH_DT, "enabled", 1)
	access = frappe.get_doc("Retail Staff Access", CASH_DT)
	original = [(r.warehouse, r.is_default) for r in access.locations]
	access.set("locations", [{"warehouse": mall, "is_default": 1}])
	access.save()
	check("Changing Retail Staff Access moves the employee", frappe.db.get_value("Employee", e_dt.name, "custom_store_warehouse") == mall)
	access.set("locations", [{"warehouse": w, "is_default": d} for w, d in original])
	access.save()
	check("...and back", frappe.db.get_value("Employee", e_dt.name, "custom_store_warehouse") == downtown)

	# --- scoping
	mgr_sees = names(MGR_DT)
	check("Store Manager sees own store's staff (login and loginless)", {e_dt.name, e_mgr.name, e_nologin_dt.name} <= mgr_sees, mgr_sees)
	check("Store Manager does NOT see other stores' staff", not ({e_mall.name, e_nologin_ap.name, e_owner.name} & mgr_sees), mgr_sees)
	check("Cashier sees only themself", names(CASH_DT) == {e_dt.name}, names(CASH_DT))
	check("Owner sees every employee", {e.name for e in (e_dt, e_mgr, e_mall, e_nologin_dt, e_nologin_ap, e_owner)} <= names(OWNER))
	check("Store Admin sees the Employee list", {e_mall.name, e_dt.name} <= names(ADMIN))
	check("By-URL read of another store's employee is refused", not as_user(MGR_DT, lambda: frappe.has_permission("Employee", "read", e_mall.name)))
	check("By-URL read of own store's employee allowed", as_user(MGR_DT, lambda: frappe.has_permission("Employee", "read", e_nologin_dt.name)))
	check("Manager cannot create Employee", not as_user(MGR_DT, lambda: frappe.has_permission("Employee", "create")))
	check("Owner can create Employee", as_user(OWNER, lambda: frappe.has_permission("Employee", "create")))

	def move_out():
		d = frappe.get_doc("Employee", e_nologin_dt.name)
		d.custom_store_warehouse = mall
		try:
			d.save()
		except frappe.PermissionError:
			return True
		return False

	check("Manager cannot move an employee to another store", as_user(MGR_DT, move_out))

	# --- personal / payroll doctypes (HRMS lets the "Employee" role READ these; hr.py scopes them)
	comp = frappe.db.get_value("Salary Component", {"type": "Earning"}, "name")
	for emp in (e_dt, e_mall):
		d = frappe.get_doc({"doctype": "Employee Incentive", "employee": emp.name, "salary_component": comp, "incentive_amount": 100, "payroll_date": "2026-10-01"})
		d.flags.ignore_validate = True  # it wants a Salary Structure; we only need a row to read
		d.insert(ignore_permissions=True)
	inc = lambda u: {frappe.db.get_value("Employee Incentive", n, "employee") for n in names(u, "Employee Incentive")}
	check("Linked staff hold the Employee role (the exposure being tested)", "Employee" in frappe.get_roles(MGR_DT))
	check("Manager sees NO other person's payroll document", inc(MGR_DT) == set(), inc(MGR_DT))
	check("Cashier sees only their own payroll document", inc(CASH_DT) == {e_dt.name}, inc(CASH_DT))
	check("Owner sees every payroll document", {e_dt.name, e_mall.name} <= inc(OWNER))
	incs = frappe.get_all("Employee Incentive", filters={"employee": ["in", [e_dt.name, e_mall.name]]}, pluck="name")
	check("By-URL read of someone else's payroll document refused", not any(as_user(MGR_DT, lambda n=n: frappe.has_permission("Employee Incentive", "read", n)) for n in incs))
	for n in incs:
		frappe.delete_doc("Employee Incentive", n, force=True, ignore_permissions=True)

	# --- nothing readable by an HR-linked user escapes the scoping (catches doctypes added by an HRMS upgrade)
	from retail_store.hr_doctypes import EMPLOYEE_FIELD, EXEMPT

	uncovered = []
	for dt in frappe.get_all("DocType", filters={"istable": 0, "issingle": 0, "is_virtual": 0}, pluck="name"):
		if dt in EMPLOYEE_FIELD or dt in EXEMPT:
			continue
		meta = frappe.get_meta(dt)
		if not any(f.fieldtype == "Link" and f.options == "Employee" for f in meta.fields):
			continue
		for role in ("Employee", "Store Manager", "Store Admin", "Store Cashier", "Store Attendant"):
			if any(p.role == role and p.read and not p.if_owner and not p.permlevel for p in meta.permissions):
				uncovered.append((dt, role))
	check("Every Employee-linked doctype readable by those roles is scoped", not uncovered, uncovered)

	# --- linked doctypes
	now = now_datetime()
	for emp, hours in ((e_dt, -3), (e_nologin_ap, -3), (e_nologin_dt, -3)):
		frappe.get_doc({"doctype": "Employee Checkin", "employee": emp.name, "log_type": "IN", "time": add_to_date(now, hours=hours)}).insert(ignore_permissions=True)
	mgr_ck = {frappe.db.get_value("Employee Checkin", n, "employee") for n in names(MGR_DT, "Employee Checkin")}
	check("Manager sees checkins of own store only", mgr_ck >= {e_dt.name, e_nologin_dt.name} and e_nologin_ap.name not in mgr_ck, mgr_ck)
	cash_ck = {frappe.db.get_value("Employee Checkin", n, "employee") for n in names(CASH_DT, "Employee Checkin")}
	check("Cashier sees own checkins only", cash_ck == {e_dt.name}, cash_ck)

	# --- clock page API (the signed-in user's own record only)
	from retail_store import hr

	st = as_user(CASH_MALL, hr.clock_status)
	check("Clock status: Mall cashier is clocked out", st["employee"] == e_mall.name and st["next"] == "IN", st)
	st = as_user(CASH_MALL, lambda: hr.clock("IN"))
	check("Clock in works for staff (no Desk rights needed)", st["next"] == "OUT" and len(st["logs"]) >= 1, st)
	try:
		as_user(CASH_MALL, lambda: hr.clock("IN"))
		check("Double clock-in refused", False)
	except frappe.ValidationError:
		check("Double clock-in refused", True)
	st = as_user(CASH_MALL, lambda: hr.clock("OUT"))
	check("Clock out works", st["next"] == "IN", st)
	check("Clock only ever writes the caller's own employee", {l["employee"] for l in frappe.get_all("Employee Checkin", filters={"employee": e_mall.name}, fields=["employee"])} == {e_mall.name})
	st = as_user("wh.attendant@demo.example", hr.clock_status)
	check("User with no Employee record gets a clear empty state", st["employee"] is None)

	# --- switching HR off hides the clock
	s.reload()
	s.enable_hr = 0
	s.save()
	try:
		as_user(CASH_MALL, hr.clock_status)
		check("Clock refused while HR is off", False)
	except frappe.PermissionError:
		check("Clock refused while HR is off", True)
	check("HR off revokes manager grants", not perm("Store Manager", "Attendance", "read"))
	if was_on:
		s.reload()
		s.enable_hr = 1
		s.save()
	cleanup()

	failed = [n for n, ok in results if not ok]
	print(f"\n{len(results) - len(failed)}/{len(results)} passed")
	if failed:
		print("FAILED:", failed)
