"""Retail Store home page: the greeting block and the two number cards.

The workspace (workspace/retail_store/retail_store.json) links a Custom HTML Block and two Number Cards,
so they must exist BEFORE it syncs: ensure_home_records() runs from a pre-model-sync patch (existing sites),
before_install (new sites) and every migrate. It is idempotent and rewrites the block's script/style each
time, so editing this file is the way to change them.
"""

import frappe
from frappe.utils import cint

from retail_store.location import get_user_warehouses

GREETING_BLOCK = "Retail Store Greeting"
SALES_TODAY = "Sales today"
REQUESTS_WAITING = "Requests waiting"

GREETING_HTML = '<div class="rs-greeting"><div class="rs-greet-main">&nbsp;</div><div class="rs-greet-sub">&nbsp;</div></div>'
GREETING_STYLE = """
.rs-greeting{padding:6px 2px 14px}
.rs-greet-main{font-size:1.6rem;font-weight:600;line-height:1.25;color:var(--text-color)}
.rs-greet-sub{margin-top:2px;color:var(--text-muted);font-size:var(--text-md,14px)}
"""
GREETING_SCRIPT = """
frappe.call({ method: "retail_store.home.greeting" }).then((r) => {
	const g = r.message || {};
	const hour = new Date().getHours();
	const part = hour < 12 ? __("Good morning") : hour < 18 ? __("Good afternoon") : __("Good evening");
	const date = new Date().toLocaleDateString(frappe.boot.lang || undefined, { weekday: "long", day: "numeric", month: "long" });
	const root = root_element.querySelector ? root_element : root_element[0];
	root.querySelector(".rs-greet-main").textContent = g.first_name ? part + ", " + g.first_name : part;
	root.querySelector(".rs-greet-sub").textContent = [g.store, date].filter(Boolean).join(" \\u00b7 ");
});
"""

CARDS = [
	{
		"label": SALES_TODAY,
		"document_type": "Sales Invoice",
		"function": "Sum",
		"aggregate_function_based_on": "base_grand_total",
		"filters_json": '[["Sales Invoice","docstatus","=",1],["Sales Invoice","posting_date","Timespan","today"]]',
		"color": "#2e8b6f",
	},
	{
		"label": REQUESTS_WAITING,
		"document_type": "Material Request",
		"function": "Count",
		"filters_json": '[["Material Request","docstatus","=",0],["Material Request","workflow_state","=","Pending Approval"]]',
		"color": "#d9822b",
	},
]


def ensure_home_records():
	if not frappe.db.exists("DocType", "Custom HTML Block") or not frappe.db.exists("DocType", "Number Card"):
		return
	exists = frappe.db.exists("Custom HTML Block", GREETING_BLOCK)
	block = (
		frappe.get_doc("Custom HTML Block", GREETING_BLOCK)
		if exists
		else frappe.get_doc({"doctype": "Custom HTML Block", "name": GREETING_BLOCK, "private": 0})
	)
	block.update({"html": GREETING_HTML, "style": GREETING_STYLE, "script": GREETING_SCRIPT})
	block.flags.ignore_permissions = True
	block.save() if exists else block.insert()
	for spec in CARDS:
		exists = frappe.db.exists("Number Card", spec["label"])
		doc = (
			frappe.get_doc("Number Card", spec["label"])
			if exists
			else frappe.get_doc({"doctype": "Number Card", "type": "Document Type", "is_public": 1})
		)
		doc.update(spec)
		doc.show_percentage_stats = 0
		doc.flags.ignore_permissions = True
		doc.save() if exists else doc.insert()


def before_install():
	ensure_home_records()


@frappe.whitelist()
def greeting():
	"""First name, and where this person works (their own store(s), else the brand name)."""
	user = frappe.session.user
	first, full = frappe.db.get_value("User", user, ["first_name", "full_name"]) or ("", "")
	if first == "DEMO":  # the demo users are named "DEMO <Name>": greet by the name
		first = (full or "").removeprefix("DEMO ").split(" ")[0]
	warehouses = get_user_warehouses(user)
	if warehouses:
		names = []
		for w in warehouses:
			if cint(frappe.db.get_value("Warehouse", w, "is_group")):
				continue
			label = frappe.db.get_value("Warehouse", w, "warehouse_name") or w
			names.append(label.removeprefix("DEMO ").removeprefix("Store ").strip())
		store = ", ".join(names[:2])
	else:
		store = frappe.db.get_single_value("Retail Store Settings", "brand_name") or frappe.defaults.get_global_default("company")
	return {"first_name": (first or "").strip(), "store": store}
