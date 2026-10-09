// Land retail staff on the Retail Store workspace, not Frappe's generic "desktop" screen
// (/desk, /desk/<app>/desktop) or a theme's home page. Only acts while the page is still
// on that generic screen at load time; the first real route (a deep link, a bookmark, or
// our redirect) switches it off, so the apps screen stays reachable afterwards.
(function () {
	let active = true;
	function check() {
		if (!active || !frappe.router || !frappe.boot) return;
		const route = frappe.get_route() || [];
		const first = route[0] || "";
		const generic =
			!first || first === "desktop" || first === "smart-home" || route[route.length - 1] === "desktop";
		if (!generic) {
			active = false;
			return;
		}
		const target = frappe.boot.user && frappe.boot.user.default_workspace;
		active = false;
		if (target && target.name === "Retail Store") {
			frappe.route_flags.replace_route = true;
			frappe.set_route("retail-store");
		}
	}
	$(document).on("page-change", check);
	$(function () {
		if (frappe.router && frappe.router.on) frappe.router.on("change", check);
	});
})();
