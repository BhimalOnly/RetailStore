# Copyright (c) 2026, bhimall and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Optional capabilities that live in a separate app rather than in ERPNext.
REQUIRES_APP = {
	"enable_ecommerce": ("webshop", "bench get-app webshop --branch version-16"),
	"enable_hr": ("hrms", "bench get-app hrms --branch version-16"),
}


class RetailStoreSettings(Document):
	def validate(self):
		from retail_store.staff_grants import validate_settings

		validate_settings(self)
		installed = frappe.get_installed_apps()
		for field, (app, get_cmd) in REQUIRES_APP.items():
			if self.get(field) and app not in installed:
				frappe.throw(
					_(
						"{0} needs the <b>{1}</b> app. Install it first:<br><code>{2}</code><br><code>bench --site {3} install-app {1}</code>"
					).format(self.meta.get_label(field), app, get_cmd, frappe.local.site),
					title=_("App not installed"),
				)

	def on_update(self):
		from retail_store.branding import apply_branding
		from retail_store.setup.capabilities import apply_capabilities
		from retail_store.setup.company import apply_loyalty_toggle
		from retail_store.setup.workflow import apply_workflow_toggle

		apply_capabilities(self)
		apply_branding(self)
		apply_loyalty_toggle(self)
		apply_workflow_toggle(self)
		from retail_store.staff_grants import sync_grant_roles

		sync_grant_roles(self)
		frappe.clear_cache()


def get_settings():
	return frappe.get_cached_doc("Retail Store Settings")
