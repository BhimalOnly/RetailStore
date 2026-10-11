"""Who can OPEN which desk workspace — checked over HTTP as real demo users.

Hiding a workspace from the sidebar is navigation only; this checks the server
itself refuses (PermissionError / HTTP 403) when someone requests it directly
by URL or API. Exit code 1 if any expectation fails.

Every workspace that exists on the site is checked (enumerated, not a fixed list), so a
workspace added later is covered automatically. Allowlist: retail-only roles may open
ONLY "Retail Store".

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

RETAIL_ONLY = [
	"cashier.downtown@demo.example",
	"cashier.mall@demo.example",
	"floater@demo.example",
	"manager.downtown@demo.example",
	"wh.attendant@demo.example",
	"wh.manager@demo.example",
]
ALWAYS_OPEN = {"Retail Store"}
SYSTEM_MANAGER_ONLY = {"Build", "Users"}  # everyone back-office except these is allowed the rest
# Optional-capability workspaces: Store Owner holds their grants, Store Admin does not.
OWNER_ONLY = {"Payroll", "CRM", "Buying", "Assets", "Projects", "Manufacturing", "Quality", "Support"}
ACCOUNTANT = {"Accounting", "Financial Reports", "Invoicing", "Payments", "Assets"}


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


def all_workspaces():
	op = session("Administrator", "admin")
	code, body = status(op, f"{BASE}/api/resource/Workspace?limit_page_length=1000&fields=%5B%22name%22%5D")
	assert code == 200, code
	return sorted(d["name"] for d in json.loads(body)["data"])


def expected_open(user, workspaces):
	everything = set(workspaces)
	if user == "Administrator":
		return everything
	if user == "owner@demo.example":
		return everything - SYSTEM_MANAGER_ONLY
	if user == "admin@demo.example":
		return everything - SYSTEM_MANAGER_ONLY - OWNER_ONLY
	if user == "accountant@demo.example":
		return (ACCOUNTANT | ALWAYS_OPEN) & everything
	return ALWAYS_OPEN & everything


def run():
	workspaces = all_workspaces()
	print(f"{len(workspaces)} workspaces on site: {', '.join(workspaces)}\n")
	users = ["Administrator", "owner@demo.example", "admin@demo.example", "accountant@demo.example"] + RETAIL_ONLY
	failures = []
	for user in users:
		op = session(user, "admin" if user == "Administrator" else PWD)
		want_open = expected_open(user, workspaces)
		bad = []
		for ws in workspaces:
			page_code, _ = status(op, f"{BASE}/api/method/frappe.desk.desktop.get_desktop_page",
				{"page": json.dumps({"name": ws, "title": ws})})
			doc_code, _ = status(op, f"{BASE}/api/resource/Workspace/{urllib.parse.quote(ws)}")
			want = ws in want_open
			ok = (page_code == 200 and doc_code == 200) if want else (page_code == 403 and doc_code in (403, 404))
			if not ok:
				bad.append((ws, page_code, doc_code, "should open" if want else "should BLOCK"))
		print(f"{user:34} opens {len(want_open):>2}/{len(workspaces)}  {'ok' if not bad else 'FAIL'}")
		for b in bad:
			print(f"    {b[0]:22} page={b[1]} doc={b[2]}  {b[3]}")
		failures += [(user,) + b for b in bad]
	print(f"\n{len(failures)} failure(s)")
	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(run())
