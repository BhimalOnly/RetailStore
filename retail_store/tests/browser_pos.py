"""Browser check of the POS variant picker, as the DEMO Downtown cashier.

Catches an ERPNext update that changes the POS screen under pos_variant_picker.js.
Needs Playwright + Chromium in any Python env (not the bench env), e.g.:
    python3 -m venv /tmp/pw && /tmp/pw/bin/pip install playwright && /tmp/pw/bin/playwright install chromium-headless-shell
    (WSL without sudo: missing libnspr4/libnss3/libasound2 can be fetched with `apt-get download`
     and unpacked with `dpkg-deb -x`, then exported via LD_LIBRARY_PATH.)
Run:  /tmp/pw/bin/python browser_pos.py <barcode-of-DEMO-TEE-M-NAVY>
Screenshots land in ./shots/.
"""
import os
import sys, time
from playwright.sync_api import sync_playwright
B = "http://retail.localhost:8001"
OUT = "shots"
os.makedirs(OUT, exist_ok=True)
BARCODE = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch()
    page = br.new_page(viewport={"width": 1400, "height": 860})
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text}") if m.type in ("error",) else None)
    r = page.context.request.post(f"{B}/api/method/login", data={"usr": "cashier.downtown@demo.example", "pwd": "RetailDemo#2026"})
    print("login", r.status)
    page.goto(f"{B}/desk/retail-store"); page.wait_for_timeout(3000)
    page.screenshot(path=f"{OUT}/1-cashier-home.png")
    page.goto(f"{B}/desk/point-of-sale")
    page.wait_for_selector(".item-wrapper", timeout=60000); page.wait_for_timeout(1500)
    page.screenshot(path=f"{OUT}/2-pos-grid.png")
    print("cards:", page.eval_on_selector_all(".item-wrapper", "els => els.map(e => e.dataset.itemCode)"))
    page.click('.item-wrapper[data-item-code="DEMO-SNEAKER"]')
    page.wait_for_selector(".modal.show .rs-opt", timeout=20000); page.wait_for_timeout(500)
    page.screenshot(path=f"{OUT}/3-picker-open.png")
    page.click('.modal.show .rs-opt[data-val="42"]')
    page.click('.modal.show .rs-opt[data-val="White"]'); page.wait_for_timeout(400)
    page.screenshot(path=f"{OUT}/4-picker-chosen.png")
    page.locator(".modal.show").get_by_role("button", name="Add to Cart").click()
    page.wait_for_timeout(2500)
    page.screenshot(path=f"{OUT}/5-cart.png")
    print("cart:", page.eval_on_selector_all(".cart-item-wrapper", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())"))
    page.fill(".search-field input", BARCODE); page.wait_for_timeout(1500)
    page.keyboard.press("Enter"); page.wait_for_timeout(2500)
    page.screenshot(path=f"{OUT}/6-after-barcode.png")
    print("cart after scan:", page.eval_on_selector_all(".cart-item-wrapper", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())"))
    print("modal open after scan:", page.locator(".modal.show").count())
    print("console errors:", logs[:5])
    br.close()
