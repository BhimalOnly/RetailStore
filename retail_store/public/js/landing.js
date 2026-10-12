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

// The rail's top tile (and any other generic "home") sends people to Frappe's own home: the Setup
// shell for an owner, the Apps launcher (naming ERPNext / Frappe HR) for everyone else. Retail
// users have one home, the Retail Store workspace. System Manager keeps Frappe's home.
(function () {
	function retail_user() {
		return (
			frappe.boot &&
			frappe.boot.user &&
			frappe.boot.user.default_workspace &&
			frappe.boot.user.default_workspace.name === "Retail Store" &&
			!(frappe.user && frappe.user.has_role && frappe.user.has_role("System Manager"))
		);
	}
	function generic_home(route) {
		const last = String(route[route.length - 1] || "").toLowerCase();  // the Setup workspace routes as ["Workspaces", "Home"]
		return route.length > 0 && (last === "home" || last === "desktop" || route[0] === "smart-home");
	}
	// The theme's own home pages. frappe.set_route() back to Retail Store from one of these rewrites the address but
	// leaves the page on screen (same URL, different page), so these leave with a real navigation instead. They are
	// also closed server-side (roles.RESTRICTED_PAGES); this is what a retail user sees if they get here anyway.
	const THEME_PAGES = ["smart-home", "all-apps", "dashboard-view", "organizational-chart", "team-updates"];
	function redirect() {
		if (!retail_user() || !frappe.router) return;
		const route = frappe.get_route() || [];
		const visible_theme_page = THEME_PAGES.some((n) => {
			const el = document.getElementById("page-" + n);
			return el && el.offsetParent !== null;
		});
		const accounts = frappe.user.has_role("Accounts User") || frappe.user.has_role("Accounts Manager"); // keeps ERPNext's Dashboard links
		// a number card's raw Desk form (the home-page cards' "Edit"): System Manager authors those, nobody else opens them
		const number_card_form = (route[0] === "build" && route[1] === "number-card") || (route[0] === "Form" && route[1] === "Number Card");
		if ((THEME_PAGES.indexOf(route[0]) !== -1 && !(accounts && route[0] === "dashboard-view")) || visible_theme_page || number_card_form) {
			window.location.replace("/desk/retail-store");
			return;
		}
		if (!generic_home(route)) return;
		frappe.route_flags.replace_route = true;
		frappe.set_route("retail-store");
	}
	// the tile is an <a href="/desk/home">; take the click before it navigates
	document.addEventListener(
		"click",
		function (e) {
			const tile = e.target.closest && e.target.closest("#st-icon-rail .st-rail-brand");
			if (!tile || !retail_user()) return;
			e.preventDefault();
			e.stopImmediatePropagation();
			frappe.set_route("retail-store");
		},
		true
	);
	$(document).on("page-change", redirect);
	$(function () {
		if (frappe.router && frappe.router.on) frappe.router.on("change", redirect);
		// a page opened straight on /desk/setup/home routes before any of the events above fire: look a few times
		let tries = 0;
		const timer = setInterval(() => {
			redirect();
			if (++tries > 30) clearInterval(timer);
		}, 200);
	});
})();
