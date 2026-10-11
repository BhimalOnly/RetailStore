# Copyright (c) 2026, bhimall and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from retail_store.location import clear_location_permissions, sync_location_permissions


class RetailStaffAccess(Document):
	def validate(self):
		seen = set()
		for row in self.locations:
			if row.warehouse in seen:
				frappe.throw(_("Row {0}: Warehouse {1} is listed twice").format(row.idx, row.warehouse))
			seen.add(row.warehouse)

		defaults = [row for row in self.locations if row.is_default]
		if len(defaults) > 1:
			frappe.throw(_("Only one location can be the default"))
		if self.locations and not defaults:
			self.locations[0].is_default = 1

	def on_update(self):
		from retail_store.setup.capabilities import apply_module_profile

		sync_location_permissions(self)
		apply_module_profile(self.user)
		from retail_store.hr import sync_employees_for_user

		sync_employees_for_user(self.user)

	def on_trash(self):
		clear_location_permissions(self.user)
