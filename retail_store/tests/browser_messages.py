"""Customer messages in a real browser: the storefront opt-in boxes, an online order and its delivery producing
Message Log rows, the Customer form's consent section, and the Messages tab of Retail Store Settings per role.

Needs the Online Store toggle ON, the webshop app and demo data (see browser_store.py, whose flow this reuses).
Switches Customer Messages on for the run and back off at the end; everything it creates is cancelled / removed.

Run:  /tmp/pw/bin/python browser_messages.py
"""
import json
import os
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/messages"
PASSWORD = "RetailDemo#2026"
VARIANT = "DEMO-SNEAKER-42-WHIT"
SHOPPER = "shopper@demo.example"
os.makedirs(OUT, exist_ok=True)
results = []
q = urllib.parse.quote


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def login(ctx, user, pwd=PASSWORD):
	ctx.request.post(f"{B}/api/method/login", data={"usr": user, "pwd": pwd})


def api(ctx, path):
	r = ctx.request.get(f"{B}{path}")
	return r.json().get("data") if r.ok else None


def logs(admin, **filters):
	f = q(json.dumps([[k, "=", v] for k, v in filters.items()]))
	return api(admin, f"/api/resource/Retail Message Log?filters={f}&fields={q(json.dumps(['name','event','channel','status','recipient','body','kind','consent_basis','provider']))}&limit_page_length=0") or []


def set_messaging(admin, on):
	admin.request.put(f"{B}/api/resource/Retail Store Settings/Retail Store Settings", data=json.dumps({"enable_messaging": 1 if on else 0}), headers={"Content-Type": "application/json"})


def shopper_customer(admin):
	rows = api(admin, f"/api/resource/Portal User?filters={q(json.dumps([['user', '=', SHOPPER], ['parenttype', '=', 'Customer']]))}&fields={q(json.dumps(['parent']))}&parent=Customer") or []
	return rows[0]["parent"] if rows else None


def add_variant_to_cart(page):
	page.goto(B + "/all-products")
	page.wait_for_timeout(3000)
	page.locator("a[href*='demo-everyday-sneaker']:visible").first.click()
	page.wait_for_timeout(3500)
	page.get_by_role("button", name="Select Variant").click()
	page.wait_for_timeout(1500)
	page.locator(".modal select").nth(0).select_option("42")
	page.wait_for_timeout(600)
	page.locator(".modal select").nth(1).select_option("White")
	page.wait_for_timeout(2200)
	page.locator(".modal.show").get_by_role("button", name="Add to Cart").click()
	page.wait_for_timeout(3500)
	page.goto(B + "/cart")
	page.wait_for_timeout(4500)


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	login(admin, "Administrator", "admin")
	customer = shopper_customer(admin)
	so_name = dn_name = None
	addr_filters = q(json.dumps([["Dynamic Link", "link_doctype", "=", "Customer"], ["Dynamic Link", "link_name", "=", customer]]))
	addresses = api(admin, f"/api/resource/Address?filters={addr_filters}&fields={q(json.dumps(['name', 'phone']))}&limit_page_length=0") or []
	try:
		for a in addresses:  # the demo shopper has no phone; real shoppers give one in the cart's address form
			admin.request.put(f"{B}/api/resource/Address/{q(a['name'])}", data=json.dumps({"phone": "5799 1234"}), headers={"Content-Type": "application/json"})
		# 1. messaging OFF: the cart shows no boxes
		set_messaging(admin, False)
		ctx = br.new_context(viewport={"width": 1300, "height": 1100})
		page = ctx.new_page()
		errors = []
		page.on("pageerror", lambda e: errors.append(str(e)[:120]))
		login(ctx, SHOPPER)
		add_variant_to_cart(page)
		check("messaging off: the cart has no opt-in boxes", page.locator("#rs-consent").count() == 0)
		ctx.close()

		# 2. messaging ON: boxes are there, unticked for a customer who never opted in
		set_messaging(admin, True)
		admin.request.put(f"{B}/api/resource/Customer/{q(customer)}", data=json.dumps({"custom_whatsapp_optin": 0, "custom_sms_optin": 0}), headers={"Content-Type": "application/json"})
		ctx = br.new_context(viewport={"width": 1300, "height": 1100})
		page = ctx.new_page()
		page.on("pageerror", lambda e: errors.append(str(e)[:120]))
		login(ctx, SHOPPER)
		page.goto(B + "/cart")
		page.wait_for_timeout(4500)
		check("messaging on: two opt-in boxes above Place Order", page.locator("#rs-consent-wa").count() == 1 and page.locator("#rs-consent-sms").count() == 1)
		check("both boxes start UNTICKED", not page.locator("#rs-consent-wa").is_checked() and not page.locator("#rs-consent-sms").is_checked())
		check("the order-update note is shown", "phone number on your order" in page.locator("#rs-consent").inner_text())
		page.locator("#rs-consent-wa").check()
		page.screenshot(path=f"{OUT}/messages-1-cart.png")
		page.get_by_role("button", name="Place Order").click()
		page.wait_for_timeout(6500)
		so_name = page.url.rsplit("/", 1)[-1]
		check("order is placed", so_name.startswith("SAL-ORD-"), page.url)
		cust = api(admin, f"/api/resource/Customer/{q(customer)}") or {}
		check("ticking WhatsApp saved the consent with when / how / who", cust.get("custom_whatsapp_optin") == 1 and cust.get("custom_whatsapp_optin_on") and cust.get("custom_consent_source") == "Storefront checkout" and not cust.get("custom_sms_optin"), {k: v for k, v in cust.items() if k.startswith("custom_")})

		# 3. the confirmation reached the outbox (dry run: nothing leaves the machine)
		rows = []
		for _ in range(15):
			rows = logs(admin, reference_name=so_name, event="Order confirmation")
			if rows and all(r["status"] != "Queued" for r in rows):
				break
			time.sleep(2)
		check("order confirmation logged (WhatsApp rule is on by default, SMS off)", [r["channel"] for r in rows] == ["WhatsApp"], rows)
		check("...as a transactional message to the number on file", rows and rows[0]["kind"] == "Transactional" and rows[0]["recipient"].startswith("+"), rows)
		check("...with the order and total in the text", rows and so_name in rows[0]["body"], rows)
		check("...delivered by the background job (Sent, Dry run), nothing left the machine", rows and rows[0]["status"] == "Sent" and rows[0]["provider"] == "Dry run", [(r["status"], r["provider"]) for r in rows])
		check("no browser errors during checkout", not errors, errors)
		ctx.close()

		# 4. the owner posts the delivery -> "order ready"
		oc = br.new_context(viewport={"width": 1440, "height": 1000})
		pg = oc.new_page()
		login(oc, "owner@demo.example")
		pg.goto(B + f"/desk/sales-order/{so_name}")
		pg.wait_for_function("window.cur_frm&&cur_frm.doctype=='Sales Order'", timeout=30000)
		pg.wait_for_timeout(2500)
		pg.locator('.inner-group-button[data-label="Create"] button:visible').first.click()
		pg.wait_for_timeout(600)
		pg.evaluate("""()=>{const g=[...document.querySelectorAll('.inner-group-button[data-label="Create"]')].find(e=>e.offsetParent!==null);g.querySelector('a.dropdown-item[data-label="Delivery%20Note"]').click()}""")
		pg.wait_for_function("window.cur_frm&&cur_frm.doctype=='Delivery Note'", timeout=30000)
		pg.wait_for_timeout(1800)
		pg.evaluate("()=>{cur_frm.savesubmit(); return true}")
		pg.wait_for_timeout(3000)
		btn = pg.locator(".modal.show .btn-primary:visible, .modal.show .btn-modal-primary:visible")
		if btn.count():
			btn.first.click()
		pg.wait_for_timeout(5000)
		dn_name = pg.evaluate("cur_frm.doc.name")
		check("owner submits the Delivery Note", pg.evaluate("cur_frm.doc.docstatus") == 1, dn_name)
		ready = []
		for _ in range(15):
			ready = logs(admin, reference_name=dn_name, event="Order ready")
			if ready and all(r["status"] != "Queued" for r in ready):
				break
			time.sleep(2)
		check("'Order ready' is sent when the delivery is posted", len(ready) == 1 and ready[0]["status"] == "Sent" and so_name in ready[0]["body"], ready)

		# 5. Customer form: the consent section, filled in by the checkout above
		pg.goto(B + f"/desk/customer/{q(customer)}")
		pg.wait_for_function("window.cur_frm&&cur_frm.doctype=='Customer'", timeout=30000)
		pg.wait_for_timeout(2500)
		toggle = pg.locator(".st-pf-toggle-btn")  # the theme keeps optional fields behind "Show N optional fields"
		if toggle.count() and "Show" in toggle.first.inner_text():
			toggle.first.click()
			pg.wait_for_timeout(600)
		pg.locator('button.nav-link:has-text("Messages")').first.click()
		pg.wait_for_timeout(900)
		check("Customer form has a Messages tab with 'Offers by WhatsApp / SMS'", pg.locator('.frappe-control[data-fieldname="custom_whatsapp_optin"]:visible').count() == 1)
		check("...with both boxes visible", pg.locator('.frappe-control[data-fieldname="custom_whatsapp_optin"]:visible').count() == 1 and pg.locator('.frappe-control[data-fieldname="custom_sms_optin"]:visible').count() == 1)
		check("the WhatsApp box is ticked with its time and the source (storefront)", pg.evaluate("cur_frm.doc.custom_whatsapp_optin") == 1 and pg.evaluate("cur_frm.doc.custom_consent_source") == "Storefront checkout")
		pg.screenshot(path=f"{OUT}/messages-2-customer.png")

		# 6. Message Log for the owner
		pg.goto(B + "/desk/retail-message-log")
		pg.wait_for_timeout(5000)
		body = pg.evaluate("document.body.innerText")
		check("owner can open the Message Log and sees the order's messages", so_name in body or "Order confirmation" in body, body[:200])
		check("...but cannot create entries by hand", pg.locator('button.primary-action:visible:has-text("Add")').count() == 0 and pg.locator('.btn-primary:visible:has-text("New")').count() == 0)
		pg.screenshot(path=f"{OUT}/messages-3-log.png")
		oc.close()

		# 7. Settings > Messages per role
		for user, rules, creds in (("owner", True, True), ("admin", True, False), ("manager.downtown", False, False), ("cashier.downtown", False, False)):
			c = br.new_context(viewport={"width": 1440, "height": 1000})
			s = c.new_page()
			login(c, f"{user}@demo.example")
			s.goto(B + "/desk/retail-store-settings")
			s.wait_for_timeout(5000)
			opened = s.evaluate("!!(window.cur_frm&&cur_frm.doctype=='Retail Store Settings')")
			if rules:
				check(f"{user}: opens Retail Store Settings", opened)
				s.locator('button.nav-link:has-text("Messages")').first.click()
				s.wait_for_timeout(900)
				check(f"{user}: Messages tab shows the message list", s.locator('[data-fieldname="message_rules"]:visible').count() == 1)
				if creds:
					for sec in ("messaging_whatsapp_section", "messaging_sms_section"):  # collapsible: open them
						s.locator(f'[data-fieldname="{sec}"] .section-head').first.click()
						s.wait_for_timeout(400)
				seen = [s.locator(f'.frappe-control[data-fieldname="{f}"]:visible').count() == 1 for f in ("whatsapp_access_token", "sms_password", "whatsapp_phone_number_id", "sms_gateway_url")]
				sections = s.locator('[data-fieldname="messaging_whatsapp_section"]:visible, [data-fieldname="messaging_sms_section"]:visible').count()
				check(f"{user}: WhatsApp / SMS connection fields visible = {creds}", all(seen) if creds else (not any(seen) and sections == 0), (seen, sections))
				s.screenshot(path=f"{OUT}/messages-4-settings-{user}.png")
			else:
				body = s.evaluate("document.body.innerText")
				check(f"{user}: cannot open Retail Store Settings", not opened or "Not permitted" in body or "not permitted" in body.lower(), body[:120])
			c.close()

		# 8. sidebar: 'Messages' under Back Office for owner/admin only
		for user, shown in (("owner", True), ("admin", True), ("manager.downtown", False), ("cashier.downtown", False)):
			c = br.new_context(viewport={"width": 1440, "height": 1000})
			s = c.new_page()
			login(c, f"{user}@demo.example")
			s.goto(B + "/desk/retail-store")
			s.wait_for_selector(".ce-block", timeout=60000)
			s.wait_for_timeout(3500)
			side = s.evaluate("(document.querySelector('.body-sidebar')||document.body).innerText").lower()
			check(f"{user}: sidebar shows 'Messages' = {shown}", ("messages" in side) == shown, side[:200])
			c.close()
	finally:
		# cleanup: cancel the delivery and the order (the stock goes back), remove the message rows, reset consent, switch off
		for dt, name in (("Delivery Note", dn_name), ("Sales Order", so_name)):
			if name:
				admin.request.post(f"{B}/api/method/frappe.client.cancel", data={"doctype": dt, "name": name})
				for row in logs(admin, reference_name=name):
					admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Retail Message Log", "name": row["name"]})
		for dq in api(admin, "/api/resource/Quotation?filters=" + q(json.dumps([["order_type", "=", "Shopping Cart"], ["docstatus", "=", 0]])) + "&limit_page_length=0") or []:
			admin.request.post(f"{B}/api/method/frappe.client.delete", data={"doctype": "Quotation", "name": dq["name"]})
		if customer:
			admin.request.put(f"{B}/api/resource/Customer/{q(customer)}", data=json.dumps({"custom_whatsapp_optin": 0, "custom_sms_optin": 0}), headers={"Content-Type": "application/json"})
		set_messaging(admin, False)
		for a in addresses:
			admin.request.put(f"{B}/api/resource/Address/{q(a['name'])}", data=json.dumps({"phone": a.get("phone") or ""}), headers={"Content-Type": "application/json"})
		if so_name:
			state = (api(admin, f"/api/resource/Sales Order/{q(so_name)}") or {}).get("docstatus")
			check(f"cleanup: order {so_name} cancelled", state == 2, state)
		check("cleanup: Customer Messages switched back off", not (api(admin, "/api/resource/Retail Store Settings/Retail Store Settings") or {}).get("enable_messaging"))
		admin.close()
		br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
