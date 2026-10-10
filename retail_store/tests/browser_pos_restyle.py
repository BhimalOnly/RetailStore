"""Browser check of the POS restyle (pos_restyle.css) AND that the restyled screen still works,
as the DEMO Downtown cashier: styles apply (light + dark), no Bootstrap .card in the POS, the variant
picker opens, a variant adds to the cart, and Checkout -> Cash -> Complete Order creates a submitted
Sales Invoice. Same Playwright setup as browser_pos.py. Run:
    /tmp/pw/bin/python browser_pos_restyle.py            (screenshots land in ./shots/restyle/)
Needs fresh demo tills + stock first:
    bench --site retail.localhost execute retail_store.demo.refresh_pos_openings
    bench --site retail.localhost execute retail_store.demo.restock_pos_test_items
Sells 1 DEMO-SNEAKER (42 / White) per run.
"""
import os
from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/restyle"
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


with sync_playwright() as p:
    br = p.chromium.launch()
    page = br.new_page(viewport={"width": 1400, "height": 860})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    api = page.context.request
    r = api.post(f"{B}/api/method/login", data={"usr": "cashier.downtown@demo.example", "pwd": "RetailDemo#2026"})
    check("cashier login", r.status == 200)

    page.goto(f"{B}/desk/point-of-sale")
    page.wait_for_selector(".item-wrapper", timeout=60000)
    page.wait_for_timeout(1500)

    css = lambda sel, prop: page.eval_on_selector(sel, f"e => getComputedStyle(e).{prop}")
    check("restyle stylesheet loaded", page.evaluate("[...document.styleSheets].some(s => (s.href||'').includes('pos_restyle'))"))
    check("item card is rounded", css(".item-wrapper", "borderRadius") == "14px", css(".item-wrapper", "borderRadius"))
    check("stock pill is a pill", css(".item-qty-pill .indicator-pill", "borderRadius") not in ("0px", ""))
    check("no Bootstrap .card in POS", page.evaluate("document.querySelectorAll('.point-of-sale-app .card').length") == 0)
    check("variant template cards still badged", page.locator(".item-wrapper.rs-template-card .rs-variant-badge").count() > 0)
    page.screenshot(path=f"{OUT}/1-light-grid.png")

    # dark mode: Frappe's resolved attribute is html[data-theme]
    page.evaluate("document.documentElement.setAttribute('data-theme','dark')")
    page.wait_for_timeout(400)
    card_bg = css(".item-wrapper", "backgroundColor")
    check("dark mode: card follows --card-bg (not white)", card_bg != "rgb(255, 255, 255)", card_bg)
    page.screenshot(path=f"{OUT}/2-dark-grid.png")
    page.evaluate("document.documentElement.setAttribute('data-theme','light')")

    # function: variant picker -> cart
    page.click('.item-wrapper[data-item-code="DEMO-SNEAKER"]')
    page.wait_for_selector(".modal.show .rs-opt", timeout=20000)
    check("variant picker opens", True)
    page.click('.modal.show .rs-opt[data-val="42"]')
    page.click('.modal.show .rs-opt[data-val="White"]')
    page.wait_for_timeout(400)
    page.locator(".modal.show").get_by_role("button", name="Add to Cart").click()
    page.wait_for_selector(".cart-item-wrapper", timeout=20000)
    page.wait_for_timeout(800)
    check("variant added to cart", page.locator(".cart-item-wrapper").count() == 1)
    check("cart row styled (radius)", css(".cart-item-wrapper", "borderRadius") == "12px", css(".cart-item-wrapper", "borderRadius"))
    check("qty rendered as pill", css(".cart-item-wrapper .item-qty > span", "borderRadius") not in ("0px", ""))
    page.screenshot(path=f"{OUT}/3-cart-light.png")
    check("checkout button is branded + bold", css(".cart-totals-section > .checkout-btn", "fontWeight") == "700")

    # function: checkout completes
    page.click(".cart-totals-section > .checkout-btn")
    page.wait_for_selector(".payment-container .mode-of-payment", timeout=20000)
    page.screenshot(path=f"{OUT}/4-payment.png")
    page.click('.payment-container .mode-of-payment[data-mode="cash"]')
    page.wait_for_timeout(600)
    page.click(".payment-container .submit-order-btn")
    page.wait_for_timeout(4000)
    page.screenshot(path=f"{OUT}/5-after-complete.png")
    # ERPNext asks "Permanently Submit <invoice>?" before submitting
    page.wait_for_selector(".modal.show", timeout=15000)
    inv_name = page.locator(".modal.show .modal-body").inner_text().strip().replace("Permanently Submit ", "").rstrip("?")
    page.locator(".modal.show").get_by_role("button", name="Yes").click()
    page.wait_for_timeout(4000)
    page.screenshot(path=f"{OUT}/6-order-complete.png")
    d = api.get(f"{B}/api/resource/Sales Invoice/{inv_name}").json().get("data", {})
    check("checkout completed: Sales Invoice submitted", d.get("docstatus") == 1, f"{inv_name}: {d.get('docstatus')}")
    check("no uncaught JS errors", not errors, "; ".join(errors[:3]))
    br.close()

print("\nFAILED: " + ", ".join(fails) if fails else "\nALL PASS")
raise SystemExit(1 if fails else 0)
