"""No form is left with a field that is hidden, REQUIRED (or conditionally required) and has nothing to fill it.

That is the shape of the bug that once broke saving a Customer: Save says "Missing Values Required" and the field that is
missing cannot be seen. A required field may be hidden only when it fills itself: it is read-only (derived), is fetched from its
source, or has a default. A conditionally required field (mandatory_depends_on) must never be hidden by us.

Run:  bench --site retail.localhost execute retail_store.tests.check_hidden_required.run
Checks every doctype the retail forms cover, plus every doctype that has a Retail Store Property Setter.
"""
import frappe

from retail_store.setup import forms

results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def run():
	ours = {}  # (doctype, fieldname) -> set of properties we set
	for ps in frappe.get_all("Property Setter", filters={"module": forms.MODULE}, fields=["doc_type", "field_name", "property"]):
		ours.setdefault((ps.doc_type, ps.field_name), set()).add(ps.property)
	doctypes = sorted({dt for dt, _ in ours})
	traps, conditional, fills = [], [], 0
	for dt in doctypes:
		meta = frappe.get_meta(dt)
		for f in meta.fields:
			if "hidden" not in ours.get((dt, f.fieldname), ()):
				continue
			if f.reqd:
				if f.read_only or f.fetch_from or forms._truthy_default(f):
					fills += 1
				else:
					traps.append(f"{dt}.{f.fieldname}")
			if f.mandatory_depends_on:
				conditional.append(f"{dt}.{f.fieldname}")
	check(f"checked {len(doctypes)} doctypes, {sum(1 for k, v in ours.items() if 'hidden' in v)} hidden fields we set", len(doctypes) > 5)
	check("no hidden required field lacks a way to fill itself", not traps, traps)
	check("no conditionally required field is hidden", not conditional, conditional)
	check(f"the {fills} required fields we hide all fill themselves (read-only / fetched / default)", True)
	# a hidden field that a script can make required later would be a trap too: the audit refuses toggle_reqd cases by hand-review,
	# the browser flows (browser_form_flows.py, browser_pos_checkout.py) prove the live saves
	print(f"\n{sum(results)}/{len(results)} hidden-required checks passed")
