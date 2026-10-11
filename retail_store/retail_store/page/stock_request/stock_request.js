// Request Stock: the one plain screen shop-floor staff use to ask for stock from the main warehouse,
// follow their requests and (when the owner has allowed it) confirm a delivery. No Desk forms.
// Server side: retail_store.stock_request.

frappe.pages["stock-request"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Request Stock"), single_column: true });
	const esc = frappe.utils.escape_html;
	const call = (method, args) => frappe.call({ method: "retail_store.stock_request." + method, args, type: "POST" }).then((r) => r.message);
	const $root = $(`<div class="rs-sr"></div>`).appendTo(page.main);
	$(`<style>
		.rs-sr{max-width:640px;margin:24px auto}
		.rs-sr h4{margin:28px 0 10px;font-size:var(--text-lg);font-weight:600}
		.rs-sr .rs-card{border:1px solid var(--border-color);border-radius:var(--border-radius-lg,12px);padding:16px;background:var(--card-bg,#fff)}
		.rs-sr .rs-row{display:flex;gap:10px;align-items:center;padding:8px 0;border-top:1px solid var(--border-color)}
		.rs-sr .rs-row:first-child{border-top:0}
		.rs-sr .rs-row .rs-name{flex:1}
		.rs-sr .rs-row .rs-sub{color:var(--text-muted);font-size:var(--text-sm)}
		.rs-sr input.rs-qty{width:80px;text-align:center}
		.rs-sr .rs-hits{margin-top:6px}
		.rs-sr .rs-hit{display:flex;justify-content:space-between;padding:8px 10px;border-radius:8px;cursor:pointer}
		.rs-sr .rs-hit:hover{background:var(--control-bg,#f3f3f3)}
		.rs-sr .rs-pill{display:inline-block;padding:2px 10px;border-radius:999px;background:var(--control-bg,#f3f3f3);font-size:var(--text-sm)}
		.rs-sr .rs-send{width:100%;margin-top:14px;padding:12px;border-radius:999px}
		.rs-sr .rs-empty{color:var(--text-muted)}
	</style>`).appendTo($root);
	const $new = $(`<div></div>`).appendTo($root);
	const $mine = $(`<div></div>`).appendTo($root);
	const $in = $(`<div></div>`).appendTo($root);
	let ctx = null;
	let cart = [];

	function renderNew() {
		if (!ctx.locations.length) {
			$new.html(`<p class="rs-empty">${__("No location is set up for you. Ask the store owner.")}</p>`);
			return;
		}
		const loc = $new.find(".rs-loc").val() || ctx.locations[0];
		$new.html(`
			<h4>${__("What does your shop need?")}</h4>
			<div class="rs-card">
				<div class="form-group" ${ctx.locations.length > 1 ? "" : 'style="display:none"'}>
					<label class="control-label">${__("For")}</label>
					<select class="form-control rs-loc">${ctx.locations.map((l) => `<option ${l === loc ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
				</div>
				<input type="text" class="form-control rs-find" placeholder="${__("Search a product by name or code")}">
				<div class="rs-hits"></div>
				<div class="rs-cart mt-3"></div>
				<button class="btn btn-primary rs-send" ${cart.length ? "" : "disabled"}>${__("Send request")}</button>
				<p class="rs-sub mt-2 text-muted">${ctx.source ? __("Stock comes from {0}. A manager approves the request first.", [esc(ctx.source)]) : ""}</p>
			</div>`);
		const $hits = $new.find(".rs-hits");
		const search = frappe.utils.debounce(() => {
			const txt = $new.find(".rs-find").val();
			if (!txt) return $hits.empty();
			call("search_products", { txt, location: $new.find(".rs-loc").val() }).then((items) => {
				$hits.html(items.length ? items.map((i) => `<div class="rs-hit" data-code="${esc(i.name)}" data-name="${esc(i.item_name)}">
						<span>${esc(i.item_name)}</span><span class="text-muted">${i.here !== undefined ? __("{0} here", [i.here]) : ""}</span></div>`).join("")
					: `<div class="rs-empty p-2">${__("No product found")}</div>`);
			});
		}, 250);
		$new.find(".rs-find").on("input", search);
		$hits.on("click", ".rs-hit", function () {
			const code = $(this).data("code");
			const line = cart.find((c) => c.item_code === code);
			if (line) line.qty += 1;
			else cart.push({ item_code: code, name: $(this).data("name"), qty: 1 });
			renderNew();
			$new.find(".rs-find").focus();
		});
		$new.find(".rs-loc").on("change", () => renderNew());
		const $cart = $new.find(".rs-cart");
		cart.forEach((c, i) => {
			$(`<div class="rs-row"><div class="rs-name">${esc(c.name)}</div>
				<input type="number" min="1" class="form-control rs-qty" value="${c.qty}">
				<button class="btn btn-default btn-xs rs-x">&times;</button></div>`)
				.appendTo($cart)
				.on("input", ".rs-qty", function () { c.qty = parseFloat($(this).val()) || 0; })
				.on("click", ".rs-x", () => { cart.splice(i, 1); renderNew(); });
		});
		$new.find(".rs-send").on("click", function () {
			$(this).prop("disabled", true);
			call("send_request", { location: $new.find(".rs-loc").val(), rows: JSON.stringify(cart) })
				.then(() => {
					frappe.show_alert({ message: __("Request sent"), indicator: "green" });
					cart = [];
					load();
				})
				.catch(() => renderNew());
		});
	}

	function renderMine() {
		$mine.html(`<h4>${__("Your requests")}</h4><div class="rs-card">${
			ctx.requests.length
				? ctx.requests.map((r) => `<div class="rs-row"><div class="rs-name">
					${r.items.map((i) => `${esc(i.item_name)} × ${i.qty}`).join(", ")}
					<div class="rs-sub">${frappe.datetime.str_to_user((r.creation || "").slice(0, 10))}</div></div>
					<span class="rs-pill">${esc(r.state)}</span></div>`).join("")
				: `<span class="rs-empty">${__("Nothing requested yet.")}</span>`
		}</div>`);
	}

	function renderIncoming(list) {
		if (!ctx.can_receive) return $in.empty();
		$in.html(`<h4>${__("Deliveries on their way")}</h4><div class="rs-card">${
			list.length
				? list.map((d) => `<div class="rs-row"><div class="rs-name">
					${d.items.map((i) => `${esc(i.item_name)} × ${i.left_qty}`).join(", ")}
					<div class="rs-sub">${esc(d.destination || "")}</div></div>
					<button class="btn btn-primary btn-sm rs-got" data-entry="${esc(d.name)}">${__("Received")}</button></div>`).join("")
				: `<span class="rs-empty">${__("Nothing is on its way.")}</span>`
		}</div>`);
		$in.find(".rs-got").on("click", function () {
			$(this).prop("disabled", true);
			call("receive", { entry: $(this).data("entry") })
				.then(() => { frappe.show_alert({ message: __("Stock received"), indicator: "green" }); load(); })
				.catch(() => load());
		});
	}

	function load() {
		call("context").then((c) => {
			ctx = c;
			renderNew();
			renderMine();
			if (c.can_receive) call("incoming").then(renderIncoming);
			else $in.empty();
		});
	}
	wrapper.load = load;
	load();
};

frappe.pages["stock-request"].on_page_show = function (wrapper) {
	if (wrapper.load) wrapper.load();
};
