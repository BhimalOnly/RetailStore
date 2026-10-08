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
}


def after_install():
	run_setup()
	click.secho("Retail Store installed. Configure it at /desk/retail-store-settings", fg="green")


def after_migrate():
	run_setup()


def after_setup_wizard(args=None):
	from retail_store.setup.company import setup_company_defaults

	setup_company_defaults()


def run_setup():
	from retail_store.setup.capabilities import apply_capabilities
	from retail_store.setup.company import setup_company_defaults
	from retail_store.setup.roles import setup_roles_and_permissions
	from retail_store.setup.workflow import setup_material_request_workflow

	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	ensure_single_defaults()
	activate_retail_domain()
	setup_roles_and_permissions()
	setup_material_request_workflow()
	apply_capabilities()
	setup_company_defaults()
	frappe.clear_cache()


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
