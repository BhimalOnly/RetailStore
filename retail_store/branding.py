"""Per-site branding.

Logo, brand colour and accent colour live in Retail Store Settings (a Single
doctype, so one value per site database). Nothing is hardcoded in the app, so
each client site carries its own brand on the same code.

Desk: colours are exposed as CSS custom properties (--rs-brand, --rs-accent)
and, only when "Apply Brand Colours to Desk" is on, mapped onto Desk's
--primary. No stylesheet is shipped, so a Desk theme app can be added later.
"""

import frappe
from frappe.utils import escape_html

DEFAULT_LOGO = "/assets/retail_store/images/retail-store-logo.svg"


def get_branding():
	if not frappe.db.exists("DocType", "Retail Store Settings"):
		return {}
	s = frappe.get_cached_doc("Retail Store Settings")
	return {
		"brand_name": s.brand_name or frappe.defaults.get_global_default("company") or "Retail Store",
		"logo": s.brand_logo or None,
		"favicon": s.brand_favicon or None,
		"brand_color": s.brand_color or None,
		"accent_color": s.accent_color or None,
		"apply_to_desk": bool(s.apply_brand_to_desk),
	}


def boot_session(bootinfo):
	branding = get_branding()
	bootinfo.retail_store_branding = branding
	# POS shows its Clock In / Out button only when HR is on and the user has an Employee record
	bootinfo.retail_store_clock = bool(
		"hrms" in frappe.get_installed_apps()
		and frappe.db.get_single_value("Retail Store Settings", "enable_hr")
		and frappe.session.user != "Guest"
		and frappe.db.exists("Employee", {"user_id": frappe.session.user, "status": "Active"})
	)
	# v16 desk shows the app tile's logo (top-left, apps screen), not Navbar Settings'
	# app_logo; the tile logo comes from a static hook, so swap in this site's logo.
	if branding.get("logo"):
		for app in bootinfo.get("app_data") or []:
			if app.get("app_name") == "retail_store":
				app["app_logo_url"] = branding["logo"]
				if branding.get("brand_name"):
					app["app_title"] = branding["brand_name"]


def update_website_context(context):
	branding = get_branding()
	context.retail_store_branding = branding
	if branding.get("favicon"):
		context.favicon = branding["favicon"]
	css_vars = "".join(
		f"{var}:{escape_html(branding[key])};"
		for var, key in (("--rs-brand", "brand_color"), ("--rs-accent", "accent_color"))
		if branding.get(key)
	)
	if css_vars:
		context.head_html = (context.get("head_html") or "") + f"<style>:root{{{css_vars}}}</style>"


def apply_branding(settings):
	"""Push the per-site logo/name into Frappe's own settings so login, navbar
	and website use it too. Clearing the logo restores the Frappe default."""
	navbar = frappe.get_single("Navbar Settings")
	if (navbar.app_logo or None) != (settings.brand_logo or None):
		navbar.app_logo = settings.brand_logo
		navbar.flags.ignore_permissions = True
		navbar.save()

	website = frappe.get_single("Website Settings")
	changed = False
	for field, value in (
		("app_logo", settings.brand_logo),
		# the public site's navbar logo and footer line (otherwise: plain "Home" text and "Powered by ERPNext")
		("banner_image", settings.brand_logo),
		("footer_powered", settings.brand_name),
		("favicon", settings.brand_favicon),
		("app_name", settings.brand_name),
	):
		if (website.get(field) or None) != (value or None):
			website.set(field, value)
			changed = True
	if changed:
		website.flags.ignore_permissions = True
		website.flags.ignore_mandatory = True
		website.save()


def has_app_permission():
	"""Show the Retail Store tile to anyone with a retail role (or System Manager)."""
	from retail_store.setup.roles import ROLES

	roles = set(frappe.get_roles())
	return bool(roles & (set(ROLES) | {"System Manager", "Accounts Manager"}))
