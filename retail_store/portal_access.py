"""Which portal pages a customer (Website User) may open, as ONE table that drives both the sidebar
and the access check.

ERPNext's portal lists staff-facing pages to every customer: Projects, Timesheets, Material Request,
Issues, Quotations, plus supplier pages. Disabling the sidebar entry only hides a link: the page
itself still opened for a shopper (/quotations, /timesheets, /rfq... returned 200, and /issues let them
file a support ticket nobody watches). Same lesson as the Desk workspaces (workspace_access.py): fix
the access, not just the visibility. So:

  * apply_portal_menu() (on settings save + migrate) enables a Portal Menu Item only when the page is
    allowed for its role, so the sidebar and the access rule can never disagree;
  * block_gated_pages() (before_request) refuses a gated route for Website Users with a 403.

Customers always get their orders, invoices, shipments and addresses. Everything else follows an
optional capability in Retail Store Settings (Support -> Issues, Projects -> Projects/Timesheets,
CRM -> Quotations, Buying -> the supplier pages, which also need the Supplier role). A route absent
from PORTAL (profile, cart, newsletters...) is not touched.
"""

import frappe
from frappe import _

ALWAYS = None  # open to the role whenever the page exists
NEVER = "never"  # no capability makes this useful on the portal

# (route prefix, Portal Menu Item title, role the page is for, capability that unlocks it)
PORTAL = [
	("/orders", "Orders", "Customer", ALWAYS),
	("/invoices", "Invoices", "Customer", ALWAYS),
	("/shipments", "Shipments", "Customer", ALWAYS),
	("/addresses", "Addresses", "Customer", ALWAYS),
	("/quotations", "Quotations", "Customer", "enable_crm"),
	("/issues", "Issues", "Customer", "enable_support"),
	("/project", "Projects", "Customer", "enable_projects"),
	("/timesheets", "Timesheets", "Customer", "enable_projects"),
	("/material-requests", "Material Request", "Customer", NEVER),
	("/rfq", "Request for Quotations", "Supplier", "enable_buying"),
	("/supplier-quotations", "Supplier Quotation", "Supplier", "enable_buying"),
	("/purchase-orders", "Purchase Orders", "Supplier", "enable_buying"),
	("/purchase-invoices", "Purchase Invoices", "Supplier", "enable_buying"),
]


def _capability_on(capability):
	if capability is ALWAYS:
		return True
	if capability == NEVER:
		return False
	return bool(frappe.get_cached_doc("Retail Store Settings").get(capability))


def page_allowed(role, capability, user_roles):
	"""A page is open when its capability is on AND the visitor holds the role it is meant for."""
	return _capability_on(capability) and role in user_roles


def apply_portal_menu():
	"""Sidebar entries follow the same rule as access: enabled only when the capability is on.
	(The role check is per visitor, so Portal Menu Item's own `role` column keeps doing that.)"""
	titles = {title: capability for _route, title, _role, capability in PORTAL}
	for row in frappe.get_all("Portal Menu Item", filters={"parent": "Portal Settings"}, fields=["name", "title", "enabled"]):
		if row.title in titles:
			want = 1 if _capability_on(titles[row.title]) else 0
			if row.enabled != want:
				frappe.db.set_value("Portal Menu Item", row.name, "enabled", want)
	frappe.cache.delete_key("portal_menu_items")


def block_gated_pages():
	"""before_request: 403 a gated portal page for a Website User who may not have it."""
	request = getattr(frappe.local, "request", None)
	if not request or request.method != "GET":
		return
	path = request.path.lower().rstrip("/")
	if frappe.session.user == "Guest":
		return
	for route, _title, role, capability in PORTAL:
		if path == route or path.startswith(route + "/"):
			break
	else:
		return
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "Website User":
		return  # staff keep full access to what their roles allow
	if not page_allowed(role, capability, frappe.get_roles()):
		frappe.throw(_("You are not permitted to access this page."), frappe.PermissionError)


GUEST_TO_LOGIN = ("/orders", "/invoices", "/shipments", "/addresses", "/me")


class GuestToShopperLogin:
	"""page_renderer: a signed-out visitor opening a customer page (e.g. a bookmarked /orders) goes to
	the shopper sign-in, not Frappe's bare "Not Permitted" page whose button leads to the STAFF /login."""

	def __init__(self, path=None, http_status_code=None):
		# the resolver may already have rewritten `path` (/orders -> "Sales Order"); judge the URL asked for
		# (no request when Frappe validates routes from a controller, e.g. Website Settings > Home Page)
		request = getattr(frappe.local, "request", None)
		self.path = "/" + (request.path if request else str(path or "")).strip("/ ")
		self.has_request = bool(request)
		self.http_status_code = 302

	def can_render(self):
		if not self.has_request or frappe.session.user != "Guest" or not any(self.path.lower() == p or self.path.lower().startswith(p + "/") for p in GUEST_TO_LOGIN):
			return False
		from retail_store.storefront import store_is_on

		return store_is_on()

	def render(self):
		from urllib.parse import quote

		from retail_store.storefront import SHOPPER_LOGIN

		frappe.flags.redirect_location = f"{SHOPPER_LOGIN}?redirect-to={quote(self.path)}"
		from frappe.website.page_renderers.redirect_page import RedirectPage

		return RedirectPage(self.path, 302).render()
