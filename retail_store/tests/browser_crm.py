"""Browser check of the CRM capability: Lead -> Opportunity -> Customer as Store Owner, and that
no other retail role can see or reach CRM.

Needs the CRM toggle ON (Retail Store Settings > Capabilities, System Manager) and Playwright, see
browser_pos.py for setup. Creates one Lead/Opportunity/Customer and deletes them again (as
Administrator, over REST) unless --keep is passed.

Run:  /tmp/pw/bin/python browser_crm.py [--keep]
Exits 1 on any failed check. Screenshots land in ./shots/.
"""
import json
import os
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots"
PASSWORD = "RetailDemo#2026"
KEEP = "--keep" in sys.argv
os.makedirs(OUT, exist_ok=True)

results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def wait_form(page, doctype, name=None):
	cond = f"window.cur_frm&&cur_frm.doctype=='{doctype}'" + (f"&&cur_frm.doc.name=='{name}'" if name else "")
	page.wait_for_function(cond, timeout=30000)
	page.wait_for_timeout(1800)


def create_menu(page, item):
	"""Open the visible toolbar's Create menu and pick `item`. Frappe keeps the previous form's
	toolbar in the DOM (hidden), so always scope to the visible group."""
	page.locator('.inner-group-button[data-label="Create"] button:visible').first.click()
	page.wait_for_timeout(600)
	page.evaluate(
		"""t=>{const g=[...document.querySelectorAll('.inner-group-button[data-label="Create"]')].find(e=>e.offsetParent!==null);
		g.querySelector(`a.dropdown-item[data-label="${t}"]`).click()}""",
		item,
	)
	page.wait_for_timeout(3500)


def dialog(page):
	d = page.locator(".modal.show")
	return d.inner_text().replace("\n", " | ")[:200] if d.count() else None


def login(ctx, user, pwd=PASSWORD):
	ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": pwd})


with sync_playwright() as p:
	br = p.chromium.launch()
	ctx = br.new_context(viewport={"width": 1440, "height": 1000})
	page = ctx.new_page()
	bad = []
	page.on("pageerror", lambda e: bad.append(str(e)[:120]))
	page.on("response", lambda r: bad.append(f"{r.status} {r.url.split('/api/')[-1][:70]}") if r.status in (403, 500) else None)
	login(ctx, "owner@demo.example")

	# 1. Lead
	page.goto(B + "/desk/lead/new")
	wait_form(page, "Lead")
	for field, value in [("first_name", "Zed"), ("last_name", "Crmtest"), ("email_id", "zed.crmtest@example.mu"), ("company_name", "Zed Crmtest Shoes")]:
		page.locator(f'[data-fieldname="{field}"] input').first.fill(value)
	page.keyboard.press("Control+s")
	page.wait_for_timeout(4000)
	lead = page.evaluate("cur_frm.doc.name")
	check("Owner creates a Lead", lead.startswith("CRM-LEAD-") and not page.evaluate("!!cur_frm.doc.__islocal"), lead)
	page.screenshot(path=f"{OUT}/crm-1-lead.png")

	# 2. Lead -> Opportunity
	create_menu(page, "Opportunity")
	# ERPNext first asks whether to also create a Prospect for the Lead's company (checked by default)
	check("Create Opportunity dialog offers 'Create Prospect'", "Create Prospect" in (dialog(page) or ""), dialog(page))
	page.screenshot(path=f"{OUT}/crm-1b-create-opportunity-dialog.png")
	page.locator(".modal.show .btn-primary:visible, .modal.show .btn-modal-primary:visible").first.click()
	wait_form(page, "Opportunity")
	check("Lead -> Opportunity prefills the Lead", page.evaluate("cur_frm.doc.party_name") == lead, page.evaluate("cur_frm.doc.party_name"))
	page.keyboard.press("Control+s")
	page.wait_for_timeout(4500)
	opp = page.evaluate("cur_frm.doc.name")
	check("Owner saves the Opportunity (no 403 on lookups)", opp.startswith("CRM-OPP-") and not dialog(page), (opp, dialog(page)))
	page.screenshot(path=f"{OUT}/crm-2-opportunity.png")

	# 3. Opportunity -> Customer
	create_menu(page, "Customer")
	wait_form(page, "Customer")
	page.keyboard.press("Control+s")
	page.wait_for_timeout(4500)
	customer = page.evaluate("cur_frm.doc.name")
	check("Opportunity -> Customer saved", not page.evaluate("!!cur_frm.doc.__islocal") and not dialog(page), (customer, dialog(page)))
	page.screenshot(path=f"{OUT}/crm-3-customer.png")
	check(
		"Customer links back to the Lead and Opportunity",
		page.evaluate("cur_frm.doc.lead_name") == lead and page.evaluate("cur_frm.doc.opportunity_name") == opp,
		(page.evaluate("cur_frm.doc.lead_name"), page.evaluate("cur_frm.doc.opportunity_name")),
	)
	group, territory = page.evaluate("cur_frm.doc.customer_group"), page.evaluate("cur_frm.doc.territory")
	check("Converted Customer gets a default Customer Group and Territory", bool(group) and bool(territory), (group, territory))
	print(f"      (Customer Group = {group!r}, Territory = {territory!r})")
	status = ctx.request.get(f"{B}/api/resource/Lead/{lead}").json().get("data", {}).get("status")
	check("Lead is marked Converted", status == "Converted", status)
	check("No console/server errors during the owner flow", not bad, bad)
	page.goto(B + "/desk")
	page.wait_for_timeout(5000)
	rail = page.evaluate("[...document.querySelectorAll('.body-sidebar a')].map(e=>e.innerText.trim())")
	check("CRM shows in the owner's sidebar (Add-ons)", "CRM" in rail, rail)
	ctx.close()

	# 4. every other retail role: no CRM in navigation, every CRM route blocked, no data shown
	for who, user in [
		("cashier", "cashier.downtown@demo.example"),
		("attendant+cashier", "cashier.mall@demo.example"),
		("store manager", "manager.downtown@demo.example"),
		("store admin", "admin@demo.example"),
		("warehouse manager", "wh.manager@demo.example"),
	]:
		c = br.new_context(viewport={"width": 1440, "height": 900})
		pg = c.new_page()
		login(c, user)
		pg.goto(B + "/desk")
		pg.wait_for_timeout(5000)
		rail = pg.evaluate("[...document.querySelectorAll('.st-rail-module,.st-rail-app')].map(e=>e.innerText.trim())")
		check(f"{who}: no CRM in the rail", "CRM" not in rail, rail)
		open_routes = []
		for path in ("/desk/lead", "/desk/opportunity", "/desk/prospect", "/desk/crm", f"/desk/lead/{lead}"):
			pg.goto(B + path)
			pg.wait_for_timeout(2400)
			if not pg.locator(".modal.show").count():
				open_routes.append(path)
			body = pg.evaluate("document.querySelector('.page-container')?.innerText||''")
			if "Crmtest" in body or lead in body:
				open_routes.append(path + " (data shown)")
		check(f"{who}: every CRM route blocked", not open_routes, open_routes)
		c.close()

	# 5. cleanup as Administrator. Converting a Lead also creates a Prospect and a Contact, and
	# the Prospect links the Opportunity and Contact, so it has to go first.
	if not KEEP:
		c = br.new_context()
		login(c, "Administrator", "admin")
		q = urllib.parse.quote
		prospects = c.request.get(f"{B}/api/resource/Prospect?filters={q(json.dumps([['company_name', '=', 'Zed Crmtest Shoes']]))}").json().get("data", [])
		doomed = [("Prospect", x["name"]) for x in prospects] + [("Customer", customer), ("Opportunity", opp), ("Contact", "Zed Crmtest"), ("Lead", lead)]
		for dt, name in doomed:
			r = c.request.delete(f"{B}/api/resource/{dt}/{q(name)}")
			check(f"cleanup: deleted {dt} {name}", r.ok or r.status == 404, r.status)
		c.close()
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
