"""Who can OPEN which desk workspace — checked over HTTP as real demo users.

Hiding a workspace from the sidebar is navigation only; this checks the server
itself refuses (PermissionError / HTTP 403) when someone requests it directly
by URL or API. Exit code 1 if any expectation fails.

Run (bench running on 8001):
    python3 apps/retail_store/retail_store/tests/workspace_access.py
"""
import json
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

BASE = "http://retail.localhost:8001"
PWD = "RetailDemo#2026"

RETAIL_ROLES_ONLY = [
	"cashier.downtown@demo.example",
	"cashier.mall@demo.example",
	"manager.downtown@demo.example",
	"wh.attendant@demo.example",
	"wh.manager@demo.example",
]
LOCKED = ["Accounting", "Selling", "Stock", "Buying", "Financial Reports", "Invoicing", "Payments", "Build"]
OPEN = ["Retail Store", "Home"]

# user -> workspaces they must be able to open (everything else in LOCKED must be refused)
EXPECT_OPEN = {
	"Administrator": set(LOCKED + OPEN),
	"owner@demo.example": set(LOCKED[:-1] + OPEN),  # everything but the developer "Build"
	"admin@demo.example": set(LOCKED[:-1] + OPEN),
	"accountant@demo.example": {"Accounting", "Financial Reports", "Invoicing", "Payments"} | set(OPEN),
}
for u in RETAIL_ROLES_ONLY:
	EXPECT_OPEN[u] = set(OPEN)


def session(user, pwd):
	jar = CookieJar()
	op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
	data = urllib.parse.urlencode({"usr": user, "pwd": pwd}).encode()
	op.open(urllib.request.Request(f"{BASE}/api/method/login", data=data)).read()
	return op


def status(op, url, form=None):
	data = urllib.parse.urlencode(form).encode() if form is not None else None
	req = urllib.request.Request(url, data=data)
	req.add_header("X-Frappe-CSRF-Token", "x")
	try:
		r = op.open(req)
		return r.status, r.read()
	except urllib.error.HTTPError as e:
		return e.code, e.read()


def run():
	failures = []
	print(f"{'user':34}{'workspace':20}{'page API':>9}{'doc API':>9}  expected")
	for user, should_open in EXPECT_OPEN.items():
		op = session(user, "admin" if user == "Administrator" else PWD)
		for ws in LOCKED + OPEN:
			page_code, _ = status(op, f"{BASE}/api/method/frappe.desk.desktop.get_desktop_page",
				{"page": json.dumps({"name": ws, "title": ws})})
			doc_code, _ = status(op, f"{BASE}/api/resource/Workspace/{urllib.parse.quote(ws)}")
			want = ws in should_open
			ok = (page_code == 200 and doc_code == 200) if want else (page_code == 403 and doc_code in (403, 404))
			print(f"{user:34}{ws:20}{page_code:>9}{doc_code:>9}  {'open' if want else 'BLOCK'} {'ok' if ok else '<-- FAIL'}")
			if not ok:
				failures.append((user, ws, page_code, doc_code, want))
	print(f"\n{len(failures)} failure(s)")
	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(run())
