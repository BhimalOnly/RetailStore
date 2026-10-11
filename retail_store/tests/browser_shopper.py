"""Shopper identity on the Online Store, in a real browser: a BRAND-NEW customer can sign up and buy
(browser_store.py only exercises the pre-made demo shopper), plus the pieces around it.

  * /login is the staff (Solvronix) page; shoppers have their own /account/login, which the shop links to
  * the store front page (/) has a banner, categories and new arrivals
  * portal pages a customer should not have are refused (403), not just hidden from the sidebar
  * new customer: Add to Cart as a guest -> shopper login -> Sign up -> emailed link -> set password ->
    signed in -> cart -> new address -> Place Order -> a Sales Order exists for THEM

Signup is email-verified (Frappe sends a set-password link), so the site needs an outgoing Email
Account. For a dev site run the sink and point a default-outgoing Email Account at it
(SMTP 127.0.0.1:1025, no TLS, no auth):
    python -m venv /tmp/mailvenv && /tmp/mailvenv/bin/pip install aiosmtpd
    MAIL_OUT=/tmp/retail_mail /tmp/mailvenv/bin/python tests/mail_sink.py &
Run (Playwright as in browser_pos.py):
    MAIL_OUT=/tmp/retail_mail /tmp/pw/bin/python browser_shopper.py
Leaves one test Customer per run (its Sales Order is cancelled, which ERPNext will not delete); clear
them with:  bench --site retail.localhost execute retail_store.demo.purge_signup_test_customers
"""
import email
import glob
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/shopper"
MAIL = os.environ.get("MAIL_OUT", "/tmp/retail_mail")
os.makedirs(OUT, exist_ok=True)
EMAIL = f"signup-test-{int(time.time())}@demo.example"
PASSWORD = "Sh0pper!Pass#2026x"
results = []


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def api(ctx, path, **params):
	r = ctx.request.get(B + path, params=params)
	return r.json().get("data") if r.ok else None


def read_signup_link():
	"""The set-password link from the mail the sink received for EMAIL (Frappe redacts it in Email Queue)."""
	for _ in range(30):
		for f in sorted(glob.glob(MAIL + "/*.eml")):
			m = email.message_from_bytes(open(f, "rb").read())
			if EMAIL in (m["To"] or ""):
				body = ""
				for part in m.walk():
					if part.get_content_type() in ("text/html", "text/plain"):
						payload = part.get_payload(decode=True)
						body += payload.decode("utf8", "ignore") if payload else ""
				found = re.search(r'https?://[^\s"<>]*update-password\?key=[A-Za-z0-9]+', body)
				if found:
					return re.sub(r"^https?://[^/]+", B, found.group(0))  # dev site has no host_name
		time.sleep(2)
	return None


with sync_playwright() as p:
	br = p.chromium.launch()
	admin = br.new_context()
	admin.request.post(B + "/api/method/login", data={"usr": "Administrator", "pwd": "admin"})

	# ---- prerequisites ------------------------------------------------------------------------
	disabled = admin.request.get(B + "/api/method/frappe.client.get_value", params={"doctype": "Website Settings", "fieldname": "disable_signup"}).json().get("message", {}).get("disable_signup")
	check("signup is enabled on the site", not int(disabled or 0))
	outgoing = api(admin, "/api/resource/Email Account", filters=json.dumps([["default_outgoing", "=", 1], ["enable_outgoing", "=", 1]]), fields=json.dumps(["name"]))
	check("a default outgoing Email Account exists (signup is email-verified)", bool(outgoing))

	# ---- 1. two separate sign-in URLs -----------------------------------------------------------
	pg = br.new_page(viewport={"width": 1300, "height": 1000})

	def flags(url, referer=None):
		pg.goto(url, referer=referer) if referer else pg.goto(url)
		pg.wait_for_timeout(1500)
		return pg.evaluate("document.body.classList.contains('rs-shop-login')"), pg.evaluate("document.body.classList.contains('sl-split')")

	check("/login is the staff (Solvronix) page", flags(B + "/login") == (False, True))
	check("/login stays the staff page even when reached from a shop page", flags(B + "/login", B + "/all-products") == (False, True))
	check("/login?redirect-to=/desk... is the staff page", flags(B + "/login?redirect-to=/desk/point-of-sale", B + "/desk") == (False, True))
	check("/account/login is the shopper page", flags(B + "/account/login") == (True, False))
	pg.goto(B + "/all-products")
	pg.wait_for_timeout(2000)
	nav = pg.locator("a.btn-login-area").first.get_attribute("href")
	check("shop navbar Login link points at /account/login", nav == "/account/login", nav)
	check("a signed-out visitor on /orders is sent to the shopper sign-in", flags(B + "/orders") == (True, False) and "/account/login" in pg.url, pg.url)
	pg.goto(B + "/account/login")
	pg.wait_for_timeout(1500)
	check("shopper login offers Sign up", pg.locator("a:has-text('Sign up')").count() > 0)
	check("shopper login has no 'Powered by' staff footer text", "Powered by Solvronix" not in pg.inner_text("body"))
	pg.screenshot(path=f"{OUT}/1-shopper-login.png")
	pg.click("a:has-text('Sign up')")
	pg.wait_for_timeout(800)
	pg.screenshot(path=f"{OUT}/1b-shopper-signup.png")
	pg.set_viewport_size({"width": 390, "height": 844})
	pg.wait_for_timeout(500)
	pg.screenshot(path=f"{OUT}/1c-shopper-signup-mobile.png")
	check("shopper sign-up has no horizontal overflow at 390px", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
	pg.goto(B + "/account/login")
	pg.wait_for_timeout(1200)
	pg.screenshot(path=f"{OUT}/1d-shopper-login-mobile.png")
	check("shopper login has no horizontal overflow at 390px", pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
	pg.goto(B + "/login")
	pg.wait_for_timeout(1500)
	pg.screenshot(path=f"{OUT}/1e-staff-login-mobile.png")
	pg.set_viewport_size({"width": 1300, "height": 1000})
	pg.goto(B + "/login")
	pg.wait_for_timeout(1500)
	pg.screenshot(path=f"{OUT}/1f-staff-login.png")

	# ---- 2. store front page --------------------------------------------------------------------
	headline = (admin.request.get(B + "/api/method/frappe.client.get_value", params={"doctype": "Retail Store Settings", "fieldname": "storefront_headline"}).json().get("message") or {}).get("storefront_headline")
	pg.goto(B + "/")
	pg.wait_for_timeout(2500)
	check("home page is the store front, not the product list", pg.locator(".rs-hero").count() == 1, pg.url)
	check("home banner shows the configured headline", headline and headline in pg.inner_text(".rs-hero h1"), headline)
	check("home page lists categories", pg.locator(".rs-cat").count() > 0)
	check("home page lists new arrivals", pg.locator(".rs-prod").count() > 0)
	first_cat = pg.locator(".rs-cat").first.get_attribute("href")
	check("a category tile opens a real page", admin.request.get(B + first_cat).status == 200, first_cat)
	pg.screenshot(path=f"{OUT}/2-home.png", full_page=True)

	# ---- 3. portal pages a customer should not have --------------------------------------------
	demo = br.new_context()
	demo.request.post(B + "/api/method/login", data={"usr": "shopper@demo.example", "pwd": "RetailDemo#2026"})
	for path in ("/orders", "/invoices", "/shipments", "/addresses", "/me", "/cart"):
		check(f"customer can open {path}", demo.request.get(B + path).status == 200)
	for path in ("/projects", "/project", "/timesheets", "/material-requests", "/issues", "/issues/new", "/rfq", "/purchase-orders"):
		check(f"customer is refused {path}", demo.request.get(B + path).status == 403, demo.request.get(B + path).status)
	dp = demo.new_page()
	dp.goto(B + "/orders")
	dp.wait_for_timeout(1500)
	links = dp.evaluate("[...document.querySelectorAll('.sidebar-link, .sidebar-item a, .list-sidebar a')].map(a => a.innerText.trim())")
	check("portal sidebar lists no staff modules", not {"Projects", "Timesheets", "Issues", "Material Request"} & set(links), links)

	# ---- 4. a brand-new customer signs up and buys ----------------------------------------------
	ctx = br.new_context(viewport={"width": 1300, "height": 1100})
	page = ctx.new_page()
	bad = []
	page.on("pageerror", lambda e: bad.append(str(e)[:120]))
	page.goto(B + "/demo-canvas-tote-bag-1r5hy")
	page.wait_for_timeout(2500)
	page.get_by_role("button", name="Add to Cart").first.click()
	page.wait_for_timeout(3500)
	check("guest Add to Cart lands on /account/login", "/account/login" in page.url and page.evaluate("document.body.classList.contains('rs-shop-login')"), page.url)
	page.click("a:has-text('Sign up')")
	page.wait_for_timeout(800)
	page.fill("#signup_fullname", "Asha Newshopper")
	page.fill("#signup_email", EMAIL)
	page.click(".btn-signup")
	page.wait_for_timeout(4000)
	check("signup says to check email", "email" in page.inner_text("body").lower())
	page.screenshot(path=f"{OUT}/3-signup-submitted.png")
	link = read_signup_link()
	check("verification email arrives with a set-password link", bool(link))
	if not link:
		print("\nNo email reached", MAIL, "- is the sink running and the Email Account pointing at it?")
		sys.exit(1)
	page.goto(link)
	page.wait_for_timeout(2500)
	page.screenshot(path=f"{OUT}/4-set-password.png")
	check("set-password page is the storefront look (not the staff page)", not page.evaluate("document.body.classList.contains('sl-split')"))
	page.locator("#new_password").press_sequentially(PASSWORD, delay=15)
	page.locator("#confirm_password").press_sequentially(PASSWORD, delay=15)
	page.wait_for_timeout(1200)
	page.click("#update")
	page.wait_for_timeout(4500)
	uid = [c["value"] for c in ctx.cookies() if c["name"] == "user_id"]
	check("after setting a password the new customer is signed in", uid and EMAIL.replace("@", "%40") in uid[0], uid)
	check("...and is a Website User (no Desk access)", api(admin, f"/api/resource/User/{EMAIL}") and api(admin, f"/api/resource/User/{EMAIL}").get("user_type") == "Website User")

	page.goto(B + "/demo-canvas-tote-bag-1r5hy")
	page.wait_for_timeout(2500)
	page.get_by_role("button", name="Add to Cart").first.click()
	page.wait_for_timeout(3500)
	page.goto(B + "/cart")
	page.wait_for_timeout(4500)
	check("cart shows the item", "DEMO-TOTE" in page.inner_text("body") or "DEMO Canvas Tote" in page.inner_text("body"))
	page.screenshot(path=f"{OUT}/5-cart-no-address.png")
	page.click("text=Add a new address")
	page.wait_for_timeout(2500)
	dlg = page.locator(".modal-content:visible").last
	texts = dlg.locator("input[type=text]")
	for i, value in enumerate(["Home", "12 Royal Road", "", "Port Louis", ""]):
		if value:
			texts.nth(i).fill(value)
	dlg.locator("select").select_option("Shipping")
	country = texts.nth(5)
	country.fill("Mauritius")
	page.wait_for_timeout(1500)
	suggestion = page.locator("ul[role=listbox] li:visible, .awesomplete li:visible").first
	if suggestion.count():
		suggestion.click()
	texts.nth(7).fill("52501234")  # phone (after postal code)
	page.screenshot(path=f"{OUT}/6-address-form.png")
	dlg.get_by_role("button", name="Save").click()
	page.wait_for_timeout(4000)
	check("new address saved and offered at checkout", "Royal Road" in page.inner_text("body"))
	page.screenshot(path=f"{OUT}/7-cart-with-address.png", full_page=True)
	page.get_by_role("button", name="Place Order").click()
	page.wait_for_timeout(6000)
	so_name = page.url.rsplit("/", 1)[-1]
	check("order placed: confirmation page for the new customer", so_name.startswith("SAL-ORD-") and "Not Permitted" not in page.inner_text("body"), page.url)
	page.screenshot(path=f"{OUT}/8-order.png", full_page=True)
	order = api(admin, f"/api/resource/Sales Order/{so_name}") or {}
	check("the Sales Order belongs to the NEW customer's own Customer record", order.get("contact_email") == EMAIL or EMAIL in json.dumps(order.get("contact_email") or ""), order.get("contact_email"))
	check("order line is DEMO-TOTE", (order.get("items") or [{}])[0].get("item_code") == "DEMO-TOTE")
	check("no uncaught JS errors in the journey", not bad, "; ".join(bad[:3]))

	# ---- cleanup what can be removed ------------------------------------------------------------
	if order:
		admin.request.post(B + "/api/method/frappe.client.cancel", data={"doctype": "Sales Order", "name": so_name})
		check("cleanup: test order cancelled", (api(admin, f"/api/resource/Sales Order/{so_name}") or {}).get("docstatus") == 2)
	for q in api(admin, "/api/resource/Quotation", filters=json.dumps([["contact_email", "=", EMAIL], ["docstatus", "=", 0]]), fields=json.dumps(["name"])) or []:
		admin.request.post(B + "/api/method/frappe.client.delete", data={"doctype": "Quotation", "name": q["name"]})
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
