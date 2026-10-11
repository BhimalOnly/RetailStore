"""Browser click-through of the HR module as real demo users (after tests/check_hr.py seeded data).

Needs Playwright (see browser_pos.py). Seed first:
    bench --site retail.localhost execute retail_store.tests.seed_hr_demo.run
Run:  /path/to/pw/bin/python browser_hr.py     Screenshots land in ./shots/hr-*.png
"""
import json
import os
from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
OUT = "shots"
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


def login(br, user, pwd=PWD):
	ctx = br.new_context(viewport={"width": 1300, "height": 850})
	page = ctx.new_page()
	r = ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": pwd})
	assert r.status == 200, (user, r.status)
	return ctx, page


def list_names(page, doctype="employee"):
	page.goto(f"{B}/desk/{doctype}")
	page.wait_for_timeout(4000)
	return page.inner_text("body")


with sync_playwright() as p:
	br = p.chromium.launch()

	# --- Cashier: POS -> Clock In / Out -> clock in and out, never touching Desk
	ctx, page = login(br, "cashier.downtown@demo.example")
	page.goto(f"{B}/desk/point-of-sale")
	page.wait_for_selector(".item-wrapper", state="attached", timeout=90000)
	page.wait_for_timeout(3500)
	if page.locator(".modal.show").count():  # POS asks to roll over yesterday's opening entry; not part of HR
		page.keyboard.press("Escape"); page.wait_for_timeout(600)
	btn = page.locator(".rs-clock-btn:visible")
	check("POS shows a Clock In / Out button", btn.count() >= 1)
	page.screenshot(path=f"{OUT}/hr-1-pos-button.png")
	btn.first.click()
	page.wait_for_selector(".rs-clock .rs-btn", timeout=20000)
	check("Clock page opens from POS", "store-clock" in page.url)
	check("Clock page is chrome-free (no Desk navbar, rail or sidebar)", not any(page.locator(x + ":visible").count() for x in ("#st-top-toolbar", "#st-icon-rail", ".body-sidebar-container")))
	check("Clock page shows employee + store", "Dana Downtown" in page.inner_text(".rs-clock") and "Downtown" in page.inner_text(".rs-clock"))
	page.screenshot(path=f"{OUT}/hr-2-clock-out-state.png")
	check("Starts clocked out with a Clock In button", page.inner_text(".rs-btn").strip() == "Clock In")
	page.click(".rs-btn")
	page.wait_for_selector(".rs-btn:has-text('Clock Out')", timeout=15000)
	check("Clock In flips to Clocked in / Clock Out", "Clocked in since" in page.inner_text(".rs-clock"))
	page.screenshot(path=f"{OUT}/hr-3-clocked-in.png")
	page.reload(); page.wait_for_selector(".rs-btn", timeout=20000)
	check("State survives a reload", page.inner_text(".rs-btn").strip() == "Clock Out")
	page.click(".rs-btn")
	page.wait_for_selector(".rs-btn:has-text('Clock In')", timeout=15000)
	check("Clock Out returns to Clocked out", "Clocked out" in page.inner_text(".rs-clock"))
	page.screenshot(path=f"{OUT}/hr-4-clocked-out.png")
	body = list_names(page)
	check("Cashier cannot list Employees", "Mia Mall" not in body and "Pat Airport" not in body)
	page.screenshot(path=f"{OUT}/hr-5-cashier-employee-list.png")
	page.goto(f"{B}/desk/payroll"); page.wait_for_timeout(3000)
	check("Cashier cannot open Payroll", "Not permitted" in page.inner_text("body") or "payroll" not in page.url)
	ctx.close()

	# --- Cashier without an Employee record
	ctx, page = login(br, "wh.attendant@demo.example")
	page.goto(f"{B}/desk/store-clock"); page.wait_for_timeout(4000)
	check("No Employee record -> clear message", "No employee record" in page.inner_text("body"))
	ctx.close()

	# --- Store Manager: own store only, cannot create
	ctx, page = login(br, "manager.downtown@demo.example")
	body = list_names(page)
	page.screenshot(path=f"{OUT}/hr-6-manager-employee-list.png")
	check("Manager sees Downtown staff (login + loginless)", all(n in body for n in ("Dana Downtown", "Cleo Cleaner", "Marco Manager")))
	check("Manager does not see Mall / Airport staff", "Mia Mall" not in body and "Pat Airport" not in body)
	check("Manager has no New button", page.locator("button.primary-action:has-text('Add Employee'), button.primary-action:has-text('New')").count() == 0)
	page.goto(f"{B}/desk/employee/new"); page.wait_for_timeout(3500)
	# Frappe still draws an empty New form from a typed URL; what matters is that saving is refused.
	status = page.evaluate("""async () => (await fetch('/api/resource/Employee', {method: 'POST',
		headers: {'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': frappe.csrf_token},
		body: JSON.stringify({first_name: 'Nope', last_name: 'RSHR', gender: 'Male', date_of_birth: '1990-01-01',
			date_of_joining: '2024-01-01', company: 'Demo Retail Co', custom_store_warehouse: 'DEMO Store Downtown - DRC'})})).status""")
	check("Manager's attempt to create an Employee is refused by the server", status == 403, status)
	page.goto(f"{B}/desk/employee/HR-EMP-00002"); page.wait_for_timeout(3500)
	check("Manager refused another store's employee by URL", "Mia Mall" not in page.inner_text("body"))
	page.screenshot(path=f"{OUT}/hr-7-manager-other-store.png")
	page.goto(f"{B}/desk/employee/HR-EMP-00005"); page.wait_for_timeout(3500)
	check("Manager opens own store's employee", "Cleo" in page.inner_text("body"))
	for dt in ("attendance", "shift-assignment", "leave-application", "employee-checkin"):
		page.goto(f"{B}/desk/{dt}"); page.wait_for_timeout(3000)
		check(f"Manager opens {dt} list", "Not permitted" not in page.inner_text("body"))
	page.goto(f"{B}/desk/employee-incentive"); page.wait_for_timeout(3500)
	check("Manager sees no one's payroll document (incentive for Mia Mall / Dana hidden)", "Mia Mall" not in page.inner_text("body") and "Dana Downtown" not in page.inner_text("body"))
	page.screenshot(path=f"{OUT}/hr-8-manager-no-payroll.png")
	ctx.close()

	# --- Store Owner: everyone, can create, payroll
	ctx, page = login(br, "owner@demo.example")
	body = list_names(page)
	page.screenshot(path=f"{OUT}/hr-9-owner-employee-list.png")
	check("Owner sees all stores' staff", all(n in body for n in ("Dana Downtown", "Mia Mall", "Pat Airport", "Cleo Cleaner")))
	check("Owner has a New/Add button", page.locator("button.primary-action").filter(has_text="Employee").count() >= 1 or page.locator("button.primary-action:has-text('New')").count() >= 1)
	page.goto(f"{B}/desk/employee/new"); page.wait_for_timeout(4000)
	check("Owner opens a New Employee form with the Store / Location field", page.locator("[data-fieldname='custom_store_warehouse']").count() >= 1)
	page.fill("[data-fieldname='first_name'] input", "Zed")
	page.screenshot(path=f"{OUT}/hr-9b-owner-new-employee.png")
	page.goto(f"{B}/desk/payroll"); page.wait_for_timeout(4000)
	check("Owner opens Payroll", "Not permitted" not in page.inner_text("body"))
	page.screenshot(path=f"{OUT}/hr-10-owner-payroll.png")
	page.goto(f"{B}/desk/salary-component"); page.wait_for_timeout(3500)
	body = page.inner_text("body")
	check("Owner sees seeded payroll components", "CSG (Employee)" in body and "PAYE" in body)
	page.screenshot(path=f"{OUT}/hr-11-owner-components.png")
	ctx.close()

	# --- Store Admin: can create, no payroll
	ctx, page = login(br, "admin@demo.example")
	page.goto(f"{B}/desk/employee/new"); page.wait_for_timeout(4000)
	check("Admin opens a New Employee form", page.locator("[data-fieldname='first_name']").count() >= 1)
	list_names(page)
	check("Admin has a New/Add button", page.locator("button.primary-action").count() >= 1)
	page.screenshot(path=f"{OUT}/hr-12-admin-employee-list.png")
	page.goto(f"{B}/desk/payroll"); page.wait_for_timeout(3000)
	check("Admin cannot open Payroll", "Not permitted" in page.inner_text("body") or "payroll" not in page.url)
	ctx.close()

	# --- System Manager
	ctx, page = login(br, "Administrator", "admin")
	body = list_names(page)
	check("System Manager sees all staff", "Pat Airport" in body and "Mia Mall" in body)
	page.goto(f"{B}/desk/retail-store-settings"); page.wait_for_timeout(4000)
	page.get_by_role("tab", name="HR & Payroll").click(); page.wait_for_timeout(800)
	toggle = page.get_by_text("optional fields")
	if toggle.count():
		toggle.first.click(); page.wait_for_timeout(600)
	body = page.inner_text("body")
	check("System Manager sees the payroll rate fields", "CSG Employee Rate" in body and "PAYE Rate" in body)
	page.screenshot(path=f"{OUT}/hr-13-settings-payroll.png", full_page=True)
	ctx.close()

	# --- Store Owner cannot see the payroll rates (System Manager only, like Branding)
	ctx, page = login(br, "owner@demo.example")
	page.goto(f"{B}/desk/retail-store-settings"); page.wait_for_timeout(4000)
	body = page.inner_text("body")
	check("Owner does not see the payroll rate fields", "CSG Employee Rate" not in body and "PAYE Rate" not in body)
	ctx.close()
	br.close()

print(f"\n{len(fails)} failure(s)", fails)
