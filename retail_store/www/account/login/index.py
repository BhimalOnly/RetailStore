"""Shopper sign-in / sign-up at /account/login: Frappe's own login page in the storefront look.

/login is Solvronix Desk's staff page and stays untouched. This route reuses Frappe's login
controller (same form, same sign-up flow, same redirect-to handling) and only adds the body class
the storefront CSS keys on. Only linked to when the Online Store is on (storefront.shopper_login_url)."""

import frappe
from frappe.www.login import get_context as login_context

no_cache = 1


def get_context(context):
	from retail_store.storefront import store_is_on

	if not store_is_on():
		frappe.local.flags.redirect_location = "/login"
		raise frappe.Redirect
	login_context(context)
	context.title = frappe.get_website_settings("app_name") or context.get("title")
	context.body_class = "rs-shop-login"
	context.rs_shop_login = 1
	return context
