"""HR for the retail starter pack (needs the hrms app, switched on by Retail Store Settings > enable_hr).

Three jobs:

1. Location scoping. Employee carries ONE location field (custom_store_warehouse). For an
   employee with a login, that field is copied from the user's Retail Staff Access default
   location, so Retail Staff Access stays the single source of truth for people who log in;
   loginless staff are set directly. A Store Manager sees (and manages) employees of their own
   stores, everyone else sees only themselves, Store Owner / System Manager / HR Manager see all.
   The hooks mirror permissions.py: query conditions hide rows, has_permission refuses by URL.

2. Clock in / out for the shop floor (page "store-clock"), built on HRMS' own
   add_log_based_on_employee_field so Employee Checkin, shift fetch and auto-attendance all
   behave exactly as HRMS designed.

3. Defaults seeded from Retail Store Settings (leave types, overtime type, payroll components,
   PAYE slab). No rate lives in this file: every figure is read from the settings. They are a
   starting point and MUST be verified by the client's own accountant (see mauritius_payroll_reference.md).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime, getdate, now_datetime, today

from retail_store.location import get_user_warehouses

STORE_FIELD = "custom_store_warehouse"

from retail_store.hr_doctypes import EMPLOYEE_FIELD, STORE_SCOPED  # noqa: E402

SEES_ALL = {"System Manager", "Store Owner", "HR Manager", "Payroll Manager"}
STORE_ROLES = {"Store Manager", "HR User"}


def _esc(value):
	return frappe.db.escape(value)


def get_scope(user=None, doctype="Employee"):
	"""("all", None) | ("stores", [warehouses]) | ("own", None) for this user on this doctype."""
	user = user or frappe.session.user
	if user == "Administrator":
		return "all", None
	roles = set(frappe.get_roles(user))
	if roles & SEES_ALL:
		return "all", None
	# Store Admin creates Employee records, so it sees that list; it holds no other HR rights.
	if doctype == "Employee" and "Store Admin" in roles:
		return "all", None
	if doctype in STORE_SCOPED and roles & STORE_ROLES:
		return "stores", get_user_warehouses(user) or []
	return "own", None


def _employee_condition(user, doctype="Employee", table="`tabEmployee`"):
	kind, warehouses = get_scope(user, doctype)
	if kind == "all":
		return ""
	own = f"{table}.user_id = {_esc(user)}"
	if kind == "stores" and warehouses:
		stores = ", ".join(_esc(w) for w in warehouses)
		return f"({own} or {table}.{STORE_FIELD} in ({stores}))"
	return own


def query_conditions(user=None, doctype=None):
	"""permission_query_conditions for every doctype in hr_doctypes.EMPLOYEE_FIELD."""
	user = user or frappe.session.user
	cond = _employee_condition(user, doctype)
	if not cond:
		return ""
	if doctype == "Employee":
		return cond
	field = EMPLOYEE_FIELD[doctype]
	return f"`tab{doctype}`.`{field}` in (select name from `tabEmployee` where {cond})"


def _employee_allowed(employee, user, doctype="Employee"):
	kind, warehouses = get_scope(user, doctype)
	if kind == "all":
		return True
	row = frappe.db.get_value("Employee", employee, ["user_id", STORE_FIELD], as_dict=True)
	if not row:
		return True  # nothing to protect; the form's own validation reports a bad link
	if row.user_id == user:
		return True
	return kind == "stores" and bool(row.get(STORE_FIELD)) and row.get(STORE_FIELD) in (warehouses or [])


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Refuse by URL what query_conditions hides from lists (deny only, like every hook here)."""
	user = user or frappe.session.user
	if doc.doctype == "Employee":
		return True if doc.is_new() else _employee_allowed(doc.name, user)
	field = EMPLOYEE_FIELD.get(doc.doctype)
	value = doc.get(field) if field else None
	return not value or _employee_allowed(value, user, doc.doctype)


# --- One location per employee ------------------------------------------------------------


def access_default_location(user):
	"""Default store of a user's Retail Staff Access, or None when they have no (enabled) one."""
	if not frappe.db.exists("Retail Staff Access", {"user": user, "enabled": 1}):
		return None
	rows = frappe.get_all(
		"Retail Staff Location",
		filters={"parent": user, "parenttype": "Retail Staff Access"},
		fields=["warehouse", "is_default"],
		order_by="idx",
	)
	default = next((r.warehouse for r in rows if r.is_default), None)
	return default or (rows[0].warehouse if rows else None)


def employee_validate(doc, method=None):
	# A self User Permission (HRMS' create_user_permission) would stop a Store Manager seeing
	# their store's staff, because it filters every Employee link on every doctype. Own-record
	# access is enforced by the hooks above instead.
	doc.create_user_permission = 0

	if doc.user_id:
		store = access_default_location(doc.user_id)
		if store and doc.get(STORE_FIELD) != store:
			if doc.get(STORE_FIELD) and not doc.is_new():
				frappe.msgprint(
					_("Location set to {0}: it follows {1}'s Retail Staff Access. Change it there.").format(
						store, doc.user_id
					),
					indicator="orange",
					alert=True,
				)
			doc.set(STORE_FIELD, store)

	kind, warehouses = get_scope(doctype="Employee")
	if kind == "stores" and doc.get(STORE_FIELD) not in (warehouses or []):
		frappe.throw(_("You can only manage employees of your own stores."), frappe.PermissionError)


def sync_employees_for_user(user):
	"""Retail Staff Access changed: move that user's Employee record(s) with it."""
	store = access_default_location(user)
	if not store or not frappe.db.has_column("Employee", STORE_FIELD):
		return
	for name in frappe.get_all("Employee", filters={"user_id": user, STORE_FIELD: ["!=", store]}, pluck="name"):
		frappe.db.set_value("Employee", name, STORE_FIELD, store, update_modified=False)


def backfill_employee_stores():
	for user in frappe.get_all("Retail Staff Access", filters={"enabled": 1}, pluck="user"):
		sync_employees_for_user(user)


# --- Clock in / out -----------------------------------------------------------------------

STALE_HOURS = 18  # an IN older than this was a forgotten clock-out; start a new shift


def _require_hr():
	if "hrms" not in frappe.get_installed_apps() or not cint(
		frappe.db.get_single_value("Retail Store Settings", "enable_hr")
	):
		frappe.throw(_("Clock in/out is not switched on for this store."), frappe.PermissionError)


def _my_employee():
	return frappe.db.get_value(
		"Employee",
		{"user_id": frappe.session.user, "status": "Active"},
		["name", "employee_name", STORE_FIELD],
		as_dict=True,
	)


def _worked_hours(logs, now):
	total, started = 0.0, None
	for log in logs:
		if log.log_type == "IN" and started is None:
			started = get_datetime(log.time)
		elif log.log_type == "OUT" and started is not None:
			total += (get_datetime(log.time) - started).total_seconds() / 3600
			started = None
	if started is not None:
		total += (now - started).total_seconds() / 3600
	return round(total, 2)


def _expected_next(employee, now):
	last = frappe.get_all(
		"Employee Checkin",
		filters={"employee": employee},
		fields=["log_type", "time"],
		order_by="time desc, creation desc",
		limit=1,
	)
	if last and last[0].log_type == "IN" and get_datetime(last[0].time) > add_to_date(now, hours=-STALE_HOURS):
		return "OUT", last[0]
	return "IN", (last[0] if last else None)


@frappe.whitelist()
def clock_status():
	_require_hr()
	emp = _my_employee()
	if not emp:
		return {"employee": None}
	now = now_datetime()
	nxt, last = _expected_next(emp.name, now)
	start = f"{today()} 00:00:00"
	if nxt == "OUT" and last and str(last.time) < start:
		start = str(last.time)  # shift that began before midnight
	logs = frappe.get_all(
		"Employee Checkin",
		filters={"employee": emp.name, "time": [">=", start]},
		fields=["name", "log_type", "time"],
		order_by="time asc, creation asc",
	)
	return {
		"employee": emp.name,
		"employee_name": emp.employee_name,
		"store": emp.get(STORE_FIELD),
		"next": nxt,
		"clocked_in_since": str(last.time) if nxt == "OUT" and last else None,
		"worked_hours": _worked_hours(logs, now),
		"logs": [{"log_type": l.log_type, "time": str(l.time)} for l in logs],
	}


@frappe.whitelist(methods=["POST"])
def clock(log_type=None):
	"""Clock the signed-in user in or out. Only ever their own Employee record."""
	_require_hr()
	from hrms.hr.doctype.employee_checkin.employee_checkin import add_log_based_on_employee_field

	emp = _my_employee()
	if not emp:
		frappe.throw(_("No active Employee record is linked to your login. Ask the store owner."))
	now = now_datetime()
	expected, _last = _expected_next(emp.name, now)
	if log_type and log_type != expected:
		frappe.throw(
			_("You are already clocked {0}.").format(_("in") if expected == "OUT" else _("out")),
			title=_("Nothing to do"),
		)
	add_log_based_on_employee_field(
		emp.name,
		now,
		device_id=emp.get(STORE_FIELD) or "Store",
		log_type=expected,
		employee_fieldname="name",
	)
	return clock_status()


# --- Defaults from Retail Store Settings --------------------------------------------------

LEAVE_ANNUAL = "Annual Leave"
LEAVE_SICK = "Sick Leave"
OVERTIME_TYPE = "Retail Overtime"

# Components are looked up by these names. Amounts/formulas come from the settings only.
COMPONENTS = {
	"CSG (Employee)": "CSGE",
	"CSG (Employer)": "CSGR",
	"HRDC Levy (Employer)": "HRDC",
	"PRGF (Employer)": "PRGF",
	"PAYE": "PAYE",
	"Basic Salary": "BS",
	"End of Year Bonus": "EOYB",
	"Overtime": "OT",
}


def setup_hr_defaults(settings=None):
	"""Idempotently (re)write leave types, overtime type, payroll components and the PAYE slab from
	the settings. Safe to run on every migrate / settings save; skipped without hrms."""
	if "hrms" not in frappe.get_installed_apps():
		return
	settings = settings or frappe.get_single("Retail Store Settings")
	if not cint(settings.enable_hr):
		return
	_seed_leave_types(settings)
	_seed_payroll_components(settings)
	_seed_overtime_type(settings)
	_seed_paye_slab(settings)


def _ensure(doctype, name, values):
	"""Create doc `name` or update only the listed values."""
	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		changed = False
		for k, v in values.items():
			if doc.get(k) != v:
				doc.set(k, v)
				changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save()
		return doc
	doc = frappe.get_doc({"doctype": doctype, "__newname": name, **values})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def _seed_leave_types(settings):
	_ensure(
		"Leave Type",
		LEAVE_ANNUAL,
		{"leave_type_name": LEAVE_ANNUAL, "max_leaves_allowed": flt(settings.hr_annual_leave_days), "include_holiday": 0},
	)
	if flt(settings.hr_sick_leave_days) > 0:
		_ensure(
			"Leave Type",
			LEAVE_SICK,
			{"leave_type_name": LEAVE_SICK, "max_leaves_allowed": flt(settings.hr_sick_leave_days), "include_holiday": 0},
		)


def _num(value):
	"""A settings number as a short literal for a salary formula (1.5, not 1.500000)."""
	return f"{flt(value):g}"


def _seed_payroll_components(settings):
	csg = (
		f"base * ({_num(settings.csg_employee_rate_low)} if base <= {_num(settings.csg_salary_threshold)} "
		f"else {_num(settings.csg_employee_rate_high)}) / 100"
	)
	csg_employer = (
		f"base * ({_num(settings.csg_employer_rate_low)} if base <= {_num(settings.csg_salary_threshold)} "
		f"else {_num(settings.csg_employer_rate_high)}) / 100"
	)
	rows = [
		("Basic Salary", {"type": "Earning"}),
		("Overtime", {"type": "Earning"}),
		(
			"End of Year Bonus",
			{"type": "Earning", "description": "Paid through Additional Salary; see the End of Year Gratuity Act 2001."},
		),
		("CSG (Employee)", {"type": "Deduction", "amount_based_on_formula": 1, "formula": csg}),
		# Employer-side amounts are recorded for the payslip and reports but never reduce net pay.
		(
			"CSG (Employer)",
			{"type": "Deduction", "statistical_component": 1, "amount_based_on_formula": 1, "formula": csg_employer},
		),
		(
			"HRDC Levy (Employer)",
			{
				"type": "Deduction",
				"statistical_component": 1,
				"amount_based_on_formula": 1,
				"formula": f"base * {_num(settings.hrdc_rate)} / 100",
			},
		),
		(
			"PRGF (Employer)",
			{
				"type": "Deduction",
				"statistical_component": 1,
				"amount_based_on_formula": 1,
				"formula": f"base * {_num(settings.prgf_rate)} / 100",
			},
		),
		("PAYE", {"type": "Deduction", "variable_based_on_taxable_salary": 1}),
	]
	for name, values in rows:
		_ensure(
			"Salary Component",
			name,
			{"salary_component": name, "salary_component_abbr": COMPONENTS[name], **values},
		)


def _seed_overtime_type(settings):
	if not frappe.db.exists("DocType", "Overtime Type"):
		return
	if not frappe.db.exists("Overtime Type", OVERTIME_TYPE):
		# The hourly rate is derived from these components; owners can widen the list afterwards.
		doc = frappe.get_doc(
			{
				"doctype": "Overtime Type",
				"__newname": OVERTIME_TYPE,
				"overtime_salary_component": "Overtime",
				"standard_multiplier": flt(settings.hr_overtime_multiplier),
				"applicable_for_weekend": 1,
				"applicable_salary_component": [{"salary_component": "Basic Salary"}],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
	_ensure(
		"Overtime Type",
		OVERTIME_TYPE,
		{
			"overtime_salary_component": "Overtime",
			"standard_multiplier": flt(settings.hr_overtime_multiplier),
			"applicable_for_weekend": 1,
			"weekend_multiplier": flt(settings.hr_rest_day_multiplier),
			"applicable_for_public_holiday": 1,
			"public_holiday_multiplier": flt(settings.hr_rest_day_multiplier),
		},
	)


def _seed_paye_slab(settings):
	"""One submitted Income Tax Slab per set of bands. Changing a band in the settings adds a NEW
	slab (tax-year versioning is how HRMS works); older slabs stay for past payslips."""
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company or not settings.paye_effective_from:
		return
	bands = [
		(0, flt(settings.paye_band1_limit), flt(settings.paye_rate1)),
		(flt(settings.paye_band1_limit), flt(settings.paye_band2_limit), flt(settings.paye_rate2)),
		(flt(settings.paye_band2_limit), 0, flt(settings.paye_rate3)),
	]
	wanted = [(frm, to, pct) for frm, to, pct in bands]
	for name in frappe.get_all(
		"Income Tax Slab", filters={"docstatus": 1, "disabled": 0, "name": ["like", "Mauritius PAYE%"]}, pluck="name"
	):
		slab = frappe.get_doc("Income Tax Slab", name)
		have = [(flt(s.from_amount), flt(s.to_amount), flt(s.percent_deduction)) for s in slab.slabs]
		if str(slab.effective_from) == str(getdate(settings.paye_effective_from)) and have == wanted:
			return
	label = f"Mauritius PAYE {getdate(settings.paye_effective_from)}"
	if frappe.db.exists("Income Tax Slab", label):
		label = f"{label} ({frappe.utils.nowdate()})"
	doc = frappe.get_doc(
		{
			"doctype": "Income Tax Slab",
			"__newname": label,
			"effective_from": settings.paye_effective_from,
			"company": company,
			"currency": frappe.get_cached_value("Company", company, "default_currency"),
			"slabs": [{"from_amount": f, "to_amount": t, "percent_deduction": p} for f, t, p in wanted],
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
