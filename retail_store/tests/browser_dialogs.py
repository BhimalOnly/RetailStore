"""Dialog gallery in a real browser (the system-wide modal restyle, retail_store/public/css/dialogs.css + js/dialogs.js).

For every dialog type (message, confirm, prompt, "Select Currency" search, multi-select, New Customer quick entry,
plain form dialog, file uploader), in light and dark, at 1440x900 and 1366x768, it checks with numbers:
  * the dialog starts below the toolbar and ends inside the window, with header and footer on screen
  * the form inside is flat (no second white card), nothing overflows sideways
  * New Customer (Individual): no empty column, Email and Mobile share a row, fits 1440x900 without scrolling
and the stacked-dialog behaviour:
  * a message over a dialog sits clear below its header, takes focus, and Escape closes only the message (what was
    typed survives); a blocking (static) dialog ignores Escape
Screenshots land in ./shots/dialogs/.

Run:  /tmp/pw/bin/python browser_dialogs.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

B = "http://retail.localhost:8001"
OUT = "shots/dialogs"
os.makedirs(OUT, exist_ok=True)
results = []

CASES = {
	"message": "frappe.msgprint({title:'Missing Values Required',message:'Following fields have missing values:<br><br><ul><li>City</li></ul>',indicator:'red'})",
	"confirm": "frappe.confirm('Are you sure you want to delete this record? This cannot be undone.',()=>{})",
	"prompt": "frappe.prompt([{label:'Reason',fieldname:'r',fieldtype:'Data',reqd:1},{label:'Amount',fieldname:'a',fieldtype:'Currency'}],()=>{},'Enter details','Submit')",
	"select_currency": "new frappe.ui.form.LinkSelector({doctype:'Currency',target:{set_value:function(){},df:{options:'Currency'}},txt:'MUR'})",
	"multiselect": "new frappe.ui.form.MultiSelectDialog({doctype:'Item',target:{},setters:{item_group:''},add_filters_group:1,get_query(){return{filters:{disabled:0}}},action(){}})",
	"new_customer": "frappe.ui.form.make_quick_entry('Customer')",
	"form_dialog": "new frappe.ui.Dialog({title:'Change address',fields:[{label:'Address Line 1',fieldname:'a',fieldtype:'Data'},{label:'City',fieldname:'c',fieldtype:'Data'},{label:'Country',fieldname:'k',fieldtype:'Link',options:'Country'},{label:'Notes',fieldname:'n',fieldtype:'Small Text'}],primary_action_label:'Save',primary_action(){}}).show()",
	"uploader": "new frappe.ui.FileUploader({doctype:'Customer',docname:'DEMO Jane Shopper'})",
}

MEASURE = """()=>{
	const open=[...document.querySelectorAll('.modal.show')], m=open[open.length-1];
	if(!m) return null;
	const d=m.querySelector('.modal-dialog').getBoundingClientRect(), c=m.querySelector('.modal-content').getBoundingClientRect();
	const h=m.querySelector('.modal-header'), f=m.querySelector('.modal-footer'), b=m.querySelector('.modal-body');
	const fr=f&&getComputedStyle(f).display!=='none'?f.getBoundingClientRect():null;
	const page=m.querySelector('.form-page'), pg=page&&getComputedStyle(page);
	const emptyCols=[...m.querySelectorAll('.form-column')].filter(x=>getComputedStyle(x).display!=='none'&&!x.querySelector('.frappe-control:not(.hide-control)')).length;
	const email=m.querySelector('.frappe-control[data-fieldname=email_address]'), mobile=m.querySelector('.frappe-control[data-fieldname=mobile_number]');
	return {top:Math.round(c.top),bottom:Math.round(c.bottom),vh:window.innerHeight,left:Math.round(c.left),right:Math.round(c.right),vw:window.innerWidth,
		headerOn:h.getBoundingClientRect().top>=c.top-1&&h.getBoundingClientRect().bottom<=window.innerHeight,
		footerOn:!fr||fr.bottom<=window.innerHeight+1,
		flat:!pg||(pg.boxShadow==='none'&&(pg.backgroundColor==='rgba(0, 0, 0, 0)'||pg.backgroundColor==='transparent')),
		overflowX:b.scrollWidth>b.clientWidth+1, scrolls:b.scrollHeight>b.clientHeight+1, opacity:getComputedStyle(m.querySelector('.modal-dialog')).opacity,
		emptyCols, mailRow: email&&mobile?[Math.round(email.getBoundingClientRect().top),Math.round(mobile.getBoundingClientRect().top)]:null}}"""

CLOSE = "()=>{[...document.querySelectorAll('.modal.show')].forEach(m=>{try{$(m).modal('hide')}catch(e){}});$('.modal-backdrop').remove();$('body').removeClass('modal-open')}"


def check(name, ok, detail=""):
	results.append(bool(ok))
	print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


with sync_playwright() as p:
	br = p.chromium.launch()
	for vw, vh in ((1440, 900), (1366, 768)):
		ctx = br.new_context(viewport={"width": vw, "height": vh})
		page = ctx.new_page()
		errors = []
		page.on("pageerror", lambda e: errors.append(str(e)[:120]))
		ctx.request.post(f"{B}/api/method/login", data={"usr": "owner@demo.example", "pwd": "RetailDemo#2026"})
		page.goto(B + "/desk/customer")
		page.wait_for_selector(".page-head", timeout=60000)
		page.wait_for_timeout(3500)
		for theme in ("light", "dark"):
			page.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
			for name, js in CASES.items():
				tag = f"{vw}x{vh} {theme} {name}"
				page.evaluate(CLOSE)
				page.wait_for_timeout(400)
				page.evaluate("()=>{" + js + "}")
				page.wait_for_timeout(2400)
				m = page.evaluate(MEASURE)
				if not m:
					check(f"{tag}: opens", False)
					continue
				check(f"{tag}: starts below the toolbar (top {m['top']})", m["top"] >= 52, m)
				check(f"{tag}: ends inside the window ({m['bottom']} of {m['vh']})", m["bottom"] <= m["vh"] - 8, m)
				check(f"{tag}: header and footer both on screen", m["headerOn"] and m["footerOn"], m)
				check(f"{tag}: form is flat (no card inside the dialog)", m["flat"], m)
				check(f"{tag}: nothing overflows sideways, fully opaque", not m["overflowX"] and m["opacity"] == "1" and m["left"] >= 0 and m["right"] <= m["vw"], m)
				if name == "new_customer":
					check(f"{tag}: no empty column, Email and Mobile share a row", m["emptyCols"] == 0 and m["mailRow"] and m["mailRow"][0] == m["mailRow"][1], m)
					if (vw, vh) == (1440, 900):
						check(f"{tag}: fits without scrolling", not m["scrolls"], m)
					else:
						check(f"{tag}: scrolls inside, footer still on screen", m["footerOn"], m)
				page.screenshot(path=f"{OUT}/dialog-{vw}x{vh}-{theme}-{name}.png")

		# ---- stacked dialogs (light, this window size)
		page.evaluate("document.documentElement.setAttribute('data-theme','light')")
		page.evaluate(CLOSE)
		page.wait_for_timeout(400)
		page.evaluate("()=>{frappe.ui.form.make_quick_entry('Customer')}")
		page.wait_for_timeout(2500)
		page.fill('.modal.show input[data-fieldname="customer_name"]', "Stacked Probe")
		page.keyboard.press("Tab")
		qe_header = page.evaluate("()=>document.querySelector('.modal.show .modal-header').getBoundingClientRect().bottom")
		page.evaluate("()=>{frappe.msgprint({title:'Missing Values Required',message:'City',indicator:'red'})}")
		page.wait_for_timeout(1500)
		stack = page.evaluate("()=>{const o=[...document.querySelectorAll('.modal.show')];const t=frappe.ui.open_dialogs.filter(d=>d.$wrapper.hasClass('show')).pop().$wrapper[0];return {n:o.length,depth:t.getAttribute('data-rs-depth'),top:Math.round(t.querySelector('.modal-content').getBoundingClientRect().top),focusIn:t.contains(document.activeElement)}}")
		check(f"{vw}x{vh} stacked: a message opens over the dialog", stack["n"] == 2, stack)
		check(f"{vw}x{vh} stacked: it sits clear below the dialog's header (top {stack['top']} vs header bottom {round(qe_header)})", stack["top"] >= qe_header, (stack, qe_header))
		check(f"{vw}x{vh} stacked: keyboard focus is inside the message", stack["focusIn"], stack)
		page.screenshot(path=f"{OUT}/dialog-{vw}x{vh}-stacked.png")
		page.keyboard.press("Escape")
		page.wait_for_timeout(1000)
		after = page.evaluate("()=>({n:document.querySelectorAll('.modal.show').length,name:(document.querySelector('.modal.show input[data-fieldname=customer_name]')||{}).value})")
		check(f"{vw}x{vh} stacked: Escape closes only the message, what was typed survives", after["n"] == 1 and after["name"] == "Stacked Probe", after)
		page.keyboard.press("Escape")
		page.wait_for_timeout(1000)
		check(f"{vw}x{vh} stacked: a second Escape closes the dialog", page.evaluate("document.querySelectorAll('.modal.show').length") == 0)

		# ---- a blocking (static) dialog ignores Escape, and the message above it still closes first
		page.evaluate("()=>{window.__blk=new frappe.ui.Dialog({title:'Blocked',static:true,fields:[{fieldtype:'HTML',options:'<p>Must be answered.</p>'}]});window.__blk.show();frappe.msgprint('A message')}")
		page.wait_for_timeout(1500)
		page.keyboard.press("Escape")
		page.wait_for_timeout(900)
		n1 = page.evaluate("document.querySelectorAll('.modal.show').length")
		page.keyboard.press("Escape")
		page.wait_for_timeout(900)
		n2 = page.evaluate("document.querySelectorAll('.modal.show').length")
		check(f"{vw}x{vh} blocking dialog: Escape closes the message above it, then leaves the blocking one open", n1 == 1 and n2 == 1, (n1, n2))
		page.evaluate(CLOSE)
		check(f"{vw}x{vh}: no browser errors", not errors, errors[:2])
		ctx.close()
	br.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
