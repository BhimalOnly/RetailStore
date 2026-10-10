"""Which doctypes linked from a capability's main doctypes can a given user NOT read?

A form can fail to save with a 403 on a harmless lookup table (e.g. Opportunity Type) when the
role was granted the main doctypes but not the masters they link to. This walks every Link
field (and child-table Link fields) of the capability's doctypes and reports the gaps.

    bench --site retail.localhost execute retail_store.tests.capability_links.report \
        --kwargs '{"capability": "enable_crm", "user": "owner@demo.example"}'
"""
import frappe

from retail_store.setup.capabilities import OPTIONAL


def linked_doctypes(doctypes):
	need = {}
	seen = set()

	def walk(dt):
		for f in frappe.get_meta(dt).fields:
			if f.fieldtype == "Link" and f.options:
				need.setdefault(f.options, set()).add(dt)
			elif f.fieldtype in ("Table", "Table MultiSelect") and f.options and f.options not in seen:
				seen.add(f.options)
				walk(f.options)

	for dt in doctypes:
		walk(dt)
	return need


def missing(capability, user):
	grants = list(OPTIONAL[capability]["grants"])
	missing = {}
	for target, sources in sorted(linked_doctypes(grants).items()):
		if not frappe.db.exists("DocType", target) or frappe.get_meta(target).istable or target in grants:
			continue
		# Links to "DocType" itself (e.g. Opportunity.opportunity_from) are resolved by Frappe's own
		# link/doctype pickers; no non-admin role has `read` on DocType, so flagging it is pure noise.
		if target == "DocType":
			continue
		if not (frappe.has_permission(target, "read", user=user) or frappe.has_permission(target, "select", user=user)):
			missing[target] = sorted(sources)
	return missing


def report(capability="enable_crm", user="owner@demo.example"):
	gaps = missing(capability, user)
	print(f"{capability} / {user}: {len(gaps)} linked doctype(s) not readable")
	for target, sources in gaps.items():
		print(f"  {target}  <- {', '.join(sources)}")
	return gaps
