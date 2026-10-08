app_name = "retail_store"
app_title = "Retail Store"
app_publisher = "bhimall"
app_description = "Reusable retail starter pack for ERPNext (stores, warehouses, POS, loyalty)"
app_email = "bhimalonly@gmail.com"
app_license = "mit"

required_apps = ["erpnext"]

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
app_include_js = "/assets/retail_store/js/retail_store.js"

# POS: one card per product template + Size/Colour picker (see pos_variants.py).
# Toggle: Retail Store Settings > Capabilities > "Group Variants in POS".
page_js = {"point-of-sale": "public/js/pos_variant_picker.js"}
override_whitelisted_methods = {
	"erpnext.selling.page.point_of_sale.point_of_sale.get_items": "retail_store.pos_variants.get_items",
}

boot_session = "retail_store.branding.boot_session"
update_website_context = "retail_store.branding.update_website_context"

# Installation
# ------------
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
}

has_permission = {
	"Stock Entry": "retail_store.permissions.stock_entry_has_permission",
	"Material Request": "retail_store.permissions.material_request_has_permission",
}

# Document Events
# ---------------
doc_events = {
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
