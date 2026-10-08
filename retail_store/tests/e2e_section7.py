"""End-to-end acceptance walk-through (spec section 7), over the real REST API
as each DEMO user, so permission hooks and workflow run exactly as in the UI.

Prereqs: site running (`bench start`) and demo data loaded.
Run:     env/bin/python apps/retail_store/retail_store/tests/e2e_section7.py [base_url]
"""

import json
import sys

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://retail.localhost:8001"
PASSWORD = "RetailDemo#2026"
ABBR = "DRC"
WH = {
	"main": f"DEMO Main Warehouse - {ABBR}",
	"downtown": f"DEMO Store Downtown - {ABBR}",
	"mall": f"DEMO Store Mall - {ABBR}",
	"airport": f"DEMO Store Airport - {ABBR}",
	"transit": f"Goods In Transit - {ABBR}",
}
ITEM = "DEMO-SNEAKER-41-BLAC"
ITEM2 = "DEMO-TEE-M-NAVY"
CUSTOMER = "DEMO Jane Shopper"

results = []


def check(name, ok, detail=""):
	results.append((name, bool(ok), detail))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


class Session:
	def __init__(self, user):
		self.user = user
		self.s = requests.Session()
		r = self.s.post(f"{BASE}/api/method/login", json={"usr": user, "pwd": PASSWORD})
		r.raise_for_status()

	def get(self, path, **params):
		return self.s.get(f"{BASE}{path}", params={k: json.dumps(v) if not isinstance(v, str) else v for k, v in params.items()})

	def post(self, path, data):
		return self.s.post(f"{BASE}{path}", json=data)

	def put(self, path, data):
		return self.s.put(f"{BASE}{path}", json=data)

	def list(self, doctype, fields=("name",), filters=None):
		r = self.get(f"/api/resource/{doctype}", fields=list(fields), filters=filters or [], limit_page_length=500)
		return r.json().get("data", []) if r.ok else None

	def doc(self, doctype, name):
		return self.get(f"/api/resource/{doctype}/{name}")

	def insert(self, doc):
		return self.post(f"/api/resource/{doc['doctype']}", doc)

	def call(self, method, **kwargs):
		return self.post(f"/api/method/{method}", kwargs)

	def submit(self, doc):
		return self.call("frappe.client.submit", doc=doc)

	def workflow(self, doc, action):
		return self.call("frappe.model.workflow.apply_workflow", doc=doc, action=action)


def err(r):
	try:
		j = r.json()
		return (j.get("exception") or j.get("_server_messages") or str(j))[:200]
	except Exception:
		return r.text[:200]


def qty(session, item, warehouse):
	rows = session.list("Bin", fields=["actual_qty"], filters=[["item_code", "=", item], ["warehouse", "=", warehouse]])
	return rows[0]["actual_qty"] if rows else 0


def u(local):
	return f"{local}@demo.example"


def pos_sale(sess, profile, warehouse, item, qty_=1, rate=2500):
	"""Open the till (if needed) and post a POS Sales Invoice, as the POS screen does in v16."""
	opening = sess.list("POS Opening Entry", filters=[["pos_profile", "=", profile], ["status", "=", "Open"], ["user", "=", sess.user]])
	if not opening:
		r = sess.insert(
			{
				"doctype": "POS Opening Entry",
				"pos_profile": profile,
				"user": sess.user,
				"company": "Demo Retail Co",
				"period_start_date": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 0}],
			}
		)
		if not r.ok:
			return r
		sess.submit(r.json()["data"])
	r = sess.insert(
		{
			"doctype": "Sales Invoice",
			"is_pos": 1,
			"pos_profile": profile,
			"customer": CUSTOMER,
			"company": "Demo Retail Co",
			"update_stock": 1,
			"set_warehouse": warehouse,
			"items": [{"item_code": item, "qty": qty_, "rate": rate, "warehouse": warehouse}],
			"payments": [{"mode_of_payment": "Cash", "amount": qty_ * rate}],
		}
	)
	if not r.ok:
		return r
	return sess.submit(r.json()["data"])


def main():
	admin = requests.Session()
	owner = Session(u("owner"))
	c_dt = Session(u("cashier.downtown"))
	c_mall = Session(u("cashier.mall"))
	floater = Session(u("floater"))
	m_dt = Session(u("manager.downtown"))
	whm = Session(u("wh.manager"))
	wha = Session(u("wh.attendant"))

	# ------------------------------------------------------------------ POS + loyalty
	print("\n== POS sale, stock deduction, loyalty ==")
	before = qty(owner, ITEM, WH["downtown"])
	lp_before = owner.list("Loyalty Point Entry", fields=["loyalty_points"], filters=[["customer", "=", CUSTOMER]]) or []
	r = pos_sale(c_dt, "DEMO POS Downtown", WH["downtown"], ITEM, 2, 2500)
	check("Cashier (Downtown) posts a POS sale", r.ok, err(r))
	sale_dt = r.json()["message"]["name"] if r.ok else None
	after = qty(owner, ITEM, WH["downtown"])
	check("Stock deducted at Downtown by 2", after == before - 2, f"{before} -> {after}")
	lp_after = owner.list("Loyalty Point Entry", fields=["loyalty_points", "loyalty_program"], filters=[["customer", "=", CUSTOMER]]) or []
	gained = sum(x["loyalty_points"] for x in lp_after) - sum(x["loyalty_points"] for x in lp_before)
	check("Loyalty points accrued (5000 spent / 100 = 50)", gained == 50, f"gained {gained}")
	cust = owner.doc("Customer", CUSTOMER).json()["data"]
	check("Customer auto-enrolled in Retail Rewards", cust.get("loyalty_program") == "Retail Rewards", cust.get("loyalty_program"))

	r = pos_sale(c_mall, "DEMO POS Mall", WH["mall"], ITEM2, 1, 800)
	check("Attendant+Cashier (Mall) posts a POS sale", r.ok, err(r))
	sale_mall = r.json()["message"]["name"] if r.ok else None
	r = pos_sale(floater, "DEMO POS Airport", WH["airport"], ITEM2, 1, 800)
	check("Rotating cashier posts a sale at Airport", r.ok, err(r))
	sale_airport = r.json()["message"]["name"] if r.ok else None

	# ------------------------------------------------------------------ location restriction
	print("\n== Location restriction ==")
	names = {x["name"] for x in c_dt.list("Sales Invoice") or []}
	check("Downtown cashier sees own Downtown invoice", sale_dt in names)
	check("Downtown cashier does NOT see Mall invoice in list", sale_mall not in names)
	r = c_dt.doc("Sales Invoice", sale_mall)
	check("Downtown cashier cannot open Mall invoice (403)", r.status_code == 403, r.status_code)
	r = c_dt.put(f"/api/resource/Sales Invoice/{sale_mall}", {"remarks": "x"})
	check("Downtown cashier cannot edit Mall invoice", not r.ok, r.status_code)

	names = {x["name"] for x in floater.list("Sales Invoice") or []}
	check("Rotating cashier sees Downtown invoice", sale_dt in names)
	check("Rotating cashier sees Airport invoice", sale_airport in names)
	check("Rotating cashier does NOT see Mall invoice", sale_mall not in names)

	r = c_dt.insert(
		{
			"doctype": "Sales Invoice",
			"customer": CUSTOMER,
			"company": "Demo Retail Co",
			"update_stock": 1,
			"set_warehouse": WH["mall"],
			"items": [{"item_code": ITEM, "qty": 1, "rate": 2500, "warehouse": WH["mall"]}],
		}
	)
	check("Downtown cashier cannot create an invoice on Mall stock", not r.ok, err(r))

	profiles = {x["name"] for x in c_dt.list("POS Profile") or []}
	check("Downtown cashier only sees Downtown POS Profile", profiles == {"DEMO POS Downtown"}, profiles)

	report_filters = {"company": "Demo Retail Co", "from_date": "2026-01-01", "to_date": "2027-03-31"}
	# v16: Stock Balance is a prepared report, so it is queued and read back like the UI does.
	r = c_dt.call("frappe.core.doctype.prepared_report.prepared_report.make_prepared_report", report_name="Stock Balance", filters=report_filters)
	check("Stock Balance report is NOT blocked for a restricted cashier", r.ok, err(r))
	wh_in_report = set()
	if r.ok:
		prepared = r.json()["message"]["name"]
		import time

		for _ in range(180):  # one worker may be busy with stock reposts
			st = c_dt.doc("Prepared Report", prepared).json().get("data", {}).get("status")
			if st in ("Completed", "Error"):
				break
			time.sleep(1)
		rr = c_dt.call("frappe.desk.query_report.run", report_name="Stock Balance", filters={**report_filters, "prepared_report_name": prepared})
		rows = (rr.json().get("message") or {}).get("result") or []
		wh_in_report = {row.get("warehouse") for row in rows if isinstance(row, dict)}
	check("Stock Balance shows company-wide stock (by design)", WH["mall"] in wh_in_report, sorted(wh_in_report))

	ses_dt = c_dt.list("Stock Entry")
	names = {x["name"] for x in ses_dt or []}
	r = c_dt.insert(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": "Demo Retail Co",
			"items": [{"item_code": ITEM, "qty": 1, "s_warehouse": WH["main"], "t_warehouse": WH["downtown"]}],
		}
	)
	check("Cashier cannot create a Stock Entry (role)", not r.ok, r.status_code)
	opening_names = {x["name"] for x in (c_mall.list("POS Opening Entry") or [])}
	dt_openings = {x["name"] for x in (owner.list("POS Opening Entry", filters=[["pos_profile", "=", "DEMO POS Downtown"]]) or [])}
	check("Mall cashier cannot see Downtown till openings", not (opening_names & dt_openings), opening_names & dt_openings)

	# ------------------------------------------------------------------ pattern (a)
	print("\n== Pattern (a): request -> approve -> dispatch -> receive ==")
	r = c_dt.insert(
		{
			"doctype": "Material Request",
			"material_request_type": "Material Transfer",
			"company": "Demo Retail Co",
			"schedule_date": "2026-12-31",
			"set_warehouse": WH["downtown"],
			"items": [
				{"item_code": ITEM, "qty": 4, "warehouse": WH["downtown"], "schedule_date": "2026-12-31"},
				{"item_code": ITEM2, "qty": 3, "warehouse": WH["downtown"], "schedule_date": "2026-12-31"},
			],
		}
	)
	check("Cashier creates a Material Request for own store", r.ok, err(r))
	mr = r.json()["data"]
	check("Source defaults to Main warehouse", mr.get("set_from_warehouse") == WH["main"], mr.get("set_from_warehouse"))
	check("MR starts in Draft", mr.get("workflow_state") == "Draft", mr.get("workflow_state"))

	r = c_dt.insert(
		{
			"doctype": "Material Request",
			"material_request_type": "Material Transfer",
			"company": "Demo Retail Co",
			"schedule_date": "2026-12-31",
			"items": [{"item_code": ITEM, "qty": 1, "warehouse": WH["mall"], "schedule_date": "2026-12-31"}],
		}
	)
	check("Cashier cannot request stock for another store", not r.ok, err(r))

	r = c_dt.submit(mr)
	check("Cashier cannot submit (approve) directly", not r.ok, r.status_code)
	r = c_dt.workflow(mr, "Submit for Approval")
	check("Cashier sends MR for approval", r.ok, err(r))
	mr = r.json()["message"] if r.ok else mr
	r = c_dt.workflow(mr, "Approve")
	check("Cashier cannot approve own request", not r.ok, r.status_code)

	check("Mall cashier cannot see Downtown's request", mr["name"] not in {x["name"] for x in c_mall.list("Material Request") or []})
	check("Warehouse Manager (Main) sees the request (source = Main)", mr["name"] in {x["name"] for x in whm.list("Material Request") or []})
	check("Store Manager (Downtown) sees the request", mr["name"] in {x["name"] for x in m_dt.list("Material Request") or []})

	r = whm.workflow(mr, "Approve")
	check("Warehouse Manager approves", r.ok, err(r))
	mr = r.json()["message"] if r.ok else mr
	check("MR approved & submitted", mr.get("workflow_state") == "Approved" and mr.get("docstatus") == 1, (mr.get("workflow_state"), mr.get("docstatus")))

	main_before = qty(owner, ITEM, WH["main"])
	dt_before = qty(owner, ITEM, WH["downtown"])
	r = whm.call(
		"erpnext.stock.doctype.material_request.material_request.make_in_transit_stock_entry",
		source_name=mr["name"],
		in_transit_warehouse=WH["transit"],
	)
	check("Warehouse Manager makes dispatch (In-Transit) entry from MR", r.ok, err(r))
	if r.ok:
		ste = r.json()["message"]
		r = whm.insert(ste)
		check("Dispatch entry saved", r.ok, err(r))
		r = whm.submit(r.json()["data"]) if r.ok else r
		check("Dispatch submitted (Main -> In-Transit)", r.ok, err(r))
		dispatch = r.json()["message"] if r.ok else {}
		check("Main stock reduced by 4", qty(owner, ITEM, WH["main"]) == main_before - 4)
		check("Downtown stock unchanged until received", qty(owner, ITEM, WH["downtown"]) == dt_before)
		check("Wh attendant cannot create stock entries", not wha.insert({**ste, "items": ste["items"]}).ok)

		names = {x["name"] for x in m_dt.list("Stock Entry") or []}
		check("Downtown manager sees the in-transit dispatch", dispatch.get("name") in names)
		check("Mall cashier cannot see it", dispatch.get("name") not in {x["name"] for x in c_mall.list("Stock Entry") or []})
		r = c_dt.call("erpnext.stock.doctype.stock_entry.stock_entry.make_stock_in_entry", source_name=dispatch.get("name"))
		receipt = r.json().get("message") if r.ok else None
		r2 = c_dt.insert(receipt) if receipt else r
		check("Cashier cannot confirm receipt (role)", not r2.ok, r2.status_code)

		r = m_dt.call("erpnext.stock.doctype.stock_entry.stock_entry.make_stock_in_entry", source_name=dispatch.get("name"))
		check("Downtown manager makes 'End Transit' receipt", r.ok, err(r))
		receipt = r.json()["message"]
		check("Receipt targets Downtown", all(i.get("t_warehouse") == WH["downtown"] for i in receipt["items"]), [i.get("t_warehouse") for i in receipt["items"]])
		r = m_dt.insert(receipt)
		r = m_dt.submit(r.json()["data"]) if r.ok else r
		check("Downtown manager confirms receipt", r.ok, err(r))
		check("Downtown stock +4 after receipt", qty(owner, ITEM, WH["downtown"]) == dt_before + 4)
		mr_after = owner.doc("Material Request", mr["name"]).json()["data"]
		# v16 tracks transfers in status/transfer_status (no per_transferred field)
		check(
			"MR shows Transferred / Completed",
			mr_after.get("status") == "Transferred" and mr_after.get("transfer_status") == "Completed",
			(mr_after.get("status"), mr_after.get("transfer_status")),
		)

	# ------------------------------------------------------------------ pattern (b)
	print("\n== Pattern (b): owner bulk transfer, no request ==")
	# top up Main so repeated runs don't drain the demo stock
	for code, need in ((ITEM2, 10), (ITEM, 2)):
		short = need - qty(owner, code, WH["main"])
		if short > 0:
			r = owner.insert(
				{
					"doctype": "Stock Entry",
					"stock_entry_type": "Material Receipt",
					"company": "Demo Retail Co",
					"remarks": "DEMO test top-up",
					"items": [{"item_code": code, "qty": short + 10, "t_warehouse": WH["main"], "basic_rate": 100}],
				}
			)
			owner.submit(r.json()["data"])
	mall_before = qty(owner, ITEM2, WH["mall"])
	airport_before = qty(owner, ITEM2, WH["airport"])
	r = owner.insert(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": "Demo Retail Co",
			"items": [
				{"item_code": ITEM2, "qty": 5, "s_warehouse": WH["main"], "t_warehouse": WH["mall"]},
				{"item_code": ITEM2, "qty": 5, "s_warehouse": WH["main"], "t_warehouse": WH["airport"]},
			],
		}
	)
	r = owner.submit(r.json()["data"]) if r.ok else r
	check("Owner direct bulk transfer to two stores", r.ok, err(r))
	check("Mall +5 / Airport +5", qty(owner, ITEM2, WH["mall"]) == mall_before + 5 and qty(owner, ITEM2, WH["airport"]) == airport_before + 5)

	r = owner.insert(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Transfer",
			"company": "Demo Retail Co",
			"add_to_transit": 1,
			"rs_final_destination": WH["mall"],
			"items": [{"item_code": ITEM, "qty": 2, "s_warehouse": WH["main"], "t_warehouse": WH["transit"]}],
		}
	)
	r = owner.submit(r.json()["data"]) if r.ok else r
	check("Owner dispatches via In-Transit with Final Destination = Mall", r.ok, err(r))
	if r.ok:
		d = r.json()["message"]
		check("Mall cashier can see the incoming transfer", d["name"] in {x["name"] for x in c_mall.list("Stock Entry") or []})
		rr = owner.call("erpnext.stock.doctype.stock_entry.stock_entry.make_stock_in_entry", source_name=d["name"])
		rec = rr.json()["message"]
		rr = owner.insert(rec)
		saved = rr.json().get("data", {}) if rr.ok else {}
		check("End Transit auto-targets the Final Destination", rr.ok and all(i["t_warehouse"] == WH["mall"] for i in saved.get("items", [])), err(rr))


	# ------------------------------------------------------------------ POS variant grouping
	print("\n== POS: one card per product + variant picker ==")

	def pos_items(sess, profile, term=""):
		r = sess.call(
			"erpnext.selling.page.point_of_sale.point_of_sale.get_items",
			start=0,
			page_length=40,
			price_list="Standard Selling",
			item_group="All Item Groups",
			pos_profile=profile,
			search_term=term,
		)
		return r.json()["message"]["items"] if r.ok else None

	cards = {i["item_code"]: i for i in pos_items(c_dt, "DEMO POS Downtown") or []}
	check("POS lists one card per template", {"DEMO-SNEAKER", "DEMO-TEE"} <= set(cards), sorted(cards))
	check("No individual variant cards", not any(c.startswith(("DEMO-SNEAKER-", "DEMO-TEE-")) for c in cards), sorted(cards))
	check("Plain item still listed (mixed catalogue)", "DEMO-TOTE" in cards and not cards["DEMO-TOTE"].get("rs_is_template"))
	sn = cards.get("DEMO-SNEAKER", {})
	check("Template card: 6 options, price 2500-2700", sn.get("rs_variant_count") == 6 and sn.get("price_list_rate") == 2500 and sn.get("rs_price_max") == 2700, sn)
	expected_stock = sum(qty(owner, f"DEMO-SNEAKER-{z}-{c}", WH["downtown"]) for z in (40, 41, 42) for c in ("BLAC", "WHIT"))
	check("Template card stock = sum of its variants at this store", sn.get("actual_qty") == expected_stock, (sn.get("actual_qty"), expected_stock))

	found = [i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown", "sneaker") or []]
	check("Name search returns the product card", found == ["DEMO-SNEAKER"], found)
	found = [i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown", "navy") or []]
	check("Search on a variant value finds its product", found == ["DEMO-TEE"], found)

	r = owner.doc("Item", "DEMO-SNEAKER-42-WHIT")
	barcode = (r.json()["data"].get("barcodes") or [{}])[0].get("barcode") if r.ok else None
	found = [i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown", barcode) or []] if barcode else []
	check("Barcode scan bypasses grouping (exact variant)", found == ["DEMO-SNEAKER-42-WHIT"], (barcode, found))
	found = [i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown", "DEMO-TEE-M-NAVY") or []]
	check("Exact variant code bypasses grouping", found == ["DEMO-TEE-M-NAVY"], found)

	r = c_dt.call("retail_store.pos_variants.get_variant_options", template="DEMO-SNEAKER", pos_profile="DEMO POS Downtown")
	opts = r.json().get("message") if r.ok else {}
	check("Picker offers Size then Colour", opts.get("attributes") == ["DEMO Shoe Size", "DEMO Colour"], opts.get("attributes"))
	check("Picker offers only this product's values", opts.get("options") == {"DEMO Shoe Size": ["40", "41", "42"], "DEMO Colour": ["Black", "White"]}, opts.get("options"))
	v42 = next((v for v in opts.get("variants", []) if v["attributes"] == {"DEMO Shoe Size": "42", "DEMO Colour": "White"}), {})
	check("Picker resolves 42/White to the right variant, price and stock", v42.get("item_code") == "DEMO-SNEAKER-42-WHIT" and v42.get("rate") == 2700 and v42.get("actual_qty") == qty(owner, "DEMO-SNEAKER-42-WHIT", WH["downtown"]), v42)
	r = c_dt.call("retail_store.pos_variants.get_variant_options", template="DEMO-SNEAKER", pos_profile="DEMO POS Mall")
	check("Picker refuses another store's till", r.status_code == 403, r.status_code)

	before = qty(owner, "DEMO-SNEAKER-42-WHIT", WH["downtown"])
	r = pos_sale(c_dt, "DEMO POS Downtown", WH["downtown"], v42.get("item_code", "DEMO-SNEAKER-42-WHIT"), 1, v42.get("rate") or 2700)
	check("Picked variant sells through normal POS flow", r.ok, err(r))
	check("Picked variant's stock deducted", qty(owner, "DEMO-SNEAKER-42-WHIT", WH["downtown"]) == before - 1)

	r = owner.put("/api/resource/Retail Store Settings/Retail Store Settings", {"group_variants_in_pos": 0})
	codes = {i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown") or []}
	check("Toggle off: stock ERPNext list (one card per variant)", r.ok and "DEMO-SNEAKER-40-BLAC" in codes and "DEMO-SNEAKER" not in codes, sorted(codes))
	owner.put("/api/resource/Retail Store Settings/Retail Store Settings", {"group_variants_in_pos": 1})
	codes = {i["item_code"] for i in pos_items(c_dt, "DEMO POS Downtown") or []}
	check("Toggle back on: grouped again", "DEMO-SNEAKER" in codes)

	# ------------------------------------------------------------------ summary
	failed = [r for r in results if not r[1]]
	print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
	for name, _, detail in failed:
		print("  FAILED:", name, detail)
	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main())
