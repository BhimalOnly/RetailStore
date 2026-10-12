"""Server-side helpers for tests/browser_pos_shift.py.

    bench --site retail.localhost execute retail_store.tests.pos_shift_setup.make_stale   # Downtown till opened yesterday
    bench --site retail.localhost execute retail_store.tests.pos_shift_setup.ensure_open  # every DEMO till has an open shift
"""

import frappe
from frappe.utils import add_days, now_datetime, today

TILLS = {"DEMO POS Downtown": "cashier.downtown@demo.example", "DEMO POS Mall": "cashier.mall@demo.example", "DEMO POS Airport": "floater@demo.example"}


def make_stale():
	name = frappe.db.get_value(
		"POS Opening Entry", {"pos_profile": "DEMO POS Downtown", "status": "Open", "docstatus": 1}, "name", order_by="creation desc"
	)
	frappe.db.set_value("POS Opening Entry", name, "period_start_date", add_days(now_datetime(), -1), update_modified=False)
	frappe.db.commit()
	print("stale:", name)


def ensure_open():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	for profile, user in TILLS.items():
		if frappe.db.exists("POS Opening Entry", {"pos_profile": profile, "status": "Open", "docstatus": 1}):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"pos_profile": profile,
				"user": user,
				"company": company,
				"period_start_date": now_datetime(),
				"posting_date": today(),
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 0}],
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		print("opened:", profile, doc.name)
	frappe.db.commit()
