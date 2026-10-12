"""Install / migrate entry points. Every step is idempotent, so `bench migrate`
re-applies the baseline on existing client sites without duplicating anything."""

import click
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from retail_store.permissions import FINAL_DESTINATION

CUSTOM_FIELDS = {
	"Stock Entry": [
		{
			"fieldname": FINAL_DESTINATION,
			"fieldtype": "Link",
			"label": "Final Destination",
			"options": "Warehouse",
			"insert_after": "to_warehouse",
			"depends_on": "eval:doc.add_to_transit || doc.outgoing_stock_entry",
			"description": "Store that will receive goods sent via In-Transit. Lets the receiving store see and confirm the transfer.",
			"module": "Retail Store",
		}
	],
	"Employee": [
		{
			"fieldname": "custom_store_warehouse",
			"fieldtype": "Link",
			"label": "Store / Location",
			"options": "Warehouse",
			"insert_after": "company",
			"in_list_view": 0,
			"in_standard_filter": 1,
			"description": "Where this person works. Follows Retail Staff Access when the employee has a login.",
			"module": "Retail Store",
		}
	],
}


SITE_TIME_ZONE = "Indian/Mauritius"


def set_site_time_zone():
	"""Every client is Mauritius-based; don't leave it to the setup wizard's picker. Not run on
	migrate, so a deliberate override in System Settings sticks."""
	frappe.db.set_single_value("System Settings", "time_zone", SITE_TIME_ZONE)


def after_install():
	run_setup()
	set_site_time_zone()
	click.secho("Retail Store installed. Configure it at /desk/retail-store-settings", fg="green")


def after_migrate():
	run_setup()


def after_setup_wizard(args=None):
	from retail_store.setup.company import setup_company_defaults

	setup_company_defaults()
	set_site_time_zone()  # the wizard writes its own choice after install


def run_setup():
	from retail_store.setup.capabilities import apply_capabilities
	from retail_store.setup.company import setup_company_defaults
	from retail_store.setup.roles import setup_roles_and_permissions
	from retail_store.setup.workflow import setup_material_request_workflow

	from retail_store.home import ensure_home_records

	ensure_home_records()
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	ensure_single_defaults()
	activate_retail_domain()
	setup_roles_and_permissions()
	setup_material_request_workflow()
	apply_capabilities()
	lock_user_themes()
	setup_company_defaults()
	from retail_store.hr import backfill_employee_stores

	backfill_employee_stores()
	frappe.clear_cache()


def lock_user_themes():
	"""One brand identity per site: the theme's per-user "Theme profile" picker is off (branding is
	a System Manager decision, Task #7), and any profile a user picked while it was on is dropped.
	Light/dark, density and font size stay personal. Runs on every migrate, like the settings it guards."""
	if not frappe.db.exists("DocType", "Theme Settings"):
		return
	frappe.db.set_single_value("Theme Settings", "allow_user_theme", 0)
	if frappe.db.exists("DocType", "Theme Preference"):
		frappe.db.delete("Theme Preference")
	enable_today_view()


def enable_today_view():
	"""System Manager keeps the theme's own "Today's View" (its toolbar link); retail_store.js hides the
	link and landing.js / getpage close the page for everyone else. The theme reads the switch from its
	stored studio config as well as the field, so both are set (a per-user profile used to mask this)."""
	import json

	frappe.db.set_single_value("Theme Settings", "enable_smart_home", 1)
	raw = frappe.db.get_single_value("Theme Settings", "theme_studio_config")
	try:
		config = json.loads(raw) if raw else None
	except ValueError:
		config = None
	if isinstance(config, dict) and config.get("enable_smart_home") is not True:
		config["enable_smart_home"] = True
		frappe.db.set_single_value("Theme Settings", "theme_studio_config", json.dumps(config, indent=1, sort_keys=True))


def ensure_single_defaults():
	"""v16 returns 0 (not None) for a never-saved Check on a Single, so a setting
	added in a later release would silently read as off. Write the declared
	default for any Retail Store Settings field that has no stored value yet."""
	doctype = "Retail Store Settings"
	stored = {r[0] for r in frappe.db.sql("select field from `tabSingles` where doctype = %s", doctype)}
	for df in frappe.get_meta(doctype).fields:
		if df.default is not None and df.fieldtype not in ("Section Break", "Column Break", "Tab Break") and df.fieldname not in stored:
			frappe.db.set_single_value(doctype, df.fieldname, df.default)


def activate_retail_domain():
	"""ERPNext v16 restricts the Point of Sale page to the "Retail" domain: without it,
	POS is missing from non-admin sidebars even when the role may open it."""
	if not frappe.db.exists("Domain", "Retail"):
		return
	if "Retail" not in frappe.get_active_domains():
		frappe.get_single("Domain Settings").set_active_domains(["Retail"])
		frappe.cache.delete_value("domain_restricted_pages")


def before_uninstall():
	from retail_store.setup.workflow import WORKFLOW_NAME

	if frappe.db.exists("Workflow", WORKFLOW_NAME):
		frappe.delete_doc("Workflow", WORKFLOW_NAME, ignore_permissions=True, force=True)


def before_tests():
	frappe.clear_cache()
