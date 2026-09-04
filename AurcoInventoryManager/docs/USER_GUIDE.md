# AURCO INVENTORY MANAGER — User & Build Guide

**Brand:** AURCO  ·  **Created by:** Zain Shami  ·  **Version:** 2.28.0
**Platform:** Windows Desktop (.EXE) · offline · local-first · SQLite

---

## 1. Build the Windows .EXE

On any Windows 10/11 PC with **Python 3.10–3.13** installed:

```
build_windows.bat
```

That single script creates a virtual environment, installs the dependencies,
and produces:

| Output | Path |
|---|---|
| Application | `dist\AURCO Inventory Manager\AURCO Inventory Manager.exe` |
| Installer *(if Inno Setup 6 is installed)* | `Output\AURCO_Inventory_Manager_Setup_2.22.0.exe` |

The installer adds a **desktop shortcut**, a **Start Menu shortcut**, the
application icon, an uninstaller, and optionally pre-creates `D:\AURCO Inventory`.
Inno Setup 6 (free) is available at <https://jrsoftware.org/isdl.php>.

To run from source without building: `run_dev.bat`.

> The uninstaller never deletes your data folder — only program files.

---

## 1a. Windows shortcuts

`create_shortcut.bat` creates a **Desktop shortcut** and a **Start Menu entry**
(AURCO group) with the application icon. It finds the built `.EXE`, an installed
copy, or falls back to running from source — so it works at any stage.
`build_windows.bat` now runs it automatically at the end of a build, and the
installer still creates its own shortcuts.

---

## 1b. AURCO branding out of the box

The AURCO logo ships with the application and is applied automatically on first
run, together with a brand-matched printed header (charcoal → AURCO red
gradient) and a white backing plate so the logo stays sharp.

Change any of it later:

* **logo file, position, size, watermark** → *Settings → Appearance & Theme →
  Logo placement*
* **header band colours and style** → *Settings → Document Designer*
* the **AURCO Brand (Red)** theme preset matches the on-screen application to
  the same palette.

---

## 2. First run

1. A **Storage Location** wizard appears. Choose where all data lives, e.g.
   `D:\AURCO Inventory`, an external disk, or a network share.
2. Tick **Load sample/demo records** to explore a fully populated system
   (40 items, ~250 documents, 6 months of history).
3. The folder tree is created automatically:

```
AURCO Inventory/
├── Database/            aurco_inventory.db (SQLite, WAL mode)
├── Inventory/           goods receipt PDFs
├── Reversed Inventory/  reversed GRN PDFs
├── Delivery Notes/      DN PDFs
├── Reversed Delivery Notes/
├── Returns/             return note PDFs
├── Reversed Returns/
├── Stock Transfers/
├── Reversed Stock Transfers/
├── Stock Adjustments/
├── Reversed Stock Adjustments/
├── Stock Counts/
├── Reversed Stock Counts/
├── Reports/             generated report PDFs
├── Attachments/         supporting documents & item images
├── Exports/             Excel / CSV exports
├── Backups/             automatic + manual database backups
└── Logs/                error log
```

Change the location any time in **Settings → Storage & Backup → Change & Move Data**
(existing files are copied to the new location).

---

## 3. Daily workflow

| Task | How |
|---|---|
| Receive goods | **Stock In** → supplier, PO ref → F3 add items → qty & cost → *Save & Finalize* |
| Issue material | **Stock Out** → project, issued to → F3 add items → qty → *Finalize & Generate DN* |
| Return material | **Returns** → type the DN number → *Load DN* → set returned qty & condition → Save |
| Move stock | **Stock Transfer** → from/to warehouse → items → Save |
| Correct stock | **Stock Adjustment** → mandatory reason → ± quantity → Save |
| Count stock | **Physical Count** → *Load All Items* → print sheet → enter counted qty → *Generate Adjustment from Variances* |
| Find anything | **Ctrl+F** global search, or scan a barcode into the top box |
| Search inside files | Global Search also checks searchable text inside PDFs, TXT, CSV, DOCX and XLSX attachments / library files |

Every finalized transaction writes an immutable ledger row and updates the item
balance in the same database transaction — stock can never drift.

### Reserved stock in the Item Master
The Item Master grid shows **Balance · Reserved · Free to Use**. *Reserved* is
stock prepared for an open material request that has no Delivery Note yet — it is
still on the shelf, so the balance is unchanged, but it is promised to a project.
*Free to Use* is Balance − Reserved: what a new request can actually be given.
Hover the amber Reserved figure to see which MR numbers hold it. The reservation
clears automatically when the line is unprepared, the request is cancelled, or
the Delivery Note is created. The **Reserved Stock Report** lists every
reservation line by line, and Current Stock / Item Master reports carry the same
two columns.

### Barcode scanners
Any USB "keyboard-wedge" scanner works. Focus a *Scan / type code* box and scan:
the item is identified and its description, UOM, current stock, location and
stock status are shown, then it is added to the document.
Print labels from **Item Master → Print Barcodes** (Code128).

---

## 3a. Tools, Instruments & Devices (Ctrl+Shift+T)

A **stand-alone custody register** for tools, instruments and devices, built
around the controlled form *WH-FRM-001 — Tools, Devices & Instruments Handover*.
It answers one question: **who is holding which tool, and since when.** Its own
database (`Tools, Instruments & Devices/tool_station.db`), its own backups and reports. **No
stock movement is ever posted.**

**Four transaction types**, exactly as on the paper form:

| Type | Meaning |
|---|---|
| **Issue** | Tool leaves the warehouse, open-ended custody |
| **Transfer** | Custody moves from one holder to another |
| **Temporary Loan** | Must come back by the Expected Return Date |
| **Return** | Tool comes back, closing an earlier handover |

**A dashboard you can shape.** The Dashboard tab has one filter bar that drives
everything on it: text, type, status, project, custodian, category, warehouse,
period (or a custom date range), *only still out*, *only overdue*, and a
**Measure** selector (documents / quantity / quantity still out). Press
**⚙ Customise** to choose which KPI tiles, charts and tables appear and how many
tiles sit on a row — the layout is stored in the module's own database. Click a
tile to drill into the register with the same filters, click a chart bar to
filter by it, and use **Export View** for a PDF or Excel of exactly what is on
screen.

**The reference number is self-describing** and is decoded automatically:

```
WH-087IS2308202601
^^ ^^^ ^^ ^^^^^^^^ ^^
|  |   |  |        └─ sequence that day
|  |   |  └────────── date 23/08/2026
|  |   └───────────── type: IS Issue · TR Transfer · TL Loan · RT Return
|  └───────────────── project 087 → PRJ000087
└──────────────────── originating warehouse
```

### Sync Folder — the point of the module
Point AURCO at the folder your signed handover PDFs sync to (network share,
OneDrive, Google Drive). Press **Sync All Folders** and it reads every PDF,
decodes the reference, and files the handover with all of its item lines —
custodian, iqama, mobile, project, asset IDs, serials, makes, condition grades
and calibration dates. Re-syncing never double-posts the same form.

> **Files are only ever read.** Nothing in the synchronised folder is moved,
> renamed or deleted — it is someone else's sync target.

### The unified filter
Every document type is shown in **one consistent shape**, so Issues, Transfers,
Loans and Returns are directly comparable. Filter by type, status, project,
custodian, date range, *Overdue only* or *Outstanding only*, or search by asset
ID, serial number, iqama or project. Tick **Show one row per item** to switch
between one row per document and one row per tool.

### Custody engine
Returns can be partial — return 1 of 6 items and the handover becomes
*Partially Returned*, not closed. Over-returning more than is outstanding is
blocked. A transfer closes the source as **Transferred Out**, never *Returned*,
because the tools did not come back to the warehouse. A Temporary Loan past its
Expected Return Date turns **Overdue** automatically and reports how many days
late.

### Assets — where is it now
Derived automatically from the handover history: current status (In Store /
Issued Out / On Loan / Overdue), who holds it, which project, condition,
calibration due date and days remaining, plus the full movement history of that
one tool.

### Reports (16)
All Handover Documents · Issue / Transfer / Temporary Loan / Return Registers ·
Outstanding Custody · Overdue Loans · Custody by Person · Custody by Project ·
Item-wise Handover Detail · Asset Register (Where Is It Now) · Asset Movement
History · **Calibration Due** · Damaged / Defective Items · **Missing Documents
& Signatures** (which controlled forms are incomplete) · Monthly Handover
Summary. All with PDF / Excel / CSV / print / share.

**Print Form** reprints any handover as the controlled WH-FRM-001 layout, with
the ticked transaction type, the item grid, the verification boxes and the two
signature blocks sitting directly above the footer rule.

---

## 3b. Bulk Stock Check (Ctrl+K)

Answer *"do we have all of this?"* in seconds. Paste, type, scan or load a list
of item codes — one per line — optionally with a required quantity:

```
ITM-00012, 50
ITM-00034  20
8901234567890
WRONG-CODE, 5
```

You instantly get, per code: description, UOM, **available qty**, required qty,
**short by**, result (Available / Partial / No stock / **NOT FOUND**), value,
warehouse, location, rack and stock status.

* Duplicated codes are merged — even when one line uses the item code and another
  the barcode or alternate code.
* Tick **Show only shortages and missing codes** to see just the problems.
* **Create Delivery Note from this list** pushes the whole list into the Stock Out
  screen with quantities pre-filled.
* Export the answer to PDF / Excel / CSV, print it, or email/WhatsApp it.

---

## 3a. Material Requests — project asks, warehouse answers  (Ctrl+M)

The complete pipeline from a project's request list to the Delivery Note:

```
PASTE  →  COMPARE  →  PREPARE  →  READY  →  DELIVERY NOTE
                                (reserved)   (stock leaves)
```

### Tab 1 — New / Check Request
Copy the rows straight out of the project's Excel/ERP export (including the
header) and paste. Columns like *Line, Project ID, Item number, Procurement
category, Product name, Unit, Quantity, Status, Category, Purchase requisition
reference* are recognised automatically — no mapping needed. You immediately get
per line:

| Requested | In Stock | Reserved | Available | Can Supply | Short By | Availability |
|---|---|---|---|---|---|---|
| 8 | 3 | 0 | 3 | 3 | 5 | **Partial Available** |

Status per line is **Full Available · Partial Available · Not Available ·
Item Not Found**, with an overall verdict and totals (requested / can supply /
shortage / value). Export the answer to PDF, Excel or CSV, or email/WhatsApp it
back to the project. Then **Save as Material Request** (MR-2026-00001).

### Tab 2 — Requests & Preparation
Your team works here. **Prepare All Available** reserves everything the
warehouse can supply in one click, or use **Set Prepared Qty** per line as
material is physically picked. Each line shows Requested / Prepared / Delivered /
Pending / Short By, and the fulfilment state:

**Pending → Preparing → Ready → Partially Delivered → Delivered**

Unrecognised codes can be **linked** to an existing item or **created** in the
Item Master on the spot. When the project's wording is unclear, **Google Item**
opens a Google.com lookup with an in-system preview so the store team can verify
part names, catalog wording or likely equivalents before linking.

> Preparing a line **reserves** it — a second project checking the same item sees
> the reduced *Available* figure, so the same stock is never promised twice.
> Nothing has left the warehouse yet and no stock is deducted.

**This tab only shows work still in your hands.** As soon as *every* live line of
a request is Ready to Deliver, the request leaves this screen and lives on
**Tab 3 — Ready to Deliver**; the same happens once it is fully Delivered. A
request that is only *partly* processed stays here with its remaining lines. To
look at a finished request again, tick **Show completed (Ready / Delivered)** or
pick that status in the **Status** filter. If a line is unprepared or a delivery
is reversed, the request automatically returns to this tab.

**Printed heading.** The Request PDF is titled with all three identifiers —
`Material Request MR-2026-00062 · PR / MR No. 001735 · PRJ_0000086` — because
the site quotes its own PR number and project, not AURCO's internal MR number.
PR numbers written on individual lines are merged with the header's, duplicates
removed. The file name follows suit:
`MR-2026-00062 (PRJ_0000086) PR 001735.pdf`. Missing values are dropped rather
than printed blank. The Tab 1 availability report is titled the same way.

### Tab 3 — Ready to Deliver
Everything prepared but **not yet on a Delivery Note**, filterable by project,
MR or PR number. Select the lines going out and press **Create Delivery Note
from Selected** — that is the moment stock is deducted and the DN PDF is
produced (with each line's PR number, and the PR numbers in the file name).
**Return to Stock (unprepare)** releases a reservation if plans change.

Partially delivered requests stay open with the remaining quantity pending, so a
shortage can be delivered later when stock arrives.

### Reports
**Material Request Report · Material Shortage Report · Ready for Delivery
Report · Project-wise Request Fulfilment**, all with filters and
PDF/Excel/CSV/print.

---

## 3c. Multi-PR Delivery Notes

One Delivery Note can serve **several Purchase Requests at once**. The DN item
table has a **PR No.** column next to **Remarks**, so every row carries its own
Purchase Request number.

**Fast entry:** type the PR number in **Current PR No.** at the top of the grid —
every item you add next is tagged with it automatically. Change the PR and keep
adding; the DN builds up PR by PR. Two helpers cover the rest:

* **Apply to selected rows** — write the PR into the highlighted rows (or all rows).
* **Fill down ▼** — copy the current row's PR into every row below it.

A live counter shows how many PRs are on the note, e.g.
`3 PR(s): PR-2026-0148 (2×, 12) · PR-2026-0152 (3×, 33) · PR-2026-0161 (1×, 15)`,
and warns if any line still has no PR before you finalize.

### PR numbers in the file name
The saved Delivery Note is named:

```
DN-2026-00170_PR-2026-0148_PR-2026-0152_PR-2026-0161.pdf
```

Each PR is written **once**, no matter how many item lines it covers, in the
order it first appears. Blank PRs are skipped, duplicates (including different
letter case) are merged, and unsafe characters are removed. A very long list is
shortened to `..._+3-more` so the name always stays valid on Windows.
Turn the behaviour off or change the separator in
**Settings → Document Numbering → Delivery Note file naming**.

### PR everywhere else
* The **PDF** shows the PR column plus a *"Purchase Requests covered by this
  Delivery Note"* recap table (PR / lines / total qty).
* **Global search** and the **Documents** page find a DN by any of its PR numbers.
* **Returns** loaded from a DN inherit each line's PR; **Duplicate** keeps them.
* The **stock ledger** records the PR on every issue movement.
* New report: **PR-wise Issue Report** — every issued line grouped by PR.
* **Bulk Stock Check** accepts `ITEM-CODE, QTY, PR-NUMBER` per line, so a
  multi-PR request list can be pasted in and turned into one DN in two clicks.

---

## 3c2. Arabic in the printed header

The header prints **English on the left and Arabic on the right**, exactly like
your stationery. Arabic is properly *shaped* (letters joined) and laid out
right-to-left, using a bundled Unicode font — nothing to install.

**Typeface** — *Settings → Company & Documents → Arabic text on printed
documents*:

| Style | Look |
|---|---|
| **Kufi** *(default)* | modern flat-stroke — matches the printed letterhead |
| Naskh | classic book hand |
| Amiri | traditional calligraphic Naskh |
| System | the Windows default Arabic font |

All four are bundled, so the document prints identically on any PC.

**Arabic-Indic numerals** — switch on to print ٢٠٥١٠٦٢٨٨٤ instead of
2051062884 inside Arabic lines (English lines keep Western digits). Some display
faces omit Latin punctuation, so characters such as the dot in "س.ت" are
automatically swapped for their Arabic equivalents instead of vanishing.

Preset: **AURCO Letterhead (English + Arabic)** in the Header & Footer Designer.
Placeholders: `{company_ar}` `{tagline_ar}` `{cr_label_ar}` `{vat_label_ar}`.
Edit the Arabic wording in *Settings → Company & Documents*.
Any element you type Arabic into is detected automatically — no special setting.

---

## 3d. Notes & Tasks — your workspace  (Ctrl+T)

A personal workspace so nothing is lost between shifts.

**Notes** — sticky notes in six colours, **pinned** to the top, grouped by
category, searchable, and optionally linked to an item, DN, PR/MR or project.
Archiving keeps a note searchable without cluttering the board.

**Tasks** — a daily work list with:

* **Priority** (Low / Normal / High / **Urgent**) and status
  (To Do → In Progress → Blocked → Done)
* **Due date + time**, with overdue and due-today highlighted in red/amber
* **Assignee** (picked from your signatory list) and category
* **Checklists** — `[x] step one` lines that drive the progress bar automatically
* **Repeat** daily / weekly / monthly — completing a recurring task
  automatically creates the next occurrence
* **Reminders with sound** — AURCO checks every minute while it is open and
  **beeps** the moment a task falls due, with a tray pop-up. The tone follows the
  priority (Urgent gets a sharper triple beep), each task rings **once**, and a
  task set for 14:30 alerts at 14:30 — not before.
  *Settings → Email · WhatsApp · Printer → Alert sounds*: mute, change the check
  interval, test all six tones, or use your own `.wav`
* **Related to** — link a task to a DN, PR/MR, item or project
* Views: All open · Due today · Overdue · This week · No date · Done
* Export the list to **PDF or Excel**

---

## 3e. Excel paste, Excel export and on-the-spot stock correction

The Stock Out / Delivery Note grid (and every other transaction grid) talks to
Excel in both directions, and can correct a wrong system balance without leaving
the screen.

### Paste item lines from Excel
**📋 Paste from Excel** — or **Ctrl+V** inside the grid — opens a preview sheet
already filled from the clipboard.

* A header row (`Item Code`, `Description`, `Qty`, `PR / MR No.`, `Unit Cost`,
  `Batch/Lot`, `Location`, `Remarks`, and common synonyms) is detected
  automatically; without one the columns are read in that order.
* Tab-separated (a plain Excel copy), CSV, pipe tables and space-padded text are
  all understood. **Load Excel / CSV file...** imports a whole `.xlsx`/`.csv`.
* Each line is matched to the item master by **code, barcode, alternate code** or
  description and shown as *✔ found* / *✖ not in item master* **before** anything
  is added. Unknown codes are skipped by default.
* An item already on the note is **updated**, not duplicated (matched on item +
  PR number, so the same item can still appear twice under two PRs).
* **⬇ Excel template** saves an empty sheet with the right headings.

### Export the lines to Excel
**📊 Export to Excel** writes the grid exactly as displayed to a branded
`.xlsx` — styled header, auto-filter, frozen panes, totals — and opens it.
**Ctrl+C** copies the grid (or just the selected rows) as tab-separated text for
an immediate paste into Excel. PR numbers such as `001735` keep their leading
zeros.

### Correct the inventory quantity from the Delivery Note
The storekeeper picking the note is the person who discovers that the system
balance is wrong, so the fix lives on the same screen:

* Type the **real counted quantity straight into the Available cell**, or
* select the line and press **⚖ Adjust Stock (F4)** (also on the right-click
  menu).

The dialog shows the system quantity and accepts either a physical count or a
**± difference**, with a **mandatory reason** (physical count correction, missing
stock, damaged stock, found stock, data correction, opening balance) and optional
remarks. Posting creates a regular **Stock Adjustment (ADJ)** document with a
stock-ledger entry and audit trail — it is *not* part of the delivery note — and
the Available column updates at once. A correction that would make the balance
negative is refused, and the button obeys the **adjustments** permission.
**🔄 Refresh Stock** re-reads all available quantities, for when another PC moved
stock while the note was open.


---

## 3f. Cable Records (Ctrl+Shift+B)

A **stand-alone register for cable drums** — cable is counted in metres left on
a drum, not in pieces. Like the Tools module it keeps its **own database**
(`<storage>/Cable Records/cable_records.db`), its own numbering, audit trail,
backups and reports, and **never posts a stock movement**.

### Three registers
| Tab | What it holds |
|---|---|
| 🥁 **Drum Register** | Every drum: cable type, cores, size/CSA, voltage grade, armour, insulation, conductor, manufacturer, batch/heat no., supplier, PO, GRN, test certificate, project, warehouse, location, original length, **remaining length**, unit cost |
| ✂ **Cutting Log** | Every length issued from — or returned to — a drum, with cable tag, project, receiver, DN number, from/to equipment and remarks |
| 🧭 **Cable Schedule** | Tag by tag: area, system, from/to equipment, route, required length, drum(s) used, pulled length, balance, progress %, status and the megger/IR test |

### The remaining length is proved, never typed
Every change to a drum goes through the cutting log, so the balance can always
be re-derived (**🧮 Rebuild Balances**). The engine refuses to issue more than is
left, or to put back more than the drum ever held; **voiding** a cut returns the
length at once; **scrapping** what is left needs a **mandatory reason** and is
audited. Status walks *In Stock → Partly Used → Empty* by itself, plus
**Reserved** and **Scrapped** as deliberate decisions. Cut records are numbered
`CC-2026-00001`, drums default to `DRM-2026-00001`.

### Cutting and pulling
**✂ Issue Length** on a drum opens a dialog that previews what the drum will
hold afterwards. Choose a cable tag and it pre-fills the balance still to pull,
the from/to equipment and the project. **↩ Return Off-cut** is the same in
reverse. On the schedule tab, **✂ Pull From Drum** works the other way round: it
offers the drums carrying the right size and cuts the balance off the chosen
one. A cut tied to a tag updates that tag automatically — pulled length, drum(s)
and status.

**➡ Advance Status** walks a tag *Planned → Issued → Pulled → Glanded →
Terminated → Tested → Energized*; **🎯 Record Test** stores IR (MΩ), continuity,
result, tester and certificate, and a pass moves the tag to *Tested*.

### The dashboard
29 KPI tiles and 15 charts/tables, all driven by one filter bar (text, drum
status, cable type, size, project, location, manufacturer, period, *only drums
with cable left*, *only off-cuts*). The **Measure** selector switches the charts
between drums, length received, length remaining, length used and stock value.
**⚙ Customise** chooses the tiles, the charts, the tiles-per-row, **what counts
as an off-cut** (default 50 m) and **after how many days a drum is idle**
(default 90) — stored with the module. Click a tile to drill into the register
with the same filters; click a bar to filter by it. **Export View** prints a
PDF or Excel of exactly what is on screen.

Two tiles pay for the module on their own: **Off-cuts / Short Ends** (the short
lengths to use before opening a new drum) and **Idle Drums** (nothing cut from
them for months).

### Import and reports
**📥 Import from Excel** pastes an existing drum list straight in — the header
row is recognised (Drum No., Description, Size, Length, Remaining, Location,
Project, PO, GRN, batch…), existing drums are updated and new ones added, and
**⬇ Excel template** gives the right headings.

16 reports: drum register · stock summary by cable · available drums ·
off-cuts · empty & scrapped · idle drums · cutting log · consumption by project ·
consumption by cable tag · cable schedule · cables not yet pulled · megger /
IR test register · failed & pending tests · traceability (PO/GRN/batch/cert) ·
stock value · audit trail. All with PDF, Excel, CSV, print and share.

> The module has its own **Backup / Restore** buttons — the main database backup
> does not include it.

---

## 3g. Employee PPE Register (Ctrl+Shift+E)

A separate register for **shoes, blankets, FRCs and coveralls** issued to
employees, tracked by **employee code**.

### Why this module exists
These items often leave the store through a normal **Delivery Note**, but later
you need an employee-wise history: who received the shoes, which blanket went to
which worker, and which DN carried it. This module keeps that record without
changing stock a second time.

### What it does
* **Manual issue entry** for employee code, employee name, project/site,
  description, size, quantity, DN number and remarks.
* **DN sync** that scans finalized Delivery Notes and detects matching PPE lines
  by item description, code and category.
* Automatically groups records as **Safety Shoes, Blanket, FRC, Coverall** or
  other PPE, and also tries to read the **size** from the description.
* Keeps the source **DN number and PDF path** so the original document can be
  opened from the register.
* Flags lines that still need employee details with **Needs Employee Info**.

### Reports
Built-in reports include:
* **Full PPE Register**
* **Safety Shoes Register**
* **Blanket Register**
* **FRC Register**
* **Coverall Register**
* **By Employee**
* **By Delivery Note**
* **Missing Employee Codes**
* **Synced Delivery Note PPE**

This gives you a separate employee-issued record while still using the normal
Delivery Note workflow in inventory.

---

## 4. Stock alert system

Nothing is hard-coded. Per item you can choose:

| Mode | Behaviour |
|---|---|
| `GLOBAL` | uses the percentages in Settings (default: warn < 40 %, critical < 20 % of max) |
| `PERCENT` | custom percentages of the maximum level for that item |
| `QTY` | fixed minimum / critical quantities |
| `CATEGORY` | the thresholds defined for its category |

Status chain: **Normal → Warning → Critical → Out of Stock (0)**, colour-coded
everywhere, on the dashboard alert panel, and as an optional Windows tray
notification at startup.

---

## 4b. Appearance — full theme control

**Settings → Appearance & Theme** gives complete visual control, applied live:

* **7 presets**: AURCO Light, AURCO Dark, Midnight Blue, Desert Sand,
  Emerald Warehouse, Graphite, High Contrast.
* **15 individual colour pickers**: primary, sidebar, accent, background, cards,
  text, secondary text, borders, table stripe, selection, header text, and the
  four stock-status colours (Normal / Warning / Critical / Out of Stock).
* **Typography & shape**: font family, font size, corner radius, spacing density
  (Compact / Comfortable / Spacious), table row height, sidebar width.
* **Form style**: Card, Flat or Outlined.
* **Toggles**: card shadows, table grid lines, striped rows.
* **Export / Import** a `.aurcotheme` file to copy your look to another PC.

Theme colours also drive the **PDF header, accent bar and table headers**, so
printed documents match the on-screen branding.

### Logo placement
Also in Appearance: choose the logo file, its **position in the PDF header**
(Left / Center / Right / None), exact **width and height in mm**, whether it
appears on documents and/or reports, and an optional faint **centre watermark**.

---

## 4c. Login and password protection

**Settings → Security & Login**

* **Login screen** at startup — appears automatically once any account has a
  password (or force it with *"Ask for a user name and password when AURCO starts"*).
* **Administrator password required for deletions** — deleting/deactivating an
  item pops an authorisation dialog showing exactly what will be deleted and its
  current balance. The same protection is available for **reversing a finalized
  document** and for changing another user's password. Both are individually
  switchable.
* Passwords are stored as **PBKDF2-HMAC-SHA256** hashes with a random per-user
  salt — never in plain text.
* **Roles**: Administrator, Storekeeper, Logistics, Viewer — each with sensible
  default permissions, overridable per user from a list of 15 fine-grained
  permissions (`items_delete`, `doc_reverse`, `settings`, `backup`, ...).
* Failed logins and every authorisation (granted or denied) are written to the
  audit trail.

> If no password is ever set, AURCO stays completely frictionless — no login
> screen and no prompts. Protection switches itself on the moment you set one.

---

## 4d. Delivery Note design, signatories and attachments

### Four named handover roles
Every Delivery Note carries **Issued By · Delivered By · Handover To ·
Received By** — in the form header, in the PDF details table, and as the four
signature blocks at the bottom. The chain of custody is explicit: who released
the material, who transported it, who took charge at site, and who signed for it.

### Signatories with default signatures  (Settings → Signatories)
Keep a directory of people (name, designation, department, phone, e-mail) and
upload a **signature image** once. Then set a **default signatory per role, per
document type** — a Delivery Note opens with *Issued By* and *Delivered By*
already filled and their signatures printed automatically. Anything can be
overridden on an individual document. The signature blocks themselves are
configurable: change the roles, their order, or add your own.

Options: print signature images or leave blank lines for wet signing, show or
hide a date line, and choose the block style (Line / Box / None).

### Document Designer  (Settings → Document Designer)
Per document type — DN, GRN, Return, Transfer, Adjustment, Count:

* table **header colour** and **accent colour** (or follow the app theme)
* striped rows on/off, **table font size**, page orientation
* show/hide: company logo, value & cost columns, attachment list, QR code
* **signature area height**
* optional **terms & conditions** block and an extra footer note
* **Preview sample PDF** to see the result before saving

The *"Purchase Requests covered by this Delivery Note"* summary table has been
**removed** — the PR number already appears on every line. It remains available
as an optional switch for anyone who wants it back.

### Attachments on the document
Every document-creation screen now supports both:

* **📎 Attach Document** — pick one or more files, and
* **📋 Paste Attachment** — paste a copied file from Windows Explorer or a
  copied screenshot / image straight from the clipboard.

This works on **Delivery Notes, Goods Receipts, Returns, Transfers,
Adjustments, Counts, and the General Delivery Note Maker**.

Attachments are copied into the *Attachments* folder and linked to the
transaction. In the final PDF they are **merged after the base document pages**,
so the pack prints in this order:

1. the document itself,
2. any normally attached files,
3. any clipboard-pasted files / screenshots last.

Each appended page carries an **ATTACHMENT — document number** banner:

* **PDF** attachments are appended page for page
* **images** (jpg, png, screenshot paste, ...) are placed on their own A4 page,
  scaled to fit
* other files (Word, Excel, e-mail) get a reference page so the pack still
  records them

One file to print, e-mail or WhatsApp — document plus every supporting paper.
Turn it off per document type with *"Merge attachments into the PDF"* in the
Document Designer.

### Delivery Note header — gate-pass style
The printed Delivery Note header carries only what the gate and the driver need:

| DN Number | Date |
|---|---|
| **From** (dispatch location) | **Project** (destination site) |
| **Vehicle** | **In Time** |
| **Out Time** | Reference / MR |

On the form, *In Time* and *Out Time* have a **Now** button that stamps the
current clock time. *From* defaults to the selected warehouse but can be changed
(e.g. dispatching from a yard while stock belongs to the main store).

Need more on the page? **Settings → Document Designer → "Show extra header
fields"** adds department, requester, issued-to, purpose, driver and prepared-by.

### Handover To — the driver taking custody
**Handover To** is the person who physically takes the material, normally the
driver. Next to the name there are two extra boxes:

* **ID / Iqama** — Iqama, national ID or licence number
* **Phone** — contact number

Pick a driver already in **Settings → Signatories** and both fields fill in
automatically from his record. For a walk-in or subcontractor driver, just type
them straight into the boxes — no need to create a signatory first.

The identity is stored on the Delivery Note and printed twice: in the header
(*Handover To (Driver)* and *ID / Iqama · Phone*) and again under his signature
block, so the gate can verify the person against the document. Turn the printed
identity off with *"Print ID / Iqama and phone under the signature"* in
**Settings → Signatories**.

### Authorised signature above the footer line
The signature block is **anchored to the bottom of the page**, sitting directly
above the footer separator line, no matter how many item rows the document has.
Three or thirty lines, the signatures always land in the same place — so a
signed Delivery Note looks identical every time.

If the remaining space is too small for the block it moves to the next page and
anchors there. The caption ("Authorised Signatures") is editable, and
*"Place signatures right under the item table"* restores the inline layout.

Signatory names come from the signature panel on the form; if a document was
created another way (material request, import), the names stored on the
document header are used automatically.

### Header & Footer Designer  (Settings → Header && Footer Designer)

A full visual designer with a **live preview** that renders through the real PDF
engine — what you see is exactly what prints.

**Band controls**: height, background (**Gradient / Solid / None**), start and
end colours, gradient direction (horizontal or vertical), side padding, gap
between rows, accent bar (colour + thickness), an optional edge rule, and the
logo (show/hide, left–centre–right, width, height, backing plate).

**Element rows** — the band is a list of text elements, each independently
controlling:

| Setting | Options |
|---|---|
| Content | 18 sources: company, tagline, address, phone, e-mail, VAT, document title, document number, date, printed date/time, page, **Page X of Y**, project, warehouse, user, or free text |
| Position | **Left · Center · Right** |
| Row | 0–5 — stack as many lines as you need in the band |
| Size | 5–30 pt |
| Style | **Bold** / *Italic* |
| Colour | any colour, per element |
| Show | switch a line off without deleting it |

Add, remove and reorder lines; free text supports placeholders such as
`DN {docno} · {date}` or `VAT {vat} · {phone}`.

**Per document type** — design once for *All documents*, or give the Delivery
Note, GRN, Return, Transfer, Adjustment or Count its own header and footer. A
type without an override follows the shared default.

**6 presets** — AURCO Brand (charcoal → red), Solid Red, Corporate Navy,
Charcoal Minimal, White / Letterhead, Emerald. **Export / Import** a design as
JSON to copy it to another PC, and **Reset** returns to the factory layout.

> *Page X of Y* triggers an automatic two-pass render so the total is correct.

### Legacy header options  (Settings → Document Designer)
Applies to every PDF:

* header band **style** — a two-tone **gradient** or a solid fill
* band **start / end colours**, plus a per-document-type override
* **logo backing plate** (Auto / White / Dark / None) — a light plate keeps a
  dark logo crisp on a dark band; *Auto* adds it only when the band is dark
* header band **height**, accent bar on/off
* company name **alignment** (left / centre), show or hide the tagline,
  document title and print date-time
* **logo** file, position (left / centre / right), size in mm and watermark —
  set in *Appearance & Theme → Logo placement*
* footer **height**, page numbers, separator line, the AURCO credit line and a
  custom footer note per document type

### Form layout
The transaction forms are built for fast data entry on a normal laptop screen:

* **Coloured title banner** — the form header has an attractive gradient bar.
  Colours, gradient/solid/underline style and text colour are all set in
  **Settings → Appearance & Theme** (*Form banner start / end / text* and
  *Form banner style*), and every preset ships with a matching banner.
* **Hide details (Ctrl+H)** — collapse the header when you have many items to
  add. The banner then shows a one-line recap (project, issued to, reference,
  warehouse) and the item table expands to fill the window. Your choice is
  remembered per screen.
* **Item table columns are fixed-width** — Item Code, UOM, Available, Quantity,
  PR No. and Remarks keep their size and only *Description* flexes, so adding
  items can never push Item Code off screen or force horizontal scrolling.
* The table always shows several rows and grows with the window; row numbers
  are displayed down the left edge.
* The four handover roles appear **once**, in the signature panel below the
  table — they are no longer duplicated in the header.

### Readability
Editable cells (Quantity, Remarks, PR No., Unit Cost…) are tinted and use the
theme's text colour, and the in-cell editor is drawn with a high-contrast
border, so numbers and text stay clearly visible while typing on **every**
theme — including dark mode. Quantity fields are bold and slightly larger.

---

## 5. Documents & sharing

Delivery Notes, Returns, GRNs, Transfers, Adjustments and Count Sheets all get a
branded A4 PDF with header, document number, item table and signature blocks.
Company info, logo and footer come from **Settings → Company & Documents**.

Numbering is customisable: `DN-2026-00001`, `RET-2026-00001`, `GRN-2026-00001`,
`ADJ-2026-00001`, `TRF-2026-00001`, `CNT-2026-00001`.

Every document and report offers **Print · Email PDF · WhatsApp PDF ·
Open File Location · Copy Path**, plus PDF / Excel / CSV export.

* **Email** uses your SMTP settings; if empty it opens your default mail client.
* **WhatsApp** opens WhatsApp Web/Desktop with the message pre-filled and the
  document's folder opened for a one-click attach — no unofficial API.
* **Global Search** now has a **File Contents** tab that searches searchable text
  extracted from document PDFs, attachments and library files.
* **AURCO PDF Studio** is the built-in advanced PDF tool. It now has a sharper,
  more professional preview with **Fit Page**, **Fit Width** and **Actual Size**
  modes, higher-quality on-screen rendering, zoom-step buttons, thumbnails, page
  navigation, search, rotate, annotations, signature-image pasting,
  merge/split/reorder/extract, image/Word/Excel export, print-job preparation,
  recent-file history, drag-and-drop opening, sharing, and password-protected
  PDF copies.

### Drafts and adjusted quantities

**Save as Draft** on Stock Out (and Stock In) stores the document without moving
stock. To change it later, select it in **Documents** and press
**✏ Edit Draft / Re-open**: it re-opens on the form that created it, with an
amber guidance bar. Change any quantity, PR number, line or header field and
press **Update Draft** (or **Save Again as Draft**) — the draft is rewritten in
place, so the adjusted quantity is what you see after a refresh, on the PDF and
in the stock posted by **Finalize**. **Cancel editing** leaves the draft
untouched.

A quantity typed into the grid is committed even when you click a button while
the cell is still being edited, and lines pushed in from **Bulk Stock Check** or
a **Material Request** arrive with their quantity and PR number already filled.

Finalized documents are **locked** until you deliberately correct them. Use
**Reverse / Correct** in **Documents** — it posts the exact opposite movement,
stores the reason in the audit trail, and regenerates the PDF into a dedicated
**reversal folder** (*Reversed Delivery Notes*, *Reversed Inventory*, *Reversed
Returns*, *Reversed Stock Transfers*, *Reversed Stock Adjustments* or
*Reversed Stock Counts*).

After reversing a **Delivery Note** (and likewise a **Goods Receipt**), you can
press **✏ Edit Draft / Re-open** and save it again as a **Draft with the same
number**. When it is finalized again, the corrected PDF goes back to the normal
folder and stock is posted using the newly corrected quantity.

---

## 5b. Export presentation

**PDF reports** now print as a designed document:

* a brand rule under the title and a line of **KPI cards** (records, totals,
  value, shortages) calculated from the data
* numbers right-aligned and thousands-separated, **negatives in red**, status
  words tinted (Available green, Partial amber, Out of stock red)
* column widths sized from the content, automatic portrait/landscape, repeating
  header row, banded rows, and an emphasised **TOTAL** line
* filters used for the report are printed underneath the title, with the user
  who produced it, and pages numbered **Page 1 of N**

**Excel exports** are ready to work in: frozen header, **auto-filter**, banded
rows, correct number formats, colour-coded status text, **data bars** on the
main numeric column, red negatives, and a **TOTAL row using SUBTOTAL()** so the
figures follow whatever you filter.

In the Report Center you can also pick which **columns** to export, and switch
the totals row and striping on or off.

---

## 6. Report Center — 33 reports

Current Stock · Low Stock · Critical Stock · Out of Stock · Stock Movement ·
Stock In · Stock Out · Delivery Note · Return · Damaged Stock · Stock Adjustment ·
Physical Count/Variance · Item-wise Consumption · Category-wise · Site-wise
Consumption · Monthly Inventory · Date-wise Transactions · Warehouse-wise ·
Location-wise · UOM-wise · Stock Valuation · Fast/Slow/Non-Moving Items ·
Consumption Trend · Stock Transfer · Audit Trail · Item Master · **PR-wise Issue** ·
**Material Request** · **Material Shortage** · **Ready for Delivery** ·
**Reserved Stock** · **Project-wise Request Fulfilment**.

All support date/category/warehouse/text filters and **PDF + Excel + CSV + Print**.

---

## 7. Excel import

**Item Master → Import from Excel** opens the mapping wizard:

1. Pick the import type (Item Master / Opening Stock / Stock Transactions).
2. Browse to your `.xlsx` or `.csv` (or download a ready template).
3. Columns are auto-matched; adjust any mapping in the dropdowns.
4. Preview, then **Import Now** — a per-row error list is shown at the end.

Opening-stock and transaction imports post real ledger entries, so imported
quantities are fully traceable.

---

## 8. Keyboard shortcuts

```
Ctrl+1 Dashboard        Ctrl+F Global search / scan   F5  Refresh
Ctrl+2 Item Master      Ctrl+3 Movement history       F1  Help
Ctrl+K Bulk stock check       Ctrl+M Material requests
Ctrl+4 Stock In         Ctrl+5 Stock Out / DN         F2  Edit item
Ctrl+6 Returns          Ctrl+7 Transfer               F3  Add items
Ctrl+8 Adjustment       Ctrl+9 Physical count         Ctrl+S Save / finalize
Ctrl+D Documents        Ctrl+R Report center          Del Remove line
Ctrl+, Settings         Ctrl+B Backup now             Ctrl+N New item
Ctrl+Shift+I Quick add item
```

---

## 9. Data safety

* SQLite with WAL journaling and foreign keys; every posting is atomic.
* **No negative stock** unless explicitly enabled in Settings.
* Unique document numbers via an atomic per-year counter table.
* **Validate Database** runs `integrity_check` and reconciles every item balance
  against the ledger; **Rebuild Balances from Ledger** repairs any mismatch.
* Automatic backup on exit, manual backup (Ctrl+B), backup history and restore.
* Packaged Windows copies can require an offline **license key** per PC: the
  user sends the Installation ID and the developer returns the activation key.
* Full audit trail: created, edited, deleted, issued, received, returned,
  adjusted, transferred, finalized, printed, exported — with user and timestamp.
* Unhandled errors are logged to `Logs\aurco.log` with a friendly message.

---

## 9a. Running AURCO on more than one computer

Everyone works on the same live data — one shared database, separate logins.

```
   STORE PC  (holds the data)            SITE PC / GATE / MANAGER
   D:\AURCO Inventory        <----->     \\STORE-PC\AURCO Inventory
```

**Setup** — *Settings → Storage & Backup → Multi-user*:

1. **Show setup guide** prints the exact steps (sharing the folder, permissions,
   the share path to type on the other PC).
2. On the second PC press **Connect to a shared folder...**, enter the path and
   let it test the connection.
3. Give each person their own account in *Users & Permissions* with a role
   (Administrator / Storekeeper / Logistics / Viewer) and a password, then switch
   on the login screen in *Security & Login*.

**What you get**

* the same live stock, documents, PR/MR numbers and reports on every PC
* **unique document numbers** — the counter lives in the shared database
* every action in the audit trail with the user name **and the computer**
* **Who is connected** shows the live session list; the status bar shows
  "👥 N other user(s) online"
* **AURCO PDF Studio** lets connected PCs review the same shared PDF inside the
  system, and refreshes when the shared file changes if you are not holding an
  unsaved working copy
* **Multi-user health check** reports share speed, journal mode and locks

**Under the hood** — WAL journaling plus a 15-second busy timeout, so a second
writer waits its turn instead of failing. Postings take milliseconds, so a small
team on a LAN works comfortably. Keep automatic backups on and prefer a wired
network.

---

## 9b. Testing

A full regression suite ships with the source:

```
python tests/run_tests.py
```

It runs 177 checks: stock maths, every report and PDF template, PR file naming,
material requests and reservations, signatories, document design, the Delivery
Note form layout (column fit, table height, no duplicated fields, collapsing
header), text contrast on light and dark themes, and an upgrade from an older
database (verifying no rows are lost and balances never change).

---

## 9c. Admin Station — a separate register (v2.4)

**Sidebar → Admin Station**  ·  `Ctrl+Shift+A`

A stand-alone register for camp and office records. It is *physically* separate
from inventory:

| | |
|---|---|
| Database | `<storage>/Admin Station/admin_station.db` — its own file |
| Backups | its own, taken with the Backup button on the page |
| Reports | 12 of its own |
| Stock effect | **none, ever** — no ledger row, no balance change |

### Record shape

`SR# · Camp/Office Name · Date of Record · Item Category · Item Description ·
UOM · Quantity · Return · Destination Location · Remarks`

Five optional extras are also stored: Reference, Custodian, Condition, Unit Cost
and Status.

### Uploading data

**Admin Station → Upload Data.** Either paste rows straight out of Excel or pick
an `.xlsx` / `.csv` / `.txt` file. A mapping wizard then shows:

* every uploaded column, a sample value, and which field it will become
  (recognised headings are matched automatically — even misspellings such as
  `Reamrks`),
* a live preview of exactly what will be stored,
* defaults for a blank Camp or Date.

Dates in `dd/mm/yyyy`, `dd-mm-yyyy`, `yyyy-mm-dd`, `d-Mon-yyyy` or Excel serial
form are all converted automatically. In the **Return** column a number works,
and so does the word `Yes` (meaning the whole quantity came back).

Duplicate rows are skipped by default, and **any import can be undone in one
click** from the upload history.

### Dashboard

Twelve KPI tiles (records, camps, categories, destinations, quantity, returned,
still on site, outstanding lines, completed returns, records this month,
damaged/scrap, estimated value) plus charts by camp, category, destination,
month and return status.

### Reports

Full Record Register · Camp/Office Summary · Category Summary · Destination
Summary · Pending Returns · Completed Returns · Monthly Movement ·
**Camp × Category Matrix** · **Duplicate Suspects** · Recently Added ·
Damaged/Scrap Register · Value by Camp.

All export to PDF, Excel and CSV on the company letterhead, into the
`Admin Station` folder.

---

## 9d. General Delivery Note Maker (v2.4)

**Sidebar → General DN Maker**  ·  `Ctrl+G`

Creates a fully branded Delivery Note for anything that is **not** a stocked
item — hired tools, a subcontractor's material, a document pack, a sample.

* every line is free text; no item has to exist anywhere,
* numbering is its own series: `GDN-2026-00001`,
* **no stock movement is ever posted** and nothing appears in the inventory
  documents list,
* the same letterhead, signature blocks (Issued By / Delivered By / Handover To
  with Iqama and phone / Received By) and footer as a real Delivery Note.

Extras: paste lines from Excel, **attach or paste supporting documents from
the clipboard**, optional price/amount columns, terms & conditions, reusable
**templates**, duplicate an old note into a new one, cancel or delete, and
reprint any saved note. Supporting files are appended after the base PDF pages,
just like an inventory Delivery Note.

---

## 9e. Barcode & Label Designer (v2.4)

**Item Master → 🏷 Barcode Designer** (or **⚡ Quick Labels** to reprint with the
saved design).

Six symbologies: Code128, Code39, EAN-13, EAN-8, QR Code and QR + Code128.

**The barcode name is fully customisable.** Each label has three text lines, and
every line accepts placeholders:

```
{code} {description} {short_desc} {category} {subcategory} {uom} {brand}
{model} {specification} {barcode} {alt_code} {warehouse} {location} {rack}
{balance} {unit_cost} {min_level} {max_level} {company} {date} {currency}
```

so a title of `{company} · {code}` and a footer of `Bal {balance} @ {warehouse}`
print exactly that. Each line has its own font, size and alignment.

Also adjustable: what value is encoded (barcode, item code, alternate code or a
custom pattern), bar height and width, QR size, human-readable digits, an
optional price line, the company logo, bar/text/background/accent/border
colours, border width, corner radius, brand stripe and cutting guides.

Sheet layouts: six ready-made templates (3×8, 2×7, 4×10, 5×13, 2×4, shelf tag)
or a fully custom size, with margins, gaps, copies per item and a **start
position** so a part-used label sheet is not wasted.

A **live preview** redraws the real label as you change any setting, and named
designs can be saved, reloaded and deleted.

## 10. Architecture (for future modules)

```
aurco/
├── core/
│   ├── config.py      storage root, folder tree, bootstrap settings
│   ├── database.py    schema, settings, audit, numbering, backup/restore
│   ├── services.py    stock engine (ledger + balances), alerts, dashboard
│   ├── reports.py     28 report builders -> (title, columns, rows)
│   ├── documents.py   PDF / Excel / CSV, email, WhatsApp, print, barcodes
│   ├── importer.py    Excel mapping & import engine
│   ├── security.py    PBKDF2 passwords, roles, permissions, admin authorisation
│   ├── theming.py     theme presets, colour engine, stylesheet builder
│   ├── material.py    material requests: parse, compare, reserve, prepare, deliver
│   ├── signatories.py signatory directory, signature blocks, document layouts
│   ├── header_design.py element-based header / footer designer engine
│   ├── workspace.py   notes and tasks engine
│   ├── arabic.py      Arabic / RTL shaping and Unicode fonts
│   ├── sounds.py      alert tones for reminders
│   ├── multiuser.py   shared-database sessions and health checks
│   ├── adminstation.py SEPARATE camp/office register (own SQLite file)
│   ├── barcodes.py    label design engine: symbologies, templates, captions
│   ├── gdn.py         General Delivery Notes (no inventory dependency)
│   └── demo.py        sample dataset
└── ui/                one module per screen (PySide6)
```

New modules (procurement, assets, equipment tracking, multi-warehouse) plug in
by adding a `documents`/`document_lines` doc-type plus a UI page — the ledger,
numbering, PDF, export and audit layers are reused as-is.

Performance verified: **20,000 items imported in 2.8 s**, dashboard 0.6 s,
reports over ~20,000 ledger rows in under 0.5 s.
e6)
```

New modules (procurement, assets, equipment tracking, multi-warehouse) plug in
by adding a `documents`/`document_lines` doc-type plus a UI page — the ledger,
numbering, PDF, export and audit layers are reused as-is.

Performance verified: **20,000 items imported in 2.8 s**, dashboard 0.6 s,
reports over ~20,000 ledger rows in under 0.5 s.
