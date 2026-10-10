// Public site: open the shop in GRID view the first time (the storefront look is designed for it).
// Webshop has no setting for this: all-products/index.js reads localStorage "product_view" and falls
// back to "List View". Seeding the key here (only when the shopper has never chosen) sets the default
// without editing the webshop app; a shopper's own list/grid choice is stored by webshop and respected.
try {
	if (!localStorage.getItem("product_view")) localStorage.setItem("product_view", "Grid View");
} catch (e) {
	/* storage blocked: webshop falls back to its own default */
}
