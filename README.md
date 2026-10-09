## Retail Store

A reusable, client-agnostic **retail starter pack** for Frappe / ERPNext
**version-16**. Clone it onto an isolated site per retail client (footwear,
grocery, apparel, ...). Nothing in the logic is industry-specific; client
specifics are applied later during onboarding.

Built and verified against **Frappe 16.51.0 / ERPNext 16.50.0** (Python 3.14).

---

### Install on a new client site

```bash
bench get-app retail_store <repo-url>        # or copy apps/retail_store
bench new-site <client>.localhost --install-app erpnext
bench --site <client>.localhost install-app retail_store
# finish the Setup Wizard (company, country, currency, fiscal year)
```

Install order doesn't matter: anything that needs a Company runs from the
`setup_wizard_complete` hook, and everything re-applies idempotently on
`bench migrate`.

What install does:

* creates the 7 custom roles and their default Role Permissions (all standard ERPNext roles are kept)
* adds the **Retail Material Request** approval workflow
* activates ERPNext's **Retail** domain (needed in v16 for the POS page to show in non-admin sidebars)
* ships the **Retail Store** app: Workspace, Sidebar and Dock
* hides optional modules (see Capabilities)
* after the Setup Wizard: creates the **Retail Rewards** loyalty program and sets the main / In-Transit warehouses

Configure everything per site at **Retail Store Settings** (`/desk/retail-store-settings`).

---

### 1. Roles

Roles are **granular and combinable**. A person can hold any mix
(e.g. Store Attendant + Store Cashier) and gets the union of rights; nothing
assumes one role per person. Bookkeeping uses ERPNext's own **Accounts
Manager**, unchanged.

| Role | Job |
|---|---|
| Store Attendant | Shop floor: helps customers, creates customers, drafts sales, requests stock |
| Store Cashier | Till: POS sales, payments, opening/closing the register |
| Store Manager | Runs a store: approves requests, posts/receives transfers, stock counts, cancels/amends sales |
| Warehouse Attendant | Picks/packs, drafts stock counts, requests stock; cannot post transfers |
| Warehouse Manager | Runs a warehouse: approves requests, posts transfers, maintains the catalogue |
| Store Owner | Everything retail, across all locations, including bulk transfers |
| Store Admin | Configures the system: locations, staff access, POS profiles, catalogue, branding, with no financial postings |

Default permissions (R read, W write, C create, S submit, X cancel, A amend, D delete):

| DocType | Store Attendant | Store Cashier | Store Manager | Warehouse Attendant | Warehouse Manager | Store Owner | Store Admin |
|---|---|---|---|---|---|---|---|
| Item | R | R | R | R | RWC | RWCD | RWC |
| Customer | RWC | RWC | RWC | – | – | RWCD | RWC |
| Sales Invoice | RWC | RWCS | RWCSXA | – | – | RWCSXA | – |
| POS Invoice | – | RWCS | RWCSXA | – | – | RWCSXA | – |
| POS Opening Entry | – | RWCS | RWCS | – | – | RWCS | – |
| POS Closing Entry | – | RWCS | RWCSXA | – | – | RWCSXA | – |
| Payment Entry | – | RWCS | RWCSXA | – | – | RWCSXA | – |
| Material Request | RWC | RWC | RWCSXA | RWC | RWCSXA | RWCSXAD | – |
| Stock Entry | R | R | RWCSXA | R | RWCSXA | RWCSXAD | – |
| Stock Reconciliation | – | – | RWCSXA | RWC | RWCSXA | RWCSXA | – |
| Item Price | R | R | RWC | R | RWCD | RWCD | RWCD |
| POS Profile | – | R | RW | – | – | RWCD | RWCD |
| Warehouse | R | R | R | R | R | RWC | RWC |
| Loyalty Program | R | R | R | R | R | RWC | RWC |
| Sales Order | – | – | RWCSXA | – | – | RWCSXA | – |
| Pick List | – | – | – | RWC | RWCSXA | RWCSXA | – |
| Retail Staff Access | – | – | – | – | – | RWCD | RWCD |

All roles can also read the master data the forms need (Item Group, Item
Attribute, UOM, Price List, Mode of Payment, Bin, ...). Report and page access
is added as **Custom Role** records, so ERPNext's own definitions stay
untouched: Stock Balance and Stock Projected Qty go to every retail role,
Stock Ledger to managers, Sales Register and Sales Analytics to Store Manager
and Owner, and the Point of Sale page to Cashier, Manager and Owner.

Store Admin deliberately has **no** user management: creating users and
assigning roles stays with System Manager.

**Adjusting per client:** use *Role Permissions Manager* as usual. The full
matrix is in `retail_store/setup/roles.py` (`PERMISSIONS`). Re-running setup
(migrate) only **adds** missing rights; it never removes something granted by
hand. To go back to the baseline, use Role Permissions Manager → *Reset to
Default*, then `bench --site <site> migrate`.

---

### 2. Location-based access

* Each store or warehouse is a **Warehouse** record.
* Open **Retail Staff Access** (one record per person), pick their warehouses
  (several for staff who rotate), and save. This writes **native User
  Permissions** (`allow = Warehouse`). Each one is scoped with *Applicable For*
  to the doctypes listed in *Retail Store Settings → Location Access*
  (default: Sales Invoice, POS Invoice, POS Profile, Sales Order, Delivery
  Note, Stock Reconciliation). POS Opening/Closing Entries are scoped to the
  POS Profiles of those warehouses, and the user is added to those profiles.
* Because the permissions are not "apply to all doctypes", they **don't block
  read-only reports**. Stock Balance stays company-wide by design.
* Users with no Retail Staff Access record, or with it unticked (e.g. Store
  Owner, Accounts Manager), are not restricted.
* Saving Retail Staff Access also gives the user the retail navigation (Module
  Profile + Retail Store as their default app). System Managers keep the full
  desk.

**Why Stock Entry and Material Request use a hook instead:** a native User
Permission requires *every* warehouse on a document to be allowed, so a
"Main → Store A" transfer would be invisible to Store A. For these two
doctypes, `permissions.py` shows a document when **any** of its warehouses is
the user's: header, item rows, the Material Request's destination, or the
*Final Destination* of an In-Transit move. It reads the same User Permission
records, so there is still one source of truth.

---

### 3. Stock transfers

| | Who | Steps |
|---|---|---|
| **(a) Routine replenishment** | any restricted staff → manager | 1. Staff create a **Material Request** (Material Transfer) for **their own** store only; the source defaults to the main warehouse. 2. *Submit for Approval*. 3. A Store/Warehouse Manager or Store Owner *Approves* (this submits it) or *Rejects* it. 4. The source warehouse manager uses *Create → Material Transfer (In Transit)*, which dispatches the goods into Goods In Transit. 5. The destination's manager opens that Stock Entry and uses *End Transit* to confirm receipt. |
| **(b) Owner bulk transfer** | Store Owner / managers | Create a **Stock Entry** directly with no request. Either move straight to one or more stores (one row per destination), or tick *Add to Transit* and set **Final Destination**: the receiving store then sees it and *End Transit* fills in the destination automatically. |

Only Warehouse Manager, Store Manager and Store Owner can create or submit
Stock Entries. Approval can be turned off in *Retail Store Settings → Stock
Transfers*.

> Workflow caveat: if a client enables ERPNext *auto re-order*
> (system-generated Material Requests), check it against the approval
> workflow before go-live, or turn approval off.

---

### 4. Item / variant pattern

* **Item Group** = category.
* **Item Attribute** = global, reusable value lists (Size, Colour, ...) shared across the catalogue.
* **Template item** (`Has Variants`) picks the values relevant to it, and ERPNext generates the sellable variants.

The demo shows this with two templates producing 12 variants (see DEMO DATA).

---

### POS: one card per product + Size/Colour picker

Stock ERPNext v16 POS lists **every variant as its own card** (its `get_items` query filters
`has_variants = 0`) and has no variant picker, so a shoe with 10 sizes × 5 colours would be
50 cards. With **Group Variants in POS** on (Retail Store Settings → Capabilities, default on):

* the POS shows **one card per template** ("6 options · up to ₹2,700"), with stock summed over
  its variants *at this till's warehouse*, plus every non-variant item as usual;
* tapping it opens a **picker** listing only that product's values, in the Item Attribute's order.
  Combinations that don't exist are disabled, out-of-stock values are struck through, and the
  chosen variant's code, price and stock here are shown. *Add to Cart* then goes through
  ERPNext's normal cart path (stock check, pricing rules, loyalty);
* **scanning a barcode** (or typing a serial, batch or exact variant code) skips the picker and
  adds that exact variant, which is ERPNext's own behaviour;
* text search matches the variant (code, name, POS search fields) or its template, and returns
  the product card.

How it is wired: `override_whitelisted_methods` swaps the POS `get_items` endpoint for
`retail_store.pos_variants.get_items`, and `page_js` adds `public/js/pos_variant_picker.js`,
which patches two methods on ERPNext's POS classes (`Controller.on_cart_update`,
`ItemSelector.get_item_html`). ERPNext's files are untouched. **After any ERPNext update**, run
`tests/browser_pos.py`; if the POS has changed underneath, untick the setting and stock behaviour
returns immediately.

### 5. Capabilities (Retail Store Settings → Capabilities)

**Always on:** Stock, Selling, Accounts, POS. Customers are created straight
from POS or Customer, with no CRM module needed.

**Loyalty Program: default ON.** It creates **Retail Rewards**: single tier,
1 point per 100 of currency spent, 1 point = 1 unit of currency, 1-year
expiry, and new customers are enrolled automatically on their first purchase.
Tune these numbers per client in the Loyalty Program form. Turning the toggle
off ends the program yesterday (history is kept); turning it back on re-opens
it.

**Optional (off by default):** CRM, Online Store / E-Commerce, Buying, HR,
Manufacturing, Quality, Support, Assets, Projects. When a toggle is off:

1. the module is in the **Retail Store Staff** Module Profile's blocked list
   (this hides it from every user with a retail role);
2. it is hidden site-wide from ERPNext's **Dock** (written as the Dock's
   *site layer*, so any manual arrangement is kept), and from Desktop Icons if
   the site uses v16's Desktop mode;
3. Store Owner is not granted its doctypes.

Ticking a toggle reverses all three. For CRM, Buying and E-Commerce it also
grants Store Owner the main doctypes (Lead/Opportunity, Supplier/PO/PR/PI,
Website Item). For other modules, give the person the matching standard
ERPNext role (e.g. *Manufacturing User*).

Two optional modules are **separate apps in v16** and must be installed first
(the toggle refuses to switch on and shows the commands):

* E-Commerce: `bench get-app webshop --branch version-16 && bench --site <site> install-app webshop`
* HR: `bench get-app hrms --branch version-16 && bench --site <site> install-app hrms`

---

### 6. Branding (per site)

Branding lives in *Retail Store Settings → Branding*: name, logo, favicon,
brand colour and accent colour. Because it's stored in the site's database,
each client site has its own branding while sharing the same code.

* The logo and name are pushed into Navbar Settings and Website Settings (login, website), and replace the Retail Store app tile's logo and title on the v16 apps screen and desk. Use a square mark.
* The colours are exposed as CSS variables `--rs-brand` / `--rs-accent`. With *Apply Brand Colours to Desk* on, they are also mapped onto Desk's `--primary`.
* No stylesheet or theme is shipped. If a Desk theme app is added later, turn off *Apply Brand Colours to Desk* and let the theme own colours.

**Client onboarding: collect BOTH logo formats up front.**

| File | Needed for | Rules |
|---|---|---|
| **Square mark** (SVG preferred, at least 256 px) | Desk icon rail tile, apps screen, login page, favicon | **Required.** Must be self-contained and readable on both light and dark backgrounds (give it its own solid tile or outline). With a Desk theme such as Solvronix Desk, ONE logo field feeds the 72 px rail tile *and* the login panel. |
| **Horizontal wordmark** | Print formats, website, email letterhead | Ask for it, but do not put it in the theme's logo field. Wide logos shrink to an unreadable smudge in the rail, and dark-coloured text vanishes on a dark login panel (both happened in the first Solvronix Desk trial). |

Also collect two brand colours (primary and accent) as hex. A theme's own tokens
(buttons, active menu, links) may still hold their default colour after the two
brand colours are set; check them in the theme editor. Known leftover on the demo
site: link text and dates are still the theme's default orange (to fix in a later
branding-token pass).

---

### 7. Navigation

The **Retail Store** app (apps screen, and the default landing page for
retail staff) has a Dock with Retail Store / Stock / Selling / Accounts. The
Retail Store sidebar has: Point of Sale, Sales Invoice, Customer, Loyalty
Program, Stock Balance, Material Request, Stock Entry, Stock Reconciliation,
Warehouse, the catalogue, the till documents, and Setup. Frappe trims each
user's sidebar to what their roles can open.

**Server-side allowlist (not a blocklist).** Hiding something from the sidebar is only
navigation in Frappe: any desk user could still open `/desk/accounting`, `/desk/setup/home`,
the module dashboards or the Chart of Accounts by URL or API. Found one at a time by
clicking through as a cashier, so the lock is now deny-by-default:

* **Workspaces** (`workspace_access.py`): only *Retail Store* is open to everyone. Every other
  workspace, **including ones added later** (CRM, Online Store, HR...), is refused (403) unless
  the user holds a back-office role (System Manager, Store Owner, Store Admin), a native
  ERPNext role for that module (e.g. Accounts User for Accounting), or a role set on the
  workspace. Roles are also written onto each workspace on every migrate. *Home* (Setup landing:
  Company, Users, stock value) and *Build* are not open to retail staff. Edit `NATIVE_ROLES` /
  `BACK_OFFICE` to change it.
* **Module dashboards** (Stock / Selling / Accounts `dashboard-view`): the Dashboard document
  and its `get_permitted_cards/charts` calls need a back-office or native module role.
* **Chart of Accounts:** till staff (Cashier, Manager) have `select` but not `read` on Account,
  so POS and Sales Invoice validation work but the chart cannot be browsed. The one lookup POS
  needs (`Account.account_currency` by exact name) is allowed by a narrow `get_value` override.
* **Stock figures:** `Bin` and `Stock Ledger Entry` are scoped to the user's own warehouses
  (ERPNext otherwise lets any reader see every location's quantities and stock value).
  Users without warehouse restrictions (Store Owner) see everything.

Known and accepted: every desk user can still list colleagues' *names/emails* (Frappe's
native User list; individual User records are 403) and read the Company record (POS needs it).
Retail staff work entirely from the Retail Store workspace. The rail matches that: Accounts,
Selling and Stock module buttons are blocked per user (via generated Module Profile variants,
e.g. "Retail Store Staff - Accounts/Selling/Stock") for any retail user without a back-office
or native module role, so the Dock never shows a button that answers "Not permitted". Store
Owner / Store Admin keep them. The sidebar's company-name header still links to Frappe's
generic desktop screen, which answers "Not permitted" for retail staff (cosmetic, unaddressed).

**Landing page.** Desk users open on *Retail Store*: `User.default_workspace` is
set for every desk user (backfilled on migrate, defaulted for new users), and
`public/js/landing.js` redirects the generic desktop screen to it on first load.
Do not use `boot.home_page` for this: it expects a Page, and for workspace slugs it
shows a "Not permitted" dialog to anyone without Page access.

---

### DEMO DATA (delete or replace per client)

```bash
bench --site <site> execute retail_store.demo.create_demo_data
bench --site <site> execute retail_store.demo.delete_demo_data
```

Everything is prefixed `DEMO` / `@demo.example`:

* **Warehouses:** DEMO Main Warehouse, DEMO Store Downtown, DEMO Store Mall, DEMO Store Airport
* **Catalogue:** item groups DEMO Footwear and DEMO Apparel; attributes DEMO Shoe Size (36–46), DEMO Apparel Size and DEMO Colour; templates DEMO-SNEAKER and DEMO-TEE (12 variants, each with a barcode; size 42 costs +200); plain item DEMO-TOTE
* **Till and sales:** 3 POS Profiles, 2 customers, opening stock
* **Users:** 9 users with mixed role combinations (password `RetailDemo#2026`), e.g. `cashier.mall@demo.example` is Attendant + Cashier and `floater@demo.example` rotates between Downtown and Airport

Deleting cancels and removes every transaction touching DEMO warehouses,
including their ledger rows. **Keep demo data on a demo site; never run
either command on a live client site.**

---

### Tests

```bash
# acceptance walk-through over the REST API as each demo user (site must be running)
env/bin/python apps/retail_store/retail_store/tests/e2e_section7.py http://<site>:<port>
# toggles, branding, navigation (restores settings afterwards)
bench --site <site> execute retail_store.tests.check_config.run
# real browser, as the Downtown cashier: grid -> picker -> cart -> barcode scan (needs Playwright)
python apps/retail_store/retail_store/tests/browser_pos.py <barcode>
# who may open which workspace, as each demo user, over HTTP. Enumerates EVERY workspace on the
# site (expects 403 for all but Retail Store for retail-only roles)
python3 apps/retail_store/retail_store/tests/workspace_access.py
```

POS refuses an opening entry from a previous day ("Outdated POS Opening Entry"), so
demo tills go stale overnight. Refresh them (closes yesterday's, opens today's):
`bench --site <site> execute retail_store.demo.refresh_pos_openings`.
`browser_pos.py` also sells one unit per run and fails with a disabled "Add to Cart" once
Downtown's test variants hit zero; top up with
`bench --site <site> execute retail_store.demo.restock_pos_test_items`.

---

### Messaging extension point (planned, not built)

WhatsApp/SMS will use Meta's **Tech Provider** model: each client keeps their
own WhatsApp Business Account, and the tech provider sends on their behalf.
Planned shape: a separate app (or a `messaging` module here) that

* adds per-site credentials to a settings doctype (WABA ID, phone number ID, token reference), never shared across clients;
* listens through `doc_events` (Sales Invoice `on_submit` for receipts, Loyalty Point Entry `after_insert` for points balance, Material Request workflow changes for staff alerts);
* sends via a background job (`frappe.enqueue`) so the till never waits on Meta.

Nothing in this app sends messages today. `hooks.py` marks the spot.

---

### ERPNext v16 notes (vs older designs)

* **POS posts Sales Invoices directly** (POS Settings → *Invoice Type* defaults to Sales Invoice), so stock and loyalty points update when the sale is made rather than at closing. High-volume clients can switch to POS Invoice.
* The **Point of Sale page is restricted to the "Retail" domain**: without it, POS silently disappears from non-admin sidebars. Install activates it.
* **Navigation redesign:** Apps screen → per-app **Dock** → per-module **Sidebar** → Workspace. Sites default to *Apps* mode, which has no Desktop Icon rows. The Dock has app, site and user layers.
* **E-commerce** (`webshop`) and **HR** (`hrms`) are separate apps.
* **Stock Balance is a prepared report:** it runs in the background, and an API call returns no rows until the job finishes.
* `has_permission` hooks must return `True` explicitly; `None` counts as a denial.
* Saving a **Module Profile** queues a job and locks the document, and its `update_all_users` skips users who block nothing. This app writes the rows directly and syncs users itself.
* **Material Request:** transfer progress lives in `status` / `transfer_status`, not a `per_transferred` field.
* **POS has no variant grouping or picker** (templates are excluded from its item list); this app adds one.
* POS reads **Stock Settings** on load, which stock ERPNext grants only to Sales User and Stock Manager; without it a custom cashier role gets a "No permission for Stock Settings" popup. The till roles here get read access.
* The POS page script loads its bundle asynchronously, so a `page_js` patch must retry until `erpnext.PointOfSale.*` exists.
* `frappe.db.get_single_value` returns **0, not None**, for a Check field on a Single that was never saved, so a setting added in a later release reads as "off". Setup writes declared defaults for missing values.
* The new desk shows the **app tile's logo** (from `add_to_apps_screen`), not Navbar Settings' logo. This app swaps in the per-site brand logo at boot; use a square mark.
* Tests: use `frappe.tests.IntegrationTestCase` (`FrappeTestCase` is deprecated).

### License

MIT
