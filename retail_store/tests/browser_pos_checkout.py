"""A real till checkout, end to end, in the browser, as the FLOATING Cashier + Attendant (floater@demo.example) at the
Airport till: add an item, Checkout, pay cash, Complete Order, confirm the submit.

Why this exists: the POS was only ever exercised over REST (e2e_section7.py) or as far as the cart (browser_pos.py), and form
tests ran as Administrator / Manager. A floating cashier's first real sale then showed "Currency is now required" and
"Debit To is now required" toasts piling up over the Checkout button (progressive_guard.js announcing required fields of the
POS's own off-screen Sales Invoice form). Nothing noticed, because nothing completed a sale as a till user.

Asserts, in the UI: no "is now required" toast while adding the item, the Checkout button is not covered by anything, the
payment screen opens, Complete Order + the submit confirmation finish. Then over REST (as Administrator): the new Sales
Invoice is submitted, is a POS sale for the Airport profile made by this user, has its Currency and Debit To, is fully paid
in Cash, and the item's stock at the Airport warehouse dropped by one. The sale is cancelled again at the end, which reverses
the stock and the ledger (REST cannot delete a Sales Invoice that has accounting entries, so a cancelled one is left behind).

Needs Playwright + Chromium (see browser_pos.py) and an open POS Opening Entry today for the user at that till; when there is
none the test says so instead of failing (`bench --site retail.localhost execute retail_store.demo.refresh_pos_openings`).
Optional 4th / 5th arguments: the cash handed over (more than the total = a sale with CHANGE: the hidden Account for Change Amount must
fill itself) and a customer to pick (typed into the cart's customer box) instead of the till's walk-in.
Run:  /tmp/pw/bin/python browser_pos_checkout.py [user] [pos_profile] [item_code] [tender] [customer]     (PW_CHROMIUM=/path/to/chrome to override)
"""
import os
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"
USER = sys.argv[1] if len(sys.argv) > 1 else "floater@demo.example"
PROFILE = sys.argv[2] if len(sys.argv) > 2 else "DEMO POS Airport"
ITEM = sys.argv[3] if len(sys.argv) > 3 else "DEMO-ETHNIC-KIDS"
TENDER = float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else 0
CUSTOMER = sys.argv[5] if len(sys.argv) > 5 else ""
fails = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
	if not ok:
		fails.append(name)


def get(ctx, doctype, **params):
	r = ctx.request.get(f"{B}/api/resource/{doctype}", params=params)
	return r.json().get("data", [])


def main():
	with sync_playwright() as p:
		exe = os.environ.get("PW_CHROMIUM")
		br = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
		admin = br.new_context()
		admin.request.post(f"{B}/api/method/login", data={"usr": "Administrator", "pwd": "admin"})
		warehouse = admin.request.get(f"{B}/api/resource/POS Profile/{PROFILE}").json()["data"]["warehouse"]

		def stock():
			rows = get(admin, "Bin", filters=f'[["item_code","=","{ITEM}"],["warehouse","=","{warehouse}"]]', fields='["actual_qty"]')
			return rows[0]["actual_qty"] if rows else 0

		opening = get(admin, "POS Opening Entry", filters=f'[["user","=","{USER}"],["pos_profile","=","{PROFILE}"],["status","=","Open"],["docstatus","=",1]]', fields='["name"]')
		if not opening:
			print(f"SKIP no open POS Opening Entry for {USER} at {PROFILE} today (run retail_store.demo.refresh_pos_openings)")
			return
		before = stock()

		ctx = br.new_context(viewport={"width": 1400, "height": 900})
		ctx.request.post(f"{B}/api/method/login", data={"usr": USER, "pwd": PWD})
		page = ctx.new_page()
		# every "is now required" alert the page ever shows (a text match: the alert markup is not a stable selector)
		page.add_init_script(
			"window.__req=[];new MutationObserver(m=>m.forEach(x=>x.addedNodes.forEach(n=>{if(n.nodeType!==1)return;"
			"[...n.querySelectorAll('*'),n].filter(c=>c.children.length===0&&/now required/.test(c.textContent||''))"
			".forEach(c=>window.__req.push(c.textContent.trim()))}))).observe(document,{childList:true,subtree:true})"
		)
		errors = []
		page.on("pageerror", lambda e: errors.append(str(e)[:160]))
		page.goto(f"{B}/desk/point-of-sale")
		page.wait_for_selector(".item-wrapper", timeout=40000)
		page.wait_for_timeout(1500)
		check("the POS opens for the floating cashier (no blocking dialog)", page.locator(".modal.show").count() == 0)
		check(f"it is the {PROFILE} till", PROFILE in page.inner_text(".page-head, .page-title, body")[:4000])

		if CUSTOMER:
			page.click(".customer-section .reset-customer-btn")  # the x beside the till's walk-in: the search box appears
			page.wait_for_selector(".customer-section input[type=text]", timeout=10000)
			page.fill(".customer-section input[type=text]", CUSTOMER)
			page.wait_for_timeout(1500)
			page.locator('ul[role="listbox"] [role="option"]').filter(has_text=CUSTOMER).first.click()  # Frappe's link control: div role=option, not li
			page.wait_for_timeout(2500)
			check(f"the customer {CUSTOMER!r} is chosen in the cart", CUSTOMER.lower() in page.inner_text(".customer-section").lower(), page.inner_text(".customer-section")[:80])
		page.click(f'.item-wrapper[data-item-code="{ITEM}"]')
		page.wait_for_timeout(3500)
		check("the item is in the cart", page.locator(".cart-item-wrapper").count() == 1)
		toasts = page.evaluate("window.__req")
		check("no 'is now required' toast while building the sale", not toasts, toasts[:4])
		covered = page.evaluate(
			"(()=>{const b=document.querySelector('.checkout-btn');if(!b)return 'missing';const r=b.getBoundingClientRect();"
			"const e=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return b.contains(e)?'clear':(e&&e.className)||'covered'})()"
		)
		check("the Checkout button is not covered by anything", covered == "clear", covered)

		page.locator(".checkout-btn:visible").first.click()
		page.wait_for_selector(".payment-container", timeout=15000)
		check("the payment screen opens", page.locator(".payment-container").is_visible())
		cash = page.locator('.mode-of-payment[data-mode="cash"]').first
		try:  # Cash is selected by default (it takes a moment to show); clicking a selected method would de-select it
			page.wait_for_selector('.mode-of-payment.border-primary[data-mode="cash"]', timeout=4000)
		except Exception:
			cash.click()
		page.wait_for_timeout(600)
		if TENDER:  # the amount is keyed on the on-screen numpad, as a cashier does: clear what is there, then the digits (in hundredths)
			pad = lambda key: page.locator(f'.numpad-btn[data-button-value="{key}"]:visible').first.click()
			for _ in range(12):
				pad("delete")
			for ch in str(int(round(TENDER * 100))):  # the pad keys hundredths, like a till: Rs 500 is 5-0-0-0-0
				pad(ch)
			page.wait_for_timeout(800)
		page.locator(".submit-order-btn").first.click()
		page.wait_for_selector(".modal.show:has-text('Permanently Submit')", timeout=20000)
		page.locator(".modal.show .btn-primary, .modal.show .btn-modal-primary").first.click()
		page.wait_for_timeout(5000)
		check("still no 'is now required' toast after payment and submit", not page.evaluate("window.__req"), page.evaluate("window.__req")[:4])
		check("no script errors", not errors, errors[:2])

		invoices = get(
			admin, "Sales Invoice",
			filters=f'[["owner","=","{USER}"],["pos_profile","=","{PROFILE}"],["is_pos","=",1]]',
			fields='["name","docstatus","currency","debit_to","grand_total","paid_amount","customer","change_amount","account_for_change_amount"]', order_by="creation desc", limit_page_length=1,
		)
		inv = invoices[0] if invoices else {}
		check("a Sales Invoice was created and SUBMITTED by this cashier at this till", inv.get("docstatus") == 1, inv)
		check("it has its Currency and Debit To", bool(inv.get("currency")) and bool(inv.get("debit_to")), inv)
		if TENDER:
			check("the sale had change, and it is paid in full by the cash handed over", inv.get("grand_total", 0) > 0 and abs((inv.get("paid_amount") or 0) - TENDER) < 0.01 and abs((inv.get("change_amount") or 0) - (TENDER - inv["grand_total"])) < 0.01, inv)
			check("the Account for Change Amount (a hidden field) filled itself", bool(inv.get("account_for_change_amount")), inv)
		else:
			check("it is fully paid", inv and inv.get("paid_amount") == inv.get("grand_total") and inv.get("grand_total", 0) > 0, inv)
		if CUSTOMER:
			check("the invoice is for the chosen customer", CUSTOMER.lower() in (inv.get("customer") or "").lower(), inv.get("customer"))
		payments = admin.request.get(f"{B}/api/resource/Sales Invoice/{inv.get('name')}").json().get("data", {}).get("payments", []) if inv else []
		check("paid in Cash", any(r.get("mode_of_payment") == "Cash" and r.get("amount") for r in payments), payments)
		check("stock at the till's warehouse went down by one", stock() == before - 1, (before, stock()))

		if inv.get("name"):  # leave stock and the ledger as found
			if inv.get("docstatus") == 1:
				admin.request.post(f"{B}/api/method/frappe.client.cancel", data={"doctype": "Sales Invoice", "name": inv["name"]})
			state = get(admin, "Sales Invoice", filters=f'[["name","=","{inv["name"]}"]]', fields='["docstatus"]')
			check("cleanup: the test sale is cancelled and stock is back", bool(state) and state[0]["docstatus"] == 2 and stock() == before, (state, before, stock()))
		br.close()


main()
print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED: ' + '; '.join(fails)}")
sys.exit(1 if fails else 0)
