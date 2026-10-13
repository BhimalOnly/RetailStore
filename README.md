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
| Store Admin | Configures day-to-day operations: locations, staff access, POS profiles, catalogue, pricing, loyalty tuning, with no financial postings. **Not** branding or Capabilities (System Manager only, see sections 5 and 6) |

**Retail Store Settings is split by field level (permlevel), not by doctype:**

| Part of Retail Store Settings | System Manager | Store Owner | Store Admin | Everyone else |
|---|---|---|---|---|
| Operational (permlevel 0): Stock Transfers tab (main / in-transit warehouse, request approval), Location Access, Loyalty program and Group Variants in POS | RW | RW | RW | – |
| **Branding** tab (permlevel 1): name, logo, favicon, brand and accent colours, apply to Desk | RW | hidden | hidden | – |
| **Capabilities** optional-module toggles (permlevel 1): CRM, Online Store, Buying, HR, Manufacturing, Quality, Support, Assets, Projects, messaging | RW | hidden | hidden | – |
| **Messages** tab, wording and country code (permlevel 0): which order messages go out, by which channel | RW | RW | RW | – |
| **Messages** tab, WhatsApp / SMS connection and credentials (permlevel 2) | RW | RW | hidden | – |

Hidden means the tab/section is not shown, the values are not returned by the API, the
change history of those fields is not shown, and a save that tries to change them is
silently ignored. Frappe's Administrator is a System Manager.

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

**Shop-floor staff (Cashier, Attendants)** can only sell, count stock and *request*
transfers; they cannot edit prices or book stock movements, and a Material Request
they raise must be a Material Transfer. They use the plain **Request Stock** page
(`/desk/stock-request`), not the Desk forms. The Store Owner (or System Manager, not
Store Admin) can allow named people to *Receive stock* or *Change prices* in *Retail
Store Settings → Stock Transfers → Extra Staff Permissions*; the list is empty by default.
(`staff_grants.py` keeps the Stock Receiver / Price Editor roles in step with it.)

> Intentional: a Cashier can open the Sales Invoice list by URL even though the sidebar
> hides it. POS needs read access to Sales Invoice for returns and reprints; the list is
> scoped to their own store and they have no write access beyond POS.

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

#### POS look (cards + cart)

`public/css/pos_restyle.css` (registered with `app_include_css`) restyles the POS: rounded item
cards with a soft pastel gradient tile per product, a stock-count pill top-right, rounded
cart rows with the quantity as a pill, a dashed discount row and a bold Checkout button. It is
**visual only**: no markup or behaviour changes, so the variant picker, barcode bypass and
permissions are untouched.

* It layers on Solvronix Desk / Theme Studio rather than replacing them: colours come from
  Frappe v16's semantic tokens (`--card-bg`, `--border-color`, `--control-bg`, `--text-color`,
  `--btn-primary`), so Theme Studio brand changes and dark mode flow through. The pastel tiles
  are translucent washes, so they read on light and dark surfaces. Dark mode is
  `html[data-theme="dark"]` (checked against this build; `data-theme-mode` holds the user's
  light/dark/automatic choice).
* `retail_store` must load **after** `solvronix_desk` in `sites/apps.txt` (it does). Selectors
  carry `:not(#rs-pos)` to out-rank ERPNext's deeply nested stock rules without `!important`.
* Frappe v16 does not read a `build.json`; the file is served directly, so **bump the `?v=` in
  `hooks.py` after editing it**, then `bench --site <site> clear-cache`.
* No separate Website Theme entry is used (it can conflict with hooks-loaded CSS).
* The POS markup uses no Bootstrap `.card`, so the `.card` vs `.frappe-card` dark-mode gap does
  not apply here (re-check if ERPNext's POS changes).
* Not done, because they need JS rather than CSS: a +/- quantity stepper on cart rows (stock
  ERPNext edits quantity through the numpad), inline per-row discount badges, and the total
  inside the Checkout button.
* Test: `tests/browser_pos_restyle.py` checks the styles (light and dark) and that the restyled
  screen still works as the Downtown cashier: picker opens, variant adds, Checkout -> Cash ->
  Complete Order submits a Sales Invoice.

### 5. Capabilities (Retail Store Settings → Capabilities)

**Who can change what:** the optional-module toggles below are **System Manager only**
(permlevel 1). Store Owner and Store Admin do not see that section; they still see and tune the
always-on settings on the same tab (Loyalty Program, Group Variants in POS). Decision for a
client who wants a module (CRM, Online Store, HR...): a System Manager ticks the toggle.

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

#### CRM (proven working)

Switching **CRM** on (System Manager, Retail Store Settings > Capabilities) was tested end to end
in a real browser as Store Owner and is covered by `tests/browser_crm.py`:

1. **Lead:** create a Lead (name, email, company).
2. **Lead -> Opportunity:** *Create > Opportunity* first opens a **Create Prospect** dialog (checked
   by default, named after the company). Confirm it and the Opportunity form opens prefilled
   with the Lead. Converting a Lead therefore also creates a **Prospect** and a **Contact**.
3. **Opportunity -> Customer:** *Create > Customer* opens a Customer prefilled from the Opportunity;
   the Lead becomes *Converted* and the Customer links back to both (`lead_name`, `opportunity_name`).

What the toggle does, and for whom:

* **Store Owner** (and System Manager): full Lead, Opportunity, Prospect and Campaign access,
  plus **read** on the lookup tables those forms link to (Opportunity Type, Sales Stage,
  Opportunity Lost Reason, Competitor, Industry Type, Market Segment). Without those, saving an
  Opportunity failed with a 403 on a dropdown; `tests/capability_links.py` lists any such gap for
  any capability and user.
* **Everyone else** (Store Admin, Store Manager, Cashier, Attendant, warehouse roles): no CRM in
  the rail, every CRM route (`/desk/lead`, `/desk/opportunity`, `/desk/crm`...) is blocked, and no
  CRM data appears. Store Admin deliberately gets no CRM (it holds none of the grants); the
  module and its workspace are hidden from it from the same role list, so there is no empty page.
* Turning the toggle off reverses all of it (module blocked, Dock hidden, grants revoked).
* Reads correctly in the Desk theme (Solvronix Desk): Lead / Opportunity / Customer forms show the
  brand colours; the theme's *progressive forms* collapse optional fields behind "Show N optional
  fields" (the Details tab can look sparse until expanded).

**Customer defaults.** ERPNext leaves a new Customer's *Customer Group* and *Territory* blank (v16 does
not require them, and Lead/Opportunity conversion only fills the group, and only when a site default
exists). The starter pack therefore sets Selling Settings defaults at install and on every migrate,
only when blank: Customer Group **Individual** and Territory = the **company's country** (created
under *All Territories* if ERPNext has none for it, e.g. Mauritius; otherwise *Rest Of The World*).
A `Customer.before_validate` hook also fills a blank group/territory from those settings, so
conversions, POS quick-create and API-created customers all get them. Change the defaults per client
in Selling Settings; they are never overwritten once set. Verified: a Customer converted from an
Opportunity arrives with both set (`tests/browser_crm.py`, `check_config`).

#### Online Store (proven working)

Switching **Online Store** on (System Manager) needs the `webshop` app and its dependency `payments`
(`bench get-app payments --branch version-16 && bench get-app webshop --branch version-16`, then
`install-app payments webshop`). Tested end to end in a real browser (`tests/browser_store.py`, 22 checks):
a customer buys a **variant**, pays in store, and the Store Owner fulfils it in Desk.

What a customer sees: `/` is the shop (not the login screen); products list with Desk prices; a
product page with **Select Variant** (Size/Colour dropdowns, standard ERPNext Item Configurator),
which resolves the exact variant and its price (equal to the Desk *Item Price*) and adds it to the cart;
the cart shows the rate and total with **Place Order**; the order page confirms the order. A first-time
visitor is created as a Customer automatically (group *Individual*, home-country territory) and adds
their address in the cart. Ordering more than is in stock is refused ("Only N in Stock").

**Variants need no picker of their own** (unlike POS): the Item Configurator already handles them.
Publish the *template* as the Website Item; its website warehouse is used for every variant (see below).

**Stock, in two stages** (both at the Main warehouse, which fulfils online orders):

| Stage | actual | reserved | projected |
|---|---|---|---|
| before the order | 50 | 0 | 50 |
| order placed on the storefront | 50 | **1** | 49 |
| Delivery Note submitted (Store Owner, Desk) | **49** | 0 | 49 |

Placing the order only *reserves* stock; the physical quantity drops when the Delivery Note is posted.
Invoice and take payment in Desk as usual (Sales Order > Create > Sales Invoice / Payment Entry).

**Defaults applied the first time it is switched on** (never overwritten afterwards; System Manager edits
*Webshop Settings*): selling price list, price and stock shown, variant picker on, and an **offline payment
gateway "Pay in Store or on Delivery"** pointing at the company's cash account. Webshop refuses to show
*Place Order* without a Payment Gateway Account (it silently falls back to "Request for Quote", with no
prices in the cart), so a retailer taking cash needs one. **For online card payments** add a real gateway
(Payments app) and choose its Payment Gateway Account in Webshop Settings; the app then stops hiding
the order page's *Pay* link (it is hidden only while the offline gateway is active, because it opens a bare 403).

**Branding on the public site:** the brand logo in the navbar, an accent rule and brand-coloured
buttons/links (`public/css/storefront.css`, driven by the per-site colours; the themed login page is
left alone), the brand name in the footer instead of "Powered by ERPNext", and the shop as the home page.
The logo is the same **square mark** used for Desk (README, Branding).

**Storefront look:** `storefront.css` also gives the public site a calm, image-led look (visual language
borrowed from Allbirds, no code reused): warm oatmeal page, white navbar with a hairline instead of a
coloured bar, uppercase tracked product names on borderless image tiles, a serif product title, square
corners, and paper-on-oatmeal cart panels. The client's brand colour stays on buttons and links only. Re-skin
a site by overriding `--rs-surface`, `--rs-paper`, `--rs-ink`, `--rs-line`, `--rs-r`, `--rs-display`.

* Public site only (`web_include_css`); the Desk and POS are untouched. Bump the `?v=` in `hooks.py` after
  editing, then `bench --site <site> clear-cache`. The active Website Theme is stock `Standard` (no custom
  theme record), and none should be added: it can conflict with hooks-loaded CSS.
* Webshop markup it targets: `.item-card > .card` (grid), `.list-row` (list), `.product-image`,
  `.product-details`. Webshop nests Bootstrap `.card` inside `.card` in the cart, so inner ones are flattened.
* Button text is uppercased by CSS, so tests match it case-insensitively.
* **Grid is the default view.** Webshop has no setting for it (it hard-codes `localStorage.product_view ||
  "List View"`), so `public/js/storefront.js` seeds that key only when the shopper has never chosen; their own
  list/grid choice is kept. Names are uppercase in both views.
* **Demo photos** (`public/images/demo/`, wired by `retail_store.demo.apply_demo_images`, idempotent, skips
  missing files) are stock placeholders used to check the look against real photography. Several do not match
  their item names (e.g. the "Cotton Tee" and "Men's Kurta Pajama" images), the licence/credit for each was not
  recorded, and the kids' photo shows identifiable children: **replace them all with the client's own product
  photos, and do not leave these on a client's site.** `delete_demo_data` removes the demo Items but the image
  files stay in the app, so also delete `public/images/demo/` when cloning this app for a client.
* The "material card" callout on product pages needs template markup and content, not CSS, and is not done.

#### HR & Payroll (needs the `hrms` app)

```bash
bench get-app hrms --branch version-16
bench --site <site> install-app hrms
```

Then tick **HR** (System Manager, Retail Store Settings > Capabilities). It unhides the HR and
Payroll modules, grants the roles below, and seeds defaults from the new **HR & Payroll** tab.
Untick it and the grants are withdrawn again.

> ## ⚠ Payroll must be verified before any real pay run
> Every payroll figure here (PAYE bands, CSG, HRDC, PRGF, leave days, overtime multipliers) is a
> **starting point from a research note** (`mauritius_payroll_reference.md` in the bench root),
> compiled from payroll vendors and law firms, **not** from the MRA or the Workers' Rights Act
> text, and several figures are disputed between sources. The PAYE bands were not yet gazetted
> when the note was written. **The client's own accountant or payroll professional must check
> every rate, threshold and the resulting payslips against current MRA guidance and the Act
> before the first real pay run.** The system makes this configurable; it cannot make it correct.
> (Same category of flag as per-client SMTP in the shopper section below.)

**Who can do what**

| Role | Employee | Checkin / Attendance / Shift Assignment / Leave | Payroll |
|---|---|---|---|
| Store Owner | everyone, create + delete | everyone, full | full |
| System Manager | everyone | everyone | full, **and** the only role that edits the rates |
| Store Admin | everyone, create + edit | none | none |
| Store Manager | own stores' staff, edit **not create** | own stores' staff | none |
| Cashier / Attendant / Warehouse | themselves | clock in/out themselves | none |

**One location per employee.** Employee has a single `Store / Location` field. For an employee
with a login it follows that user's default location in *Retail Staff Access* (so there is one
source of truth: change it there and the Employee follows); loginless staff are set directly on
the Employee. A Store Manager sees and edits employees of the stores in their own Retail Staff
Access, and cannot move one to a store they do not run.

**Scoping is enforced by `hr.py`, not by HRMS' own "Employee → self" User Permission.** That
permission would stop a Store Manager seeing their store's staff, so it is switched off, and
every doctype that carries a person (`hr_doctypes.py`; Salary Slip, Expense Claim, Timesheet,
Checkin, Attendance, ...) is limited the same way by permission hooks: managers see their stores,
everyone else sees only themselves, owner-level roles see all. `tests/check_hr.py` walks every
doctype on the site and fails if an HRMS upgrade adds a person-linked doctype that is not covered.
HRMS gives every user linked to an Employee the `Employee` role, which can read payroll doctypes,
so **do not remove these hooks without putting something equivalent in their place.**

**Clock in / out** is a page (`/desk/store-clock`), reached from a **Clock In / Out** button in the
POS header (shown only when HR is on and the user has an Employee record). It writes a standard
*Employee Checkin* through HRMS' `add_log_based_on_employee_field`, so shifts and auto-attendance
work as HRMS designed. Staff never open a Desk form. Link each login to an Employee
(`User ID` on the Employee); a user with no Employee sees a plain message instead.

**What gets seeded** (idempotent, re-applied on every settings save / migrate): Leave Types
(*Annual Leave*, and *Sick Leave* only if you give it a non-zero figure), an Overtime Type, Salary
Components (*CSG (Employee)*, employer-side *CSG*, *HRDC Levy*, *PRGF* as statistical components so
they never reduce net pay, *PAYE*, *Basic Salary*, *Overtime*, *End of Year Bonus*) and a submitted
*Income Tax Slab*. Formulas are rebuilt from the settings, so no rate lives in Python or JS. Changing a
PAYE band adds a **new** Income Tax Slab (HRMS versions tax by effective date); older slabs stay for
past payslips. Not modelled: the PRGF wage ceiling (sources disagree), the cumulative-PAYE
remittance deadline, the 3x rate beyond 8 public-holiday hours, and the 13th-month
"whichever is higher" rule (*End of Year Bonus* is paid via Additional Salary).

**Time zone.** Clock times, shifts and auto-attendance all use System Settings > Time Zone.
This is a Mauritius system, so it must be `Indian/Mauritius` (UTC+4); the dev site is set to
that. Install and the setup wizard set it automatically on new sites (`install.py`); change it here if a site needs another zone.

#### Shopper identity: sign-up, sign-in, front page, portal

The audit of the Online Store found it could not onboard a real customer. What changed:

* **Sign-up works, and is email-verified.** `Website Settings > Disable Signup` is off. Frappe's sign-up
  asks for name and email and emails a **set-password link**, so the site needs an outgoing **Email
  Account** (default outgoing). Without one a new customer is told "ask your administrator to verify
  your sign-up" and is stuck. **Per client: add their SMTP details before go-live.** On this dev site a
  local sink stands in (`tests/mail_sink.py`; Email Account "Retail Dev Outgoing" -> 127.0.0.1:1025).
  Dev sites also have no `host_name`, so the emailed link points at `http://<site>` without the port.
* **New customers get the `Customer` role** (`Portal Settings > Default Role`, set by
  `setup_webshop_defaults` while blank). Without it a self-signed-up user had no roles, could not read
  their own Customer record and got "Not Permitted" on their own order confirmation. The demo shopper
  only worked because the seeder gave it the role by hand, which is why browser_store never saw it.
* **Two sign-in URLs.** `/login` is Solvronix Desk's staff page and is untouched. Shoppers have their
  own page, **`/account/login`** (`www/account/login`: Frappe's login controller, same form and sign-up
  flow, plus the `rs-shop-login` body class the storefront CSS keys on). Three things point shoppers
  there, none of which edit webshop or frappe: (1) Webshop Settings > *Redirect on Action*, which the
  guest Add to Cart / Wishlist use, is set to `/account/login` while blank; (2) retail_store ships its
  own copies of Frappe's navbar partials (`templates/includes/navbar/`, retail_store loads last so they
  win) whose Login link uses `rs_login_url`, set by `storefront.shopper_login_url`; (3) a `page_renderer`
  (`portal_access.GuestToShopperLogin`) sends a signed-out visitor on /orders, /invoices, /shipments,
  /addresses or /me to `/account/login?redirect-to=...`. With the Online Store off none of this is
  active: `rs_login_url` is unset, nothing links to the page, and `/account/login` itself redirects to
  `/login`. The staff page still shows Solvronix's own "Create account" link; that is Solvronix's.
* **Front page** (`www/store-home`, the site Home Page while the Online Store is on): banner, "Shop by
  category", "New arrivals". Headline, tagline and banner photo are per-client fields (Retail Store
  Settings > Branding > Storefront Home Page); with no photo the banner is a brand-coloured band.
  Category tiles link only to Item Groups that are published with a route (the demo groups are).
* **Portal pages follow the capabilities** (`portal_access.py`, one table for sidebar AND access). A
  customer always gets Orders, Invoices, Shipments, Addresses. Quotations need CRM, Issues need Support,
  Projects/Timesheets need Projects, and the supplier pages need Buying and the Supplier role;
  Material Request is never shown. Disabling a Portal Menu Item only hid the link: the pages still
  opened (and a customer could file a support issue nobody watches), so a `before_request` hook now 403s
  a gated route for Website Users. Staff are unaffected.
* Test: `tests/browser_shopper.py` (45 checks): the two sign-in URLs, front page, portal gates and the whole
  new-customer journey (guest Add to Cart -> sign up -> email -> set password -> address -> Place
  Order -> an order on their own Customer). It leaves one test Customer per run; clear with
  `bench --site <site> execute retail_store.demo.purge_signup_test_customers`.
* **Phone and tablet pass** (`tests/browser_mobile.py`, 23 checks; screenshots in `shots/mobile/`).
  The cart overflowed 13px at 390px: Webshop hides the Subtotal/remove columns up to 992px but the
  "Net Total" row still has a `colspan=3` cell, so the table was laid out three columns too wide; that
  row is now a flex line. Also fixed: the footer pushed every store page 15px sideways at 768px (stock
  Frappe: its `.container` has no side padding there), the order page's customer name sat in a 55px
  column, the Place Order button was 29px tall (now 44px), and Webshop's pale-pink "Out of stock"
  is now a readable dark red. An out-of-stock product shows the message, no Add to Cart, and fits at
  desktop and phone width (the test empties the item's website warehouse and always restores it).
* **Search and filters** (`tests/browser_search.py`, 43 checks, desktop + phone; shots in `shots/search/`).
  Webshop's search box only autocompletes: pressing Enter did nothing, although its product query
  (`get_product_filter_data`) already accepts a `search` term that the page JS never sends. So
  `storefront.js` (which loads before Webshop's bundle, so it wraps `frappe.call` rather than patching
  classes) makes Enter reload the listing with `?search=`, adds the term to every product query on the
  page (so it combines with category/attribute filters), keeps it in the box, and renders a styled
  "No results for ..." state with *Clear search* / *Browse all products*. Suggestions showed a grey
  placeholder because `Website Item.thumbnail` is only built for File-attached images and ours are URLs:
  a Website Item `validate` hook now reuses the photo, and existing rows are backfilled.
  **Filters** were off (an empty "Filters / Clear All"); `setup_webshop_defaults` now enables Category
  (Item Group) and every Item Attribute used by a published template, only while the client has not set
  any of their own. Webshop collapses the panel under 768px with **no button to open it**, so
  `storefront.js` adds a Filters / Hide filters button on phones.
  **Attribute filters were dead on a variant shop** (every Colour/Size click returned zero products).
  Webshop matches *published Items* carrying the attribute, but a variant shop publishes only the
  template (variants have `published_in_website=0`) and the template's own attribute rows are empty.
  `storefront.get_product_filter_data` (an `override_whitelisted_methods` entry) resolves the filter
  through the variants instead: a template matches when ONE variant has every selected value (White +
  42 means a white size-42 variant), then hands the codes on to Webshop as an item filter.
  Not natively available in Webshop, so not offered: **price range** and **in-stock only** filters (its
  only numeric filter is a discount range driven by Pricing Rules). Adding them means a custom filter.
* **Polish** (`tests/browser_polish.py`, 16 checks, desktop + phone; shots in `shots/polish/`), all in
  `storefront.css`, no JS. The nav is now **sticky**, translucent with a backdrop blur (an open phone
  menu stays solid). A **Sale badge** sits on a product card whenever Webshop's own price line shows a
  discount (`.striked-price`, i.e. a live Pricing Rule), via `:has()`; it disappears with the discount.
  The test creates a temporary 20% Pricing Rule and always deletes it. **Not built, on purpose:** a
  *New* badge (the listing payload carries no creation date and the cards are built in JS, so it needs
  Python + JS, and on a freshly loaded catalogue every item would be "new") and a *second image on
  hover* (cards receive only `website_image`; no Website Item has a slideshow).
* **Shopping UI** (`public/js/shop_ui.js`, `tests/browser_shop_ui.py`, 65 checks, desktop + phone; shots in
  `shots/shop_ui/`). **Variant swatches** on grid cards (real colour/size values, colour circles painted
  in the colour, sizes as chips, only on variant templates), a **quick-view modal** (bottom sheet on a
  phone: image, name, price, stock, option pickers, quantity, Add to cart) and a **cart drawer** that
  slides in after any Add to cart without a page reload (lines, quantity +/-, remove, subtotal,
  Checkout / View cart; the navbar cart icon opens it too; guests are still sent to `/account/login`).
  Everything real goes through Webshop's endpoints: `update_cart`, `get_cart_quotation`,
  `variant_selector.get_next_attribute_and_values`, and `get_attributes_and_values` (batched for a page
  of cards by `storefront.get_card_variants`). The script loads before Webshop's bundle, so it wraps
  `frappe.call` to learn the listing's products and to notice a successful add. Choices: a card swatch
  opens quick view pre-selected rather than re-pricing the card; one photo per item (no gallery).
  **Three Webshop gaps found and fixed in our app** (`override_whitelisted_methods`, nothing edited in
  webshop): (1) the variant picker's `available_qty` was 0 for every variant, because it reads the
  VARIANT's Website Item, which a template-only shop does not have, so every variant looked out of stock;
  (2) `update_cart` with quantity 0 on the last line crashed (HTTP 500, rolled back, line stayed), because
  it returns `quotation.name` for a quotation it just deleted; (3) `get_cart_quotation` is wrapped only to
  add server-formatted amounts, so the drawer prints "Rs 2,700.00" like the rest of the store.
  **Test hygiene:** saving a Website Item over REST (the tests do it to empty a warehouse) blanks a
  `website_image` that is a plain `/assets/...` URL, as the demo photos are; real client photos are File
  records and unaffected. The tests re-apply the demo photos afterwards (`apply_demo_images`).
  Not built: a multi-image gallery (one photo per item). On a phone the navbar cart icon lives inside the
  hamburger menu (stock Webshop), and is hidden while the cart is empty.
* Not done: a stock empty white card under every product page, the material card, bundles.

Gaps this testing found and fixed (each would have hit a real customer):

* **Variants had no warehouse:** the cart reads the warehouse from the Website Item of the exact item bought,
  and only the template has one, so lines fell to Stock Settings' default ("Stores", which holds no stock) and
  nothing was reserved where the stock is. Cart quotations *and* Sales Orders now take the template's website
  warehouse, else Main (`storefront.py`; webshop's `place_order` re-reads it per line, so both are needed).
* **Customers saw "Not Permitted" on their own order page:** webshop's order page looks up loyalty points,
  which needs read permission on Customer. Portal ("Customer" role) users now have read on Customer,
  confined by hooks to the customers they are a Portal User of (they cannot list, read or write any other).
* **Store Owner could not save a Website Item:** no read on *Website Slideshow*; granted (`tests/capability_links.py`).
* **The Pay link led to a bare 403** for the offline gateway; hidden while it is active.

Known limits: demo products have no images (placeholders show); the template product page does not show
per-variant availability (it is checked at order time); the first-time address form requires choosing an
Address Type; cancelled test orders cannot be deleted normally (`demo.purge_cancelled_test_orders`).

Two optional modules are **separate apps in v16** and must be installed first
(the toggle refuses to switch on and shows the commands):

* E-Commerce: `bench get-app webshop --branch version-16 && bench --site <site> install-app webshop`
* HR: `bench get-app hrms --branch version-16 && bench --site <site> install-app hrms`

---

### 6. Branding (per site)

Branding lives in *Retail Store Settings → Branding* (**System Manager only**, permlevel 1; Store
Owner and Store Admin do not see the tab): name, logo, favicon,
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
retail staff) has a Dock with one entry, Retail Store (the raw Stock / Selling / Accounts module shells were removed from it: they opened unbranded ERPNext sidebars, and what they held is reachable from the Retail Store sidebar, including a **Back Office** section for owners). The
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
# staff grants, transfer-only rule, Request Stock API (server side)
bench --site <site> execute retail_store.tests.check_stock_request.run
# Request Stock page, settings grants, storefront polish (browser; see each file's header)
python apps/retail_store/retail_store/tests/browser_stock.py
python apps/retail_store/retail_store/tests/browser_storefront_batch.py
# acceptance walk-through over the REST API as each demo user (site must be running)
env/bin/python apps/retail_store/retail_store/tests/e2e_section7.py http://<site>:<port>
# toggles, branding, navigation (restores settings afterwards)
bench --site <site> execute retail_store.tests.check_config.run
# real browser, as the Downtown cashier: grid -> picker -> cart -> barcode scan (needs Playwright)
python apps/retail_store/retail_store/tests/browser_pos.py <barcode>
# POS restyle + that the restyled POS still sells (cashier: picker, cart, checkout); sells 1 sneaker
python apps/retail_store/retail_store/tests/browser_pos_restyle.py
# Online Store in a real browser (needs the webshop app + toggle on + demo data): a customer buys a
# variant, stock reserves then deducts on delivery, branding on the public site; cancels what it creates
python apps/retail_store/retail_store/tests/browser_store.py
# new-customer journey + login routing + front page + portal gates (needs the dev mail sink, see the file)
MAIL_OUT=/tmp/retail_mail python apps/retail_store/retail_store/tests/browser_shopper.py
# CRM capability in a real browser (needs CRM switched on): Lead -> Opportunity -> Customer as
# Store Owner, and that no other retail role can see or reach CRM; cleans up after itself
python apps/retail_store/retail_store/tests/browser_crm.py
# HR (needs hrms + HR switched on + demo data): scoping, grants, payroll seed, clock API. Removes what it creates
bench --site <site> execute retail_store.tests.check_hr.run
# HR in a real browser as cashier / manager / owner / admin / system manager (seed the employees first)
bench --site <site> execute retail_store.tests.seed_hr_demo.run
python apps/retail_store/retail_store/tests/browser_hr.py
# customer messages: phone numbers, consent, the three providers against a fake gateway, failure / retry, who sees credentials
bench --site <site> execute retail_store.tests.check_messaging.run
# the optional-fields fold never hides a required field (Employee Left, Attendance On Leave, Payment Entry bank, Item batches); drafts it makes are removed
python apps/retail_store/retail_store/tests/browser_fold_guard.py
# every dialog type, light + dark, two window sizes, stacked dialogs and Escape (numeric checks + screenshots)
python apps/retail_store/retail_store/tests/browser_dialogs.py
# POS New Customer quick entry: consent boxes unticked, defaults, Edit Full Form saves, MUR findable (needs an open POS shift)
python apps/retail_store/retail_store/tests/browser_customer_quick_entry.py
# the same in a real browser: cart opt-in boxes, order + delivery in the Message Log, Settings tab per role (switches messaging on, then off)
python apps/retail_store/retail_store/tests/browser_messages.py
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

**Home icon.** The rail's top tile links to Frappe's own home (`/desk/home`), which is the Setup
shell for an owner and the Apps launcher (naming ERPNext / Frappe HR, or "Not permitted") for
everyone else. `public/js/landing.js` sends every retail user (anyone but System Manager) from
that tile, from `/desk/home`, `/desk/setup/home` and any `desktop` route back to Retail Store.
Display-side only; the server 403s stay the real boundary. Test: `tests/browser_home.py`.

**Dialogs** (`public/css/dialogs.css`, `public/js/dialogs.js`). One base layer for every Frappe / ERPNext dialog, on top of the
corner / padding / pill-button skin: it starts below the toolbar and never grows past the window (the body scrolls, header and
footer stay), the form inside is flat (no second white card), an emptied column collapses (New Customer as an Individual puts
Email and Mobile on one row, and fits a 1440x900 window), footer buttons share one layout, and it fades and rises 8px on open
(off under reduced motion). A message opened over a dialog sits clear below its header, takes keyboard focus, and Escape closes
only the dialog on top (a blocking one ignores it). Gotchas: the Desk theme redefines `--border-color` inside a dialog as a
near-white glass value (dialog lines use `--rs-dialog-line`), forces `.form-page` backgrounds with `!important`, and Frappe
re-uses one message element, so the opening order is read from `frappe.ui.open_dialogs`, never from the DOM. Test: `tests/browser_dialogs.py`.

**Optional-fields fold** (`public/js/progressive_guard.js`). The Desk theme keeps every non-required field of a *saved* record behind
"Show N optional fields" (a new record shows everything). It decided what is required once, at load, so a field that
*became* required afterwards stayed hidden and Save failed with nothing to fix it: Employee Status = Left (Relieving Date),
Attendance On Leave (Leave Type), a Payment Entry on a bank account (Reference No / Date), an Item with batches and expiry
(Shelf Life). Now whenever Frappe re-evaluates the conditions the field is revealed with a note ("Relieving Date is now required
(on the Exit tab)"), a failed Save reveals the field before Frappe scrolls to it, and the fold's own Hide button never re-hides
it. Optional fields stay folded as before. Form-simplification work (Customize Form) must keep this true: never hide a field
that is required or conditionally required. Test: `tests/browser_fold_guard.py` (19 checks; with the guard off 8 of them fail).

### Backlog (known, not built)

* Report roles: `apply_report_and_page_roles` is meant to start each Custom Role from the report's standard roles, but after migrate Sales Register, Sales Analytics and Item-wise Sales Register hold only the retail roles (Profit and Loss / Balance Sheet showed the same until their accounting roles were named explicitly). Check what the Accountant can still open and fix the copy step.
* Mauritian Rupee: enabled on every migrate (ERPNext ships it disabled); a fresh site whose wizard company country is Mauritius also gets System Settings country / currency set. An existing company's currency is never changed (ERPNext locks it once there are postings); the dev demo company is still on INR.
* Staff login page still shows "Powered by Solvronix" (theme setting; the Desk and storefront credits are already hidden).
* Customer, Employee and Stock Count are still raw Desk forms; Ctrl+K search, the "All Options" menu and the Accountant / Warehouse Manager screens have not had a wording review.
* The Retail Store home page colour/icon badges (`public/js/home_cards.js`) are keyed on the English card titles; update its lookup table if a shortcut or card is ever relabelled or translated (unknown titles just get no badge).
* `check_config` switches HR off when it finishes; run `tests/seed_hr_demo.run` before `browser_hr.py`.

### Customer messages (WhatsApp / SMS)

Order messages to the customer: **order confirmation** (when a storefront order is placed) and **order ready**
(when its Delivery Note is posted). Built in this app (`retail_store/messaging/`); Capabilities > **Customer Messages**
(System Manager) switches it on, **off by default**. Low-stock and staff-invite messages are not part of it: they stay on
Frappe's own email / Desk notifications.

> ## ⚠ A local adviser must confirm the rules before real marketing messages go out
> The consent scaffolding below is **configurable and ready, not legally verified.** The research behind it (vendor guides,
> not the statute) could not confirm how the **Data Protection Act 2017**, the **ICTA's SMS rules** and **WhatsApp's own
> business rules** treat *transactional* versus *marketing* messages in Mauritius, nor whether each retailer must register with
> the Data Protection Office. **Before any client sends offers or loyalty messages, their adviser must check those points.**
> Order messages go to the phone number on the order, **pending that same confirmation**. WhatsApp pricing per message for
> Mauritius is also unconfirmed (it comes from Meta's rate card). Nothing here blocks development; it should make it easy to comply once confirmed.

**How it works**

| Piece | What it does |
|---|---|
| Rules (Settings > **Messages**) | One row per message and channel: when (Order confirmation / Order ready), WhatsApp or SMS, on/off, the wording (`{customer}` first name, `{order}`, `{store}`, `{total}`) and, for WhatsApp, the approved template's name. Starter rows: WhatsApp on, SMS off (no double sends). Store Owner and Store Admin edit these. |
| Providers | **Dry run** (default: logs, sends nothing), **Meta WhatsApp Cloud API** (the client's own WhatsApp Business account: phone number ID + access token), **generic HTTP SMS gateway** (address, method, `name=value` parameters with `{to}`, `{to_digits}`, `{message}`, `{sender}`, `{username}`, `{password}`, optional success text). Twilio can be added as a fourth adapter in `messaging/providers.py`. |
| Credentials | Retail Store Settings > Messages, `Password` fields (encrypted like the SMTP password), access level 2: **System Manager and Store Owner only**, not Store Admin. Never in code, never in the log (masked in errors). A gateway address must be `https://` (plain `http://` only for this machine). |
| Message Log | The outbox (like Email Queue): event, channel, recipient, text, status **Queued / Retry / Sent / Failed / Skipped**, attempts, the provider's reference, the problem in words, and why it was allowed (order message, or the opt-in's date). Store Owner / Store Admin read it (sidebar: Back Office > Messages); nobody edits or deletes it by hand. |
| Sending | `frappe.enqueue` after the sale commits, so the till and the checkout never wait. Timeouts, 5xx and 429 are **retried** (after about 5 then 30 minutes, 3 attempts, by a scheduler job every 5 minutes); anything a retry cannot fix (bad token, rejected number, unknown template, `http://` gateway) is **Failed at once**, with the reason shown. A failed message **never** fails the order: it is a log row. |
| Which orders | Only storefront orders (Sales Order type *Shopping Cart*); POS and Desk sales send nothing. The number comes from the order's contact, then the customer, then the delivery / billing address, and is normalised to +230 (Settings: country code). |

**Consent.** Each Customer has, per channel, *Offers by WhatsApp* / *Offers by SMS* with the time ticked, the time unticked
(the first stays), how (*Storefront checkout* / *Recorded by staff*) and by whom. The storefront cart shows the two boxes
only while messaging is on: never ticked for the shopper (only if they ticked them before), saved as they press Place Order,
and unticking withdraws. POS's new-customer dialog carries the same two boxes; staff record or withdraw a customer's choice on the Customer form's **Messages** tab (the theme keeps optional fields behind "Show N optional fields" on every form). The engine already refuses a
**marketing**-kind message without that opt-in (Skipped, "has not opted in"); no marketing message is built yet.
**New Customer quick entry (POS and Desk)** (`public/js/customer_quick_entry.js`): the two boxes are forced off every time the dialog opens, with "Only tick if the customer said yes"; Customer Type starts as *Individual* and Country as the company's country (Country becomes mandatory once an address line or city is typed); and *Edit Full Form* hands over the real field names, as Save does (ERPNext's dialog works with alias fields and mapped them only on Save, so the full form had no Country and refused to save). Test: `tests/browser_customer_quick_entry.py`.
Gap to close before launch: the storefront has no separate "manage my messages" page, only the cart boxes.

**Set up for a client:** a System Manager switches **Customer Messages** on (Capabilities); the Store Owner picks the provider
and pastes the credentials (Messages tab), edits the wording, and turns SMS rows on if they use SMS. For WhatsApp, the client
creates and gets their templates approved in their own WhatsApp Business account first (messages the business starts need an
approved template). Leave providers on Dry run to rehearse: the Message Log fills, nothing is sent.

**Tests:** `bench --site <site> execute retail_store.tests.check_messaging.run` (phone numbers, consent, all three providers
against a fake gateway on this machine, failure / retry, who sees credentials, a real storefront Sales Order; rolls itself back)
and `python tests/browser_messages.py` (the cart boxes, order + delivery in the Message Log, the Customer form, the Settings tab
and sidebar per role; cancels what it creates, switches messaging back off).

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
