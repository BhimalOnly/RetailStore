"""Remove what browser_form_flows.py created (it records every document in flow_docs.json).

Run:  bench --site retail.localhost execute retail_store.tests.purge_form_flows.run --kwargs "{'path': '/abs/path/flow_docs.json'}"

Only the documents named in that file are touched, newest first so a document goes before what it points at; anything submitted is
cancelled first (which reverses its stock and ledger entries). Refuses a file older than a day or a document that is not recent.

Deleting a CANCELLED voucher leaves its cancelled GL / Stock / Payment Ledger rows behind (ERPNext keeps them), and a later document
that reuses the name then looks "linked" to them (it blocked a Payment Entry delete). So the rows of each voucher this tool itself
cancelled are removed with it: they are reversed pairs, so no balance changes. The normal delete runs (frappe.delete_doc with
for_reload would skip on_trash and the link clean-up).
"""
import json
import os
import time

import frappe
from frappe.utils import add_to_date, now_datetime


def run(path):
	if time.time() - os.path.getmtime(path) > 86400:
		print("the record file is older than a day: refusing")
		return
	listed = json.load(open(path))
	seen, docs = set(), []
	for dt, name in listed:
		if (dt, name) not in seen:
			seen.add((dt, name))
			docs.append((dt, name))
	frappe.set_user("Administrator")
	cutoff = add_to_date(now_datetime(), days=-1)
	gone, kept = [], []
	for dt, name in reversed(docs):
		if not frappe.db.exists(dt, name):
			continue
		doc = frappe.get_doc(dt, name)
		if doc.creation < cutoff:
			kept.append((dt, name, "older than a day"))
			continue
		try:
			was_submitted = getattr(doc, "docstatus", 0) == 1
			if was_submitted:
				doc.cancel()
			frappe.delete_doc(dt, name, force=True)
			if was_submitted:  # the reversed pairs of a voucher we cancelled ourselves: nothing live in them
				for table, flag in (("GL Entry", "is_cancelled"), ("Stock Ledger Entry", "is_cancelled"), ("Payment Ledger Entry", "delinked")):
					if frappe.db.has_table(table) and not frappe.db.exists(table, {"voucher_type": dt, "voucher_no": name, flag: 0}):
						frappe.db.delete(table, {"voucher_type": dt, "voucher_no": name})
			gone.append((dt, name))
		except Exception as e:
			kept.append((dt, name, str(e)[:120]))
	frappe.db.commit()
	print(f"removed {len(gone)}; left {len(kept)}")
	for k in kept:
		print("   left:", k)
