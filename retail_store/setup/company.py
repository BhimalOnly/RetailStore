"""Company-dependent defaults: loyalty program, transfer warehouses, POS.

These need a Company, which only exists after the Setup Wizard, so they run
from the `setup_wizard_complete` hook and again (idempotently) on migrate.
"""

import frappe
from frappe.utils import add_days, nowdate

DEFAULT_PROGRAM = "Retail Rewards"


def get_default_company():
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def setup_company_defaults():
	company = get_default_company()
	if not company:
		return
	setup_selling_defaults(company)
	setup_transfer_warehouses(company)
	setup_loyalty_program(company)
	setup_pos_defaults()


RETAIL_CUSTOMER_GROUP = "Individual"
FALLBACK_TERRITORY = "Rest Of The World"


def default_territory(company):
	"""The company's own country as a leaf Territory (created under All Territories if ERPNext
	has none for it, e.g. Mauritius), else 'Rest Of The World'."""
	country = frappe.db.get_value("Company", company, "country")
	if country:
		if frappe.db.exists("Territory", {"name": country, "is_group": 0}):
			return country
		if not frappe.db.exists("Territory", country) and frappe.db.exists("Territory", "All Territories"):
			frappe.get_doc(
				{"doctype": "Territory", "territory_name": country, "parent_territory": "All Territories", "is_group": 0}
			).insert(ignore_permissions=True)
			return country
	return FALLBACK_TERRITORY if frappe.db.exists("Territory", FALLBACK_TERRITORY) else None


def setup_selling_defaults(company):
	"""Give every new Customer a Customer Group and Territory (ERPNext leaves both blank).

	Retail customers are individuals by default; territory is the company's country. Only blank
	settings are filled, so a client's own choice is never overwritten. Saved through the
	document (not set_single_value) because Selling Settings stores these as site defaults on
	validate, which is what ERPNext's Lead -> Customer conversion reads."""
	settings = frappe.get_single("Selling Settings")
	changed = False
	if not settings.customer_group and frappe.db.exists("Customer Group", {"name": RETAIL_CUSTOMER_GROUP, "is_group": 0}):
		settings.customer_group = RETAIL_CUSTOMER_GROUP
		changed = True
	if not settings.territory:
		territory = default_territory(company)
		if territory:
			settings.territory = territory
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()


def fill_customer_defaults(doc, method=None):
	"""Customer.before_validate: fill a blank Customer Group / Territory from Selling Settings.

	Covers conversions from a Lead/Opportunity/Prospect (ERPNext only fills the group, and only
	when its site default is set), POS quick-create and API-created customers."""
	if not doc.get("customer_group"):
		doc.customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or doc.get("customer_group")
	if not doc.get("territory"):
		doc.territory = frappe.db.get_single_value("Selling Settings", "territory") or doc.get("territory")


def setup_transfer_warehouses(company):
	settings = frappe.get_single("Retail Store Settings")
	if not settings.in_transit_warehouse:
		transit = frappe.db.get_value("Company", company, "default_in_transit_warehouse") or frappe.db.get_value(
			"Warehouse", {"company": company, "warehouse_type": "Transit", "is_group": 0}
		)
		if transit:
			# set_single_value: saving the doc would re-apply navigation/branding, not needed here
			frappe.db.set_single_value("Retail Store Settings", "in_transit_warehouse", transit)
	if not settings.main_warehouse:
		main = frappe.db.get_single_value("Stock Settings", "default_warehouse")
		if main:
			frappe.db.set_single_value("Retail Store Settings", "main_warehouse", main)


def _expense_account(company):
	filters = {"company": company, "root_type": "Expense", "is_group": 0, "disabled": 0}
	return frappe.db.get_value(
		"Account", {**filters, "account_name": ["like", "%Marketing%"]}
	) or frappe.db.get_value("Account", filters, order_by="lft")


def setup_loyalty_program(company):
	"""Default ON: 1 point per 100 of currency spent, 1 point = 1 currency unit, 1 year expiry.

	These numbers are placeholders to tune per client in the Loyalty Program form.
	"""
	settings = frappe.get_single("Retail Store Settings")
	if not settings.enable_loyalty:
		return

	name = settings.default_loyalty_program or (DEFAULT_PROGRAM if frappe.db.exists("Loyalty Program", DEFAULT_PROGRAM) else None)
	if not name:
		program = frappe.get_doc(
			{
				"doctype": "Loyalty Program",
				"loyalty_program_name": DEFAULT_PROGRAM,
				"loyalty_program_type": "Single Tier Program",
				"from_date": nowdate(),
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 1, "parent_customer_group": ""})
				or "All Customer Groups",
				"customer_territory": frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ""})
				or "All Territories",
				"auto_opt_in": 1,
				"collection_rules": [{"tier_name": "Standard", "min_spent": 0, "collection_factor": 100}],
				"conversion_factor": 1,
				"expiry_duration": 365,
				"company": company,
				"expense_account": _expense_account(company),
				"cost_center": frappe.db.get_value("Company", company, "cost_center"),
			}
		).insert(ignore_permissions=True)
		name = program.name

	if settings.default_loyalty_program != name:
		frappe.db.set_single_value("Retail Store Settings", "default_loyalty_program", name)


def apply_loyalty_toggle(settings):
	"""Turning loyalty off ends the program yesterday (history is kept); on re-opens it."""
	company = get_default_company()
	if settings.enable_loyalty and not settings.default_loyalty_program and company:
		setup_loyalty_program(company)
		return
	if not settings.default_loyalty_program:
		return
	program = frappe.get_doc("Loyalty Program", settings.default_loyalty_program)
	to_date = None if settings.enable_loyalty else add_days(nowdate(), -1)
	if str(program.to_date or "") != str(to_date or ""):
		program.to_date = to_date
		program.auto_opt_in = 1 if settings.enable_loyalty else 0
		program.save(ignore_permissions=True)


def setup_pos_defaults():
	# v16 POS can post Sales Invoices directly (stock + loyalty update at once).
	# Keep that default; high-volume clients can switch to POS Invoice in POS Settings.
	if frappe.db.exists("DocType", "POS Settings") and not frappe.db.get_single_value("POS Settings", "invoice_type"):
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")
