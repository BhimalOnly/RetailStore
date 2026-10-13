app_name = "retail_store"

app_title = "Retail Store"
app_publisher = "bhimall"
app_description = "Reusable retail starter pack for ERPNext (stores, warehouses, POS, loyalty)"
app_email = "bhimalonly@gmail.com"
app_license = "mit"

required_apps = ["erpnext"]

from retail_store.hr_doctypes import EMPLOYEE_FIELD  # noqa: E402  (permission hooks below)

# Apps screen / navigation
# ------------------------
# The logo is resolved per site from Retail Store Settings (see branding.py),
# so the same app code can carry a different brand on every client site.
add_to_apps_screen = [
	{
		"name": "retail_store",
		"logo": "/assets/retail_store/images/retail-store-logo.svg",
		"title": "Retail Store",
		"route": "/desk/retail-store",
		"has_permission": "retail_store.branding.has_app_permission",
	}
]

# Includes in <head>
# ------------------
# Only sets CSS custom properties from per-site config. It never ships a theme,
# so a Desk theme app can be added later without conflict (turn off
# "Apply Brand Colours to Desk" in Retail Store Settings if the theme app owns colours).
# Public site (storefront/cart/orders) brand skin, driven by the per-site brand colours
web_include_css = "/assets/retail_store/css/storefront.css?v=24"
web_include_js = [
	"/assets/retail_store/js/storefront.js?v=11",
	"/assets/retail_store/js/shop_ui.js?v=3",
]
# POS item cards + cart restyle (visual only, token-driven; loads after solvronix_desk per apps.txt)
app_include_css = ["/assets/retail_store/css/pos_restyle.css?v=12", "/assets/retail_store/css/dialogs.css?v=12"]
app_include_js = ["/assets/retail_store/js/retail_store.js?v=10", "/assets/retail_store/js/landing.js?v=7", "/assets/retail_store/js/home_cards.js?v=1", "/assets/retail_store/js/customer_quick_entry.js?v=2", "/assets/retail_store/js/dialogs.js?v=2"]

# POS: one card per product template + Size/Colour picker (see pos_variants.py).
# Toggle: Retail Store Settings > Capabilities > "Group Variants in POS".
page_js = {"point-of-sale": "public/js/pos_variant_picker.js"}
doctype_js = {"POS Closing Entry": "public/js/pos_closing_entry.js"}
override_whitelisted_methods = {
	"frappe.desk.desk_page.getpage": "retail_store.workspace_access.getpage",
	"frappe.utils.change_log.get_versions": "retail_store.navigation.get_versions",
	# Attribute filters (colour, size) on a variant shop: see storefront._items_with_attributes
	"webshop.webshop.api.get_product_filter_data": "retail_store.storefront.get_product_filter_data",
	"webshop.webshop.shopping_cart.cart.get_cart_quotation": "retail_store.storefront.get_cart_quotation",
	# removing the last cart line crashes webshop's update_cart (see storefront.update_cart)
	"webshop.webshop.shopping_cart.cart.update_cart": "retail_store.storefront.update_cart",
	# ...and the variant picker's stock for a variant (webshop reads a Website Item the variant lacks)
	"webshop.webshop.variant_selector.utils.get_next_attribute_and_values": "retail_store.storefront.get_next_attribute_and_values",
	# the App rail shows the Retail Store app only, except to System Manager (navigation.py)
	"solvronix_desk.api.get_workspaces": "retail_store.navigation.get_workspaces",
	"erpnext.selling.page.point_of_sale.point_of_sale.get_items": "retail_store.pos_variants.get_items",
	# Refuse (403) workspaces the user's roles don't allow, not just hide them.
	"frappe.client.get_value": "retail_store.permissions.get_value",
	"frappe.desk.desktop.get_desktop_page": "retail_store.workspace_access.get_desktop_page",
	"frappe.desk.doctype.dashboard.dashboard.get_permitted_cards": "retail_store.workspace_access.get_permitted_cards",
	"frappe.desk.doctype.dashboard.dashboard.get_permitted_charts": "retail_store.workspace_access.get_permitted_charts",
}

boot_session = ["retail_store.branding.boot_session", "retail_store.navigation.boot_session"]
# A customer may open only the portal pages their store has switched on (portal_access.py)
page_renderer = ["retail_store.portal_access.GuestToShopperLogin"]
before_request = ["retail_store.portal_access.block_gated_pages"]
update_website_context = [
	"retail_store.branding.update_website_context",
	"retail_store.storefront.shopper_login_url",
	"retail_store.storefront.hide_pay_link_for_offline_gateway",
	"retail_store.storefront.readable_order_items",
]

# Installation
# ------------
before_install = "retail_store.home.before_install"
after_install = "retail_store.install.after_install"
after_migrate = "retail_store.install.after_migrate"
setup_wizard_complete = "retail_store.install.after_setup_wizard"
before_uninstall = "retail_store.install.before_uninstall"

# Permissions
# -----------
# Stock Entry and Material Request move goods BETWEEN locations, so a plain
# User Permission (which ANDs every warehouse field) would hide a transfer from
# the receiving store. These hooks show the document when ANY of its warehouses
# belongs to the user. Other transactional doctypes use native User Permissions.
permission_query_conditions = {
	"Stock Entry": "retail_store.permissions.stock_entry_query_conditions",
	"Material Request": "retail_store.permissions.material_request_query_conditions",
	"Bin": "retail_store.permissions.bin_query_conditions",
	"Customer": "retail_store.storefront.customer_query_conditions",
	"Dashboard": "retail_store.workspace_access.dashboard_query_conditions",
	"Stock Ledger Entry": "retail_store.permissions.stock_ledger_entry_query_conditions",
	# HR: managers see their stores' people, everyone else only themselves (hr.py)
	**{dt: "retail_store.hr.query_conditions" for dt in EMPLOYEE_FIELD},
}

has_permission = {
	"Workspace": "retail_store.workspace_access.has_permission",
	"Dashboard": "retail_store.workspace_access.dashboard_has_permission",
	"Stock Entry": "retail_store.permissions.stock_entry_has_permission",
	"Material Request": "retail_store.permissions.material_request_has_permission",
	"Bin": "retail_store.permissions.bin_has_permission",
	"Customer": "retail_store.storefront.customer_has_permission",
	"Stock Ledger Entry": "retail_store.permissions.stock_ledger_entry_has_permission",
	**{dt: "retail_store.hr.has_permission" for dt in EMPLOYEE_FIELD},
}

# Document Events
# ---------------
doc_events = {
	"Quotation": {
		"before_validate": "retail_store.storefront.set_online_order_warehouse",
	},
	# webshop's place_order re-reads each line's warehouse from Website Item(variant), blank for variants
	"Sales Order": {
		"before_validate": "retail_store.storefront.set_online_order_warehouse",
		"on_submit": "retail_store.messaging.events.order_submitted",
	},
	"Delivery Note": {
		"on_submit": "retail_store.messaging.events.delivery_submitted",
	},
	"Website Item": {
		"validate": "retail_store.storefront.default_thumbnail",
	},
	"Customer": {
		"before_validate": "retail_store.setup.company.fill_customer_defaults",
		"validate": "retail_store.messaging.consent.stamp_consent",
	},
	"User": {
		"validate": "retail_store.workspace_access.set_default_landing",
	},
	"Material Request": {
		"validate": "retail_store.stock_transfer.validate_material_request",
	},
	"Stock Entry": {
		"before_validate": "retail_store.stock_transfer.set_final_destination_on_receipt",
		"validate": "retail_store.stock_transfer.validate_stock_entry",
	},
	"Sales Invoice": {
		"validate": "retail_store.location.set_header_warehouse",
	},
	"POS Invoice": {
		"validate": "retail_store.location.set_header_warehouse",
	},
	"POS Profile": {
		"on_update": "retail_store.location.resync_users_for_pos_profile",
	},
	"Employee": {
		"validate": "retail_store.hr.employee_validate",
	},
}

# Customer messages: retry what failed for a reason worth retrying (retail_store/messaging/engine.py)
scheduler_events = {
	"cron": {"*/5 * * * *": ["retail_store.messaging.engine.retry_due"]},
}

# Testing
# -------
before_tests = "retail_store.install.before_tests"

# Extension points (not built yet)
# --------------------------------
# WhatsApp / SMS: see README "Messaging extension point". Planned as a separate
# app or module that listens to doc_events (Sales Invoice on_submit, Loyalty
# Point Entry after_insert) and sends via the client's own WhatsApp Business
# Account through a Meta Tech Provider. Nothing here sends messages today.
