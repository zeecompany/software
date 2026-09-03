"""Built-in User Manual — searchable, printable, works with no internet.

Opened with F1 from anywhere. Content lives in `SECTIONS` so it can also be
exported to PDF for the store team to keep next to the counter.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..core import config
from ..core import documents as D
from ..core.database import Database
from . import widgets as W

# ---------------------------------------------------------------- content
# (title, html body). Kept as plain HTML so the same text prints to PDF.
SECTIONS: list[tuple[str, str]] = [
    ("Getting started", """
<h2>Getting started</h2>
<p><b>AURCO Inventory Manager</b> keeps one permanent, auditable record of every
item in your warehouse. The guiding rule is: <i>powerful backend, simple daily
operation</i>.</p>
<h3>First run</h3>
<ol>
<li>Choose the <b>storage folder</b> — a local disk, an external drive or a
network share. Everything (database, delivery notes, reports, backups) lives in
that one folder, so the whole installation moves by copying it.</li>
<li>Optionally load the demo data to explore safely.</li>
<li>Open <b>Settings</b> and enter your company details, logo and thresholds.</li>
</ol>
<h3>The screen</h3>
<p>The <b>sidebar</b> on the left is grouped: Main, Inventory, Transactions,
Documents &amp; Reports, My Workspace, Separate Modules, System. The
<b>top bar</b> has a quick search / barcode box and one-click buttons for the
jobs you do all day.</p>
<h3>The questions this system always answers</h3>
<ul>
<li>What is the current stock, and where is it?</li>
<li>When did it come in, and when was it issued?</li>
<li>Who received it, and on which Delivery Note?</li>
<li>What was returned, and why was stock adjusted?</li>
<li>Why is an item below its minimum level?</li>
</ul>
"""),
    ("Daily workflow", """
<h2>The daily workflow</h2>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Situation</th><th>Where to go</th></tr>
<tr><td>Goods arrived from a supplier</td><td><b>Stock In / Receiving</b> — creates a GRN</td></tr>
<tr><td>Material leaving to a site</td><td><b>Stock Out / Delivery Note</b> — creates a DN</td></tr>
<tr><td>Material coming back</td><td><b>Returns</b> — usable or damaged</td></tr>
<tr><td>Moving between stores</td><td><b>Stock Transfer</b></td></tr>
<tr><td>Correcting a wrong figure</td><td><b>Stock Adjustment</b> — reason is mandatory</td></tr>
<tr><td>Counting the shelves</td><td><b>Physical Count</b> — variance then adjustment</td></tr>
<tr><td>A project asked for material</td><td><b>Material Requests</b></td></tr>
<tr><td>Checking many codes at once</td><td><b>Bulk Stock Check</b></td></tr>
</table>
<h3>Reversing a document</h3>
<p><b>Documents → Reverse / Correct.</b> A reversal never erases anything: it
posts the exact opposite movement and marks the original <b>REVERSED</b>, so the
audit trail keeps both halves.</p>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Document</th><th>What the reversal does</th></tr>
<tr><td>GRN</td><td>Takes the received goods back out of stock</td></tr>
<tr><td>DN</td><td>Puts the issued goods back into stock</td></tr>
<tr><td>RET</td><td>Removes the returned quantity again (damaged returns reduce
the damaged figure)</td></tr>
<tr><td>TRF</td><td>Moves the item back to the warehouse it came from — both
legs are re-posted</td></tr>
<tr><td>ADJ</td><td>Applies the opposite sign: a −7 is undone by +7</td></tr>
</table>
<p><b>When the Delivery Note came from a Material Request</b>, reversing it puts
the request back: the delivered quantity is rolled back to zero, the DN number
is cleared, and the line returns to <b>Ready</b> with its prepared quantity and
its reservation intact. The material is physically back in the store but still
promised to that request, so you can simply issue a corrected Delivery Note.
The line's remarks record which DN was reversed and why.</p>
<p>A document can only be reversed once, a reason is always required, and a
reversal that would drive stock negative is refused.</p>

<h3>Golden rule</h3>
<p>Stock is <b>never</b> edited directly. Every change is a transaction in the
ledger, so the balance can always be explained. If a number looks wrong, use
<b>Stock Adjustment</b> with a reason — never a silent edit.</p>
"""),
    ("Material Requests (MR / PR)", """
<h2>Material Requests</h2>
<p>A Material Request is a project asking the store for material. "PR" and "MR"
mean the same thing here.</p>
<h3>Automatic header</h3>
<p>After you press <b>Check Availability</b> the request header fills itself in:</p>
<ul>
<li><b>Project ID</b> — read from the pasted rows</li>
<li><b>Site</b> — set to the same Project ID</li>
<li><b>Department</b> — <b>Site Team</b></li>
<li><b>Requested by</b> — <b>By Site Team</b></li>
<li><b>Reference</b> — every distinct PR number found in the paste, e.g.
<code>001603, 001604</code></li>
</ul>
<p>Anything you typed yourself is never overwritten, and if a paste contains two
different project IDs the note under the header tells you which one was used.
The defaults for Department and Requested by are editable in
<b>Settings → Company &amp; Documents → Material Request defaults</b>.</p>
<p><b>Clear</b> resets the whole tab: the paste box, the results grid, Project,
Site and Reference, the shortages tick box, and it puts Department and Requested
by back to their defaults.</p>

<h3>Tab 1 — New / Check</h3>
<ol>
<li>Copy the request rows in Excel and <b>paste</b> them into the box (or load a
file). Column headings are recognised automatically.</li>
<li>Press <b>Check</b>. Each line is compared with live stock and marked:
<b>Full Available</b>, <b>Partial Available</b>, <b>Not Available</b> or
<b>Item Not Found</b>.</li>
<li>Review the KPI strip: lines, requested, can supply, shortage, overall.</li>
<li>Press <b>Save as Material Request</b> to keep it.</li>
</ol>
<h3>Tab 2 — Requests &amp; Preparation</h3>
<p>Select a request to see its lines. <b>Prepare All Available</b> reserves
everything the store can supply now. <b>Set Prepared Qty</b> records exactly what
was picked. Preparation is a <i>soft reservation</i>: stock is promised but has
not left the warehouse, so two projects cannot be promised the same items.</p>
<p>When a request description is unclear, use <b>Google Item</b> or the
<b>Google</b> button in the item picker: AURCO opens a Google.com search with an
in-system preview so you can verify likely catalog wording before linking the
line to an item.</p>
<h3>Adding request lines to the Item Master</h3>
<p>A request often contains items that are not in the Item Master yet — they show
as <b>⚠ not in item master</b>. Select them (one, several, or none for all of
them) and press <b>➕ Add to Item Master</b>.</p>
<p>A window opens with <b>one row per item</b> so you can enter the
<b>opening balance</b> you are actually holding for each, along with unit cost,
warehouse, location, category and min/max levels. The <b>Apply to all</b> bar at
the top sets the same opening balance, warehouse or category on every row in one
click, and you can still override any single row afterwards.</p>
<p>Selecting nothing and pressing the button offers every unlinked line of the
request at once.</p>
<p>The opening balance is posted to the stock ledger as an <b>OPENING</b>
movement, not written silently onto the balance, so the item's history starts
correctly and the ledger stays reconcilable.</p>
<p>If a code you type already exists, AURCO <b>links to the existing item</b>
rather than creating a duplicate, and never overwrites that item's stock. The
dialog warns you before you save.</p>

<h3>Statuses — Preparing vs Partial Marked</h3>
<p>When a line is only <i>partly</i> prepared, AURCO tells you <b>why</b>:</p>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Status</th><th>Meaning</th></tr>
<tr><td><b>Preparing</b></td><td>Partly prepared because stock is short — you are
waiting for material to arrive</td></tr>
<tr><td><b>Partial Marked</b></td><td>Partly prepared even though the warehouse
could have supplied it in full — a deliberate decision</td></tr>
<tr><td><b>Ready</b></td><td>The whole requested quantity is prepared</td></tr>
</table>
<p>This happens automatically: prepare 4 of 10 when 150 are on the shelf and the
line reads <b>Partial Marked</b>; prepare 4 of 10 when only 4 exist and it reads
<b>Preparing</b>. Both stay visible in Ready to Deliver so nothing is stranded.</p>

<h3>The Process button</h3>
<p>One button on <b>Requests &amp; Preparation</b> moves material into
<b>Ready to Deliver</b>:</p>
<ul>
<li>Select the lines you want and press <b>⚙ Process</b> (or <b>Ctrl+D</b>).</li>
<li>Select <i>nothing</i> and Process handles the whole request.</li>
</ul>
<p><b>It uses the quantity you already marked.</b> If you set 5 of 12 on a line,
Process moves exactly 5 — it never overrides your figure, even when the whole 12
is sitting on the shelf. Lines with nothing marked are reserved up to whatever
the warehouse can genuinely supply.</p>
<p>Lines that cannot be processed are reported, never skipped in silence:
out-of-stock items, items not yet in the Item Master, and lines already
delivered. Anything only partly covered is listed too, so you can see at a
glance what is still short.</p>
<p><b>Nothing leaves the store.</b> Process is still the soft reservation —
stock is deducted only when the Delivery Note is created on tab 3. After
processing, AURCO takes you straight to Ready to Deliver where the material now
sits.</p>
<p><b>A finished request leaves this tab.</b> Once every live line of a request
is Ready to Deliver — or the request is fully Delivered — it disappears from
Requests &amp; Preparation, because there is nothing left to prepare; it now
belongs to tab 3. A request that is only partly processed stays here with the
lines still to pick. Tick <b>Show completed (Ready / Delivered)</b>, or choose
that status in the <b>Status</b> filter, to look at a finished request again.
Unprepare a line or reverse a delivery and the request comes back here by
itself.</p>

<h3>What the printed request is called</h3>
<p>The Request PDF heading names all three identifiers, because the site quotes
its own PR number and project rather than AURCO's internal MR number:</p>
<p><b>Material Request MR-2026-00062 &nbsp;·&nbsp; PR / MR No. 001735
&nbsp;·&nbsp; PRJ_0000086</b></p>
<p>PR numbers written against individual lines are merged with the one on the
request header, with duplicates removed; a long list is trimmed so the title
cannot wrap. The file name matches —
<code>MR-2026-00062 (PRJ_0000086) PR 001735.pdf</code> — so the right PDF can be
found without opening it. Anything missing is left out rather than printed as a
blank. The availability report on tab 1 is titled the same way.</p>

<h3>Tab 3 — Ready to Deliver</h3>
<p>Prepared material waiting for collection. Select the lines going out and press
<b>Create Delivery Note</b>. <b>Only at this point is stock actually deducted.</b></p>
<h3>Deleting rows in bulk</h3>
<p>All three tabs support multi-selection — click, then <b>Shift+click</b> for a
range or <b>Ctrl+click</b> to pick individually, or <b>Ctrl+A</b> for everything.
The <b>Del</b> key does the right thing on whichever tab you are on.</p>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Tab</th><th>Button</th><th>What it removes</th></tr>
<tr><td>1 · New / Check</td><td>Remove Selected Rows</td>
<td>Takes lines out of the check <i>before</i> it is saved. Nothing is stored
yet, so no record is touched.</td></tr>
<tr><td>2 · Requests &amp; Preparation</td><td>Delete Line(s)</td>
<td>Removes the selected lines from the saved request and releases any
reservation.</td></tr>
<tr><td>3 · Ready to Deliver</td><td>Delete Selected Lines</td>
<td>Removes prepared lines from their request entirely.</td></tr>
</table>
<p>A line that has already been <b>delivered</b> is never erased by a bulk
delete — it is skipped and listed, because the Delivery Note and the stock
ledger point at it. Cancel those instead.</p>
<p>If a bulk delete empties a request completely, AURCO offers to remove the
now-empty request as well.</p>

<h3>Removing a request</h3>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Action</th><th>What it does</th><th>When</th></tr>
<tr><td><b>Delete Line</b></td><td>Removes one line and frees its reservation</td>
<td>Line added by mistake</td></tr>
<tr><td><b>Delete Request</b></td><td>Erases the request and all its lines</td>
<td>Nothing delivered yet</td></tr>
<tr><td><b>Cancel Request</b></td><td>Keeps it, marks it Cancelled</td>
<td>Something was already delivered</td></tr>
<tr><td><b>Restore Request</b></td><td>Undoes a cancellation</td><td>Cancelled by mistake</td></tr>
</table>
<p>A request with deliveries against it <b>cannot be deleted</b> — the Delivery
Note and ledger reference it. Cancel it instead; the audit trail stays intact.
Select several requests together to delete them in one go.</p>
"""),
    ("Right-click and shortcuts", """
<h2>Right-click menus</h2>
<p>Right-click any table for the actions that make sense there — requests, request
lines, ready-to-deliver lines and the availability check all have their own menu
covering prepare, link, create item, print, copy, cancel, restore and delete.</p>
<h2>Keyboard shortcuts</h2>
<h3>Navigation</h3>
<table border='1' cellpadding='5' cellspacing='0' width='100%'>
<tr><td><b>Ctrl+1</b> Dashboard</td><td><b>Ctrl+2</b> Item Master</td><td><b>Ctrl+3</b> Movement history</td></tr>
<tr><td><b>Ctrl+4</b> Stock In</td><td><b>Ctrl+5</b> Stock Out / DN</td><td><b>Ctrl+6</b> Returns</td></tr>
<tr><td><b>Ctrl+7</b> Transfer</td><td><b>Ctrl+8</b> Adjustment</td><td><b>Ctrl+9</b> Physical count</td></tr>
<tr><td><b>Ctrl+D</b> Documents</td><td><b>Ctrl+R</b> Report Center</td><td><b>Ctrl+M</b> Material Requests</td></tr>
<tr><td><b>Ctrl+K</b> Bulk check</td><td><b>Ctrl+T</b> Notes &amp; Tasks</td><td><b>Ctrl+,</b> Settings</td></tr>
<tr><td><b>Ctrl+Shift+A</b> Admin Station</td><td><b>Ctrl+G</b> General DN Maker</td><td><b>Ctrl+F</b> Search / scan</td></tr>
<tr><td><b>Ctrl+Shift+O</b> Company Issuance</td><td><b>Ctrl+Alt+C</b> Calculator</td><td><b>F1</b> This manual</td></tr>
<tr><td><b>Ctrl+L</b> Document Library</td><td colspan='2'>Scanned delivery notes</td></tr>
</table>
<h3>Working</h3>
<table border='1' cellpadding='5' cellspacing='0' width='100%'>
<tr><td><b>F1</b> This manual</td><td><b>F5</b> Refresh</td><td><b>Ctrl+B</b> Backup now</td></tr>
<tr><td><b>Ctrl+N</b> New item</td><td><b>F2</b> Edit / set prepared qty</td><td><b>F3</b> Add items to document</td></tr>
<tr><td><b>Ctrl+S</b> Save / finalise</td><td><b>Ctrl+P</b> Print / PDF</td><td><b>Ctrl+C</b> Copy rows</td></tr>
<tr><td><b>Ctrl+D</b> Fill down (in a grid)</td><td><b>Ctrl+Shift+D</b> Fill column down</td><td><b>Ctrl+'</b> Copy cell above</td></tr>
<tr><td><b>Ctrl+Alt+C</b> or <b>F4</b> Calculator</td><td><b>Ctrl+click</b> a heading = filter</td><td><b>Right-click</b> a heading = menu</td></tr>
<tr><td><b>Del</b> Delete selected line</td><td><b>Ctrl+Del</b> Delete whole request</td><td><b>Ctrl+A</b> Select all</td></tr>
</table>
<h3>Inside Material Requests</h3>
<table border='1' cellpadding='5' cellspacing='0' width='100%'>
<tr><td><b>Alt+1 / Alt+2 / Alt+3</b> switch tab</td><td><b>Ctrl+Shift+P</b> Prepare all available</td></tr>
<tr><td><b>Ctrl+Return</b> Show details</td><td><b>Ctrl+D</b> Create Delivery Note (tab 3)</td></tr>
</table>
<h3>Excel-style column filters</h3>
<p>Every list in AURCO filters like a spreadsheet. <b>Ctrl+click</b> a column
heading (or right-click it) to tick exactly which values to show, search inside
the value list, and sort A→Z / Z→A. A filtered heading is marked <b>▼</b>, the
filter strip above the table names the active filters, and <b>Clear Filters</b>
resets everything. Totals and record counts always describe what is on screen,
and filters survive a refresh — but if new data can no longer match, the filter
clears itself rather than leaving you with an empty table.</p>
<p>Right-clicking a heading also fits, hides and restores columns.</p>

<h3>Calculator</h3>
<p><b>Ctrl+Alt+C</b> or <b>F4</b>, or the 🧮 button in the top bar. Type a whole
expression and press Enter — <code>12*8+150</code>, <code>(10+5)/3</code>,
<code>sqrt(144)</code>, <code>200+15%</code>. There is a running tape,
memory keys, quick +VAT / −VAT / per-unit buttons, and <b>Copy Result</b> so the
figure can go straight into a quantity cell.</p>

<h3>Re-ordering lines by drag</h3>
<p>Drag a row in any document grid to move it, or use <b>Ctrl+Up</b> /
<b>Ctrl+Down</b>. The order you set is the order that prints on the Delivery
Note, so lines can be arranged to match the physical picking order. Quantities,
PR numbers and remarks always travel with their row.</p>
<p>On the Material Request paste box you can also <b>drag an Excel or CSV file
straight onto the box</b> — it is loaded and checked immediately, exactly as if
you had used Load Excel / CSV.</p>

<h3>Excel-style fill in document grids</h3>
<p>Inside any Delivery Note / GRN / Return line grid:</p>
<ul>
<li><b>Ctrl+D</b> — copies the cell above into the current cell. With several rows
selected, the top row is copied into every selected row below it, exactly like
Excel.</li>
<li><b>Ctrl+Shift+D</b> — copies the current cell all the way down the column.</li>
<li><b>Ctrl+'</b> — copies just the single cell directly above.</li>
</ul>
<p>Ctrl+D only fills while a line grid has focus; everywhere else it still opens
the Documents page.</p>
<p><b>Barcode scanning:</b> focus any scan box and scan — the item is found and
added immediately. No mouse needed.</p>
"""),
    ("Items, barcodes and labels", """
<h2>Item Master</h2>
<p>Every stocked item lives here: code, description, category, UOM, brand, model,
barcode, min/max levels, location and rack. Import hundreds at once with
<b>Import from Excel</b>, which maps your columns to AURCO's fields.</p>
<h3>Balance, Reserved and Free to Use</h3>
<p>The grid shows three quantities side by side:</p>
<ul>
<li><b>Balance</b> — everything physically in the warehouse.</li>
<li><b>Reserved</b> — already prepared for an open material request but with no
Delivery Note yet. The material is still on the shelf, so the balance does not
change; it is simply promised to a project. Hover the amber figure to see which
MR numbers hold it.</li>
<li><b>Free to Use</b> — Balance minus Reserved. This is what a new request can
honestly be given.</li>
</ul>
<p>The reservation appears the moment a line is prepared or processed, and
clears by itself when the line is unprepared, the request is cancelled, or the
Delivery Note is created (at which point the stock really leaves and the balance
drops). <b>Reserved Stock Report</b> in the Report Center lists every
reservation line by line.</p>
<h3>Stock alerts</h3>
<p>Thresholds can be a percentage or a fixed quantity, set globally, per category
or per item. Items then show as Normal, Warning, Critical or Out of Stock, and the
dashboard counts each group.</p>
<h2>Barcode &amp; Label Designer</h2>
<p><b>Item Master → Barcode Designer.</b> Six symbologies (Code128, Code39,
EAN-13, EAN-8, QR, QR + Code128).</p>
<p>The <b>label text is fully customisable</b>. Each of the three lines accepts
placeholders such as <code>{code}</code>, <code>{description}</code>,
<code>{category}</code>, <code>{uom}</code>, <code>{brand}</code>,
<code>{warehouse}</code>, <code>{location}</code>, <code>{balance}</code>,
<code>{company}</code> and <code>{date}</code>, each with its own font, size and
alignment.</p>
<p>Also adjustable: what value is encoded, bar height and width, QR size, the
human-readable digits, a price line, the logo, colours, borders and cutting
guides. Choose a ready-made sheet template or a custom size, set copies per item
and a <b>start position</b> so a part-used sheet is not wasted. A live preview
redraws as you type, and designs can be saved by name. <b>Quick Labels</b>
reprints instantly with the last saved design.</p>
"""),
    ("Company details & Arabic letterhead", """
<h2>Company details and the Arabic letterhead</h2>
<p><b>Settings → Company &amp; Documents.</b></p>
<h3>VAT and C.R. numbers</h3>
<p>The English side of the letterhead has separate fields for the
<b>VAT Number</b> and the <b>C.R. Number</b>. (Before v2.15 the C.R. number was
printed but had no field, so it could not be corrected without editing the
database.)</p>
<h3>Correcting the Arabic side</h3>
<p>Under <b>Arabic text on printed documents</b> you can set:</p>
<ul>
<li><b>C.R. label (Arabic)</b> and <b>VAT label (Arabic)</b> — the wording,
e.g. س.ت and الرقم الضريبي</li>
<li><b>VAT number (Arabic side)</b> and <b>C.R. number (Arabic side)</b> — the
numbers themselves</li>
</ul>
<p>Leave the two number fields <b>blank</b> and the Arabic side simply follows
the English values, which is what you want unless the Arabic registration
genuinely differs. Fill one in and only the Arabic half of the letterhead
changes; the English half is untouched.</p>
<p>With <b>Use Arabic-Indic numerals</b> ticked the figures print as
٢٠٥١٠٦٢٨٨٤ instead of 2051062884.</p>
<p>Existing installations are migrated automatically — a letterhead saved with
the older tokens keeps printing exactly the same until you set an override.</p>
"""),
    ("Documents and sharing", """
<h2>Documents</h2>
<p>Every GRN, DN, Return, Transfer, Adjustment and Count is stored with its own
number: <code>DN-2026-00001</code>, <code>GRN-2026-00001</code> and so on.</p>
<h3>Delivery Note header</h3>
<p>Gate-pass style: From, Project, Vehicle, In Time, Out Time, plus the
<b>Handover To</b> driver with Iqama/ID and phone. Authorised signatures print
just above the footer line.</p>
<h3>File names</h3>
<p>Delivery Notes are saved as:</p>
<p><code>DN-2026-00821 Material Delivered (Main WH - Project Name) 001582 001601</code></p>
<p>The pattern is editable in <b>Settings → Company &amp; Documents → Delivery Note
file naming</b>, with a live preview and tokens such as <code>{docno}</code>,
<code>{ddmm}</code>, <code>{warehouse}</code>, <code>{project}</code>,
<code>{party}</code>, <code>{vehicle}</code> and <code>{prs}</code>. Empty fields
collapse instead of leaving stray brackets, characters Windows forbids are
removed, and a very long PR list is shortened with a "+N-more" marker.</p>

<h3>Drafts — and correcting a quantity</h3>
<p><b>Save as Draft</b> on Stock Out (or Stock In) stores the document without
moving any stock. To change it later, select it in <b>Documents</b> and press
<b>&#9998; Edit Draft / Re-open</b>: the document re-opens on the form it came
from, with an amber guidance bar. Adjust any quantity, PR number, line or header
field and press <b>Update Draft</b> (or <b>Save Again as Draft</b>) — the saved
draft is rewritten in place, so the new quantity is what you see after a
refresh, on the PDF, and on the stock that is posted when you press
<b>Finalize</b>. <b>Cancel editing</b> leaves the draft exactly as it was.</p>
<p>A quantity typed into the grid is committed even if you click a button while
the cell is still open, and lines sent in from <b>Bulk Stock Check</b> or a
<b>Material Request</b> arrive with their quantity and PR number already filled
in. A finalized document must first be corrected with <b>Reverse / Correct</b>,
which posts the opposite stock movement and regenerates the PDF into a dedicated
reversal folder. After reversing a <b>Delivery Note</b> or <b>Goods Receipt</b>,
you can reopen it and save it again as a <b>draft with the same number</b>.</p>

<h3>Excel in and out of the line grid</h3>
<p>Every transaction screen can exchange its item lines with Excel:</p>
<ul>
<li><b>&#128203; Paste from Excel</b> (or <b>Ctrl+V</b> inside the grid) opens a
preview sheet pre-filled from the clipboard. A header row such as
<i>Item Code · Description · Qty · PR / MR No. · Remarks</i> is recognised
automatically; without one the columns are read in that order. Tab-separated
(a normal Excel copy), CSV and space-padded text all work, and
<b>Load Excel / CSV file...</b> reads a whole .xlsx or .csv. Each row is matched
against the item master by code, barcode or alternate code — or by description —
and marked <i>found</i> / <i>not in item master</i>. Nothing is added until you
press <b>Add to document</b>, and an item already on the note has its quantity
updated instead of being duplicated. <b>Excel template</b> saves an empty sheet
with the correct headings.</li>
<li><b>&#128202; Export to Excel</b> saves the grid exactly as displayed to a
branded .xlsx (auto-filter, frozen header, totals) and opens it.
<b>Ctrl+C</b> copies the grid — or just the selected rows — for a direct paste
back into Excel. PR numbers keep their leading zeros.</li>
</ul>

<h3>Correcting the system stock from the Delivery Note</h3>
<p>If the <b>Available</b> figure on a delivery note line is wrong, fix it on the
spot: type the real counted quantity straight into the <b>Available</b> cell, or
select the line and press <b>&#9878; Adjust Stock (F4)</b> (also on the
right-click menu). The dialog shows the system quantity and lets you either set
the physical quantity or enter a &plusmn; difference; a <b>reason is mandatory</b>
and remarks are recommended.</p>
<p>Pressing <b>Post adjustment</b> writes a normal <b>Stock Adjustment (ADJ)</b>
document with a ledger entry and audit trail — it is <i>not</i> part of the
delivery note — and the Available column updates immediately. A correction that
would push the balance below zero is refused, and the action obeys the
<i>adjustments</i> permission. <b>&#128260; Refresh Stock</b> re-reads every
available quantity from the database, which is useful when another PC has moved
stock while your note was open.</p>

<h3>Attachments</h3>
<p>Every document form now has both <b>Attach Document</b> and <b>Paste Attachment</b>.
Paste accepts a copied file from Explorer or a copied screenshot / image from the
clipboard. Attachments are copied into the Attachments folder and merged into the
PDF <b>after</b> the document pages, so the printed pack is complete.</p>
<h3>Sharing</h3>
<p>Every screen has PDF, Excel, CSV, Print, Email and WhatsApp. Email needs SMTP
set up in Settings. WhatsApp opens with the message ready and the file's folder
open so you can attach it.</p>
<p><b>Global Search</b> now includes a <b>File Contents</b> tab that searches
searchable text extracted from PDFs, TXT/CSV notes, DOCX and XLSX files already
saved in documents, attachments and the document library.</p>
<p><b>AURCO PDF Studio</b> is the built-in advanced PDF tool. It provides page
viewing, zoom, rotate, search hits, thumbnails, drag-and-drop open, recent-file
history, annotations, signature-image pasting, merge/split/reorder/extract,
image/Word/Excel export, print-job preparation, sharing and password-protected
copies.</p>
<h2>General Delivery Note Maker</h2>
<p><b>Ctrl+G.</b> A fully branded delivery note for anything that is <i>not</i> a
stocked item — hired tools, a subcontractor's material, a sample. Lines are free
text, numbering is its own <code>GDN</code> series, and <b>no stock movement is
ever posted</b>. Supports Excel paste, optional prices, terms, reusable templates,
duplicating an old note, and supporting-document attachments including clipboard
paste. Attached files are appended after the base PDF pages.</p>
"""),
    ("Company Issuance Register", """
<h2>Company Issuance Register</h2>
<p><b>Ctrl+Shift+O.</b> Material issued to <i>other companies</i> — temporarily or
permanently — with a photograph kept as proof of every issue and every return.
It is <b>completely separate</b> from inventory: its own database file, its own
evidence folder, its own backups. Nothing here changes stock.</p>

<h3>Recording an issue</h3>
<p><b>Issuance Register → New Issue.</b> Fill in the company, recipient and Iqama
ID, the item and quantity, then attach the picture. Choose:</p>
<ul>
<li><b>Temporary</b> — you expect it back. Set an expected return date and the
system chases it for you.</li>
<li><b>Permanent</b> — it is gone for good. No return is ever chased.</li>
</ul>
<p><b>A picture is required.</b> A new issue will not save without at least one
photo, or a DN / gate-pass number as the reference. You can relax this with the
tick box at the bottom of the page, but it is on by default — that is the whole
point of the register.</p>
<p>Photographs are <b>copied</b> into the register's own Evidence folder, so the
proof survives even if the original picture is deleted from the phone.</p>

<h3>Recording a return</h3>
<p>Select the line and press <b>Record Return</b>. Partial returns are fully
supported — 3 of 5 back is a real state, and the line stays outstanding for the
other 2. The return can carry its own photograph.</p>

<h3>Status</h3>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Status</th><th>Meaning</th></tr>
<tr><td>Not Returned Yet</td><td>Out, still within the expected date</td></tr>
<tr><td>Partially Returned</td><td>Some came back, some is still out</td></tr>
<tr><td>Returned</td><td>Everything is back</td></tr>
<tr><td>Overdue</td><td>Past the expected return date — chase it</td></tr>
<tr><td>Permanent (No Return)</td><td>Issued for good, never chased</td></tr>
<tr><td>Lost / Written Off</td><td>Accepted as gone</td></tr>
</table>
<p>Status is recalculated automatically, so an item becomes Overdue simply
because time passed.</p>

<h3>Dashboard</h3>
<p>Sixteen KPI tiles — issues, companies, recipients, quantity issued and
returned, still out, overdue, worst overdue, proof coverage and value still out.
Every tile is clickable and drills through to the register with the same
filters. Charts cover company, recipient (who is holding what), most-issued
items, issued vs returned by month, outstanding ageing, status and evidence
coverage. A filter bar and a measure selector reshape the whole page.</p>

<h3>Evidence tab</h3>
<p>A gallery of every photograph in the register, with a preview pane. Tick
<b>Show issues with NO proof</b> to get the chase list of issuances that still
need a picture.</p>

<h3>Reports</h3>
<p>Fourteen, including Currently Outstanding, Overdue Returns, By Recipient
(custody), Missing Photo Proof, Ageing, Company × Status matrix and an Evidence
Index. The <b>Receipt PDF</b> prints a signed hand-over note for one issuance
with the photographs attached as extra pages.</p>

<h3>Bringing your existing sheet in</h3>
<p><b>Import Sheet.</b> Paste the rows straight from Excel. Your current column
names are recognised automatically — including the <i>Receipient</i> and
<i>Reamrks</i> spellings — dates like <b>21-Dec-25</b> are understood, and a
Remarks cell saying <i>Returned</i> or <i>Not Return yet</i> sets the status. A
DN number in the Evidence column is kept as the reference.</p>

<p><b>Backups:</b> the Backup button copies the database. The photographs live in
the Evidence folder — copy that folder too for a complete archive.</p>
"""),
    ("Document Library", """
<h2>Document Library — your scanned delivery notes</h2>
<p><b>Ctrl+L.</b> Point AURCO at the folders where signed delivery notes are
scanned and see every PDF and picture in one place, with a preview.</p>

<h3>Adding a folder</h3>
<p><b>Sync Folders → Add Folder...</b> Choose the folder on your drive or network
share. <b>Sub-folders are included</b>, so a structure like
<code>2026 / January / DN-2026-00821.pdf</code> is picked up exactly as the site
team filed it. PDF, JPG, PNG, TIFF and Office files are indexed.</p>
<p><b>Your files are never moved, renamed or deleted.</b> The library is only an
index — it records where each file is. "Remove from index" forgets the entry and
leaves the file untouched, and removing a sync folder does the same.</p>

<h3>Automatic linking</h3>
<p>A file named after its document number links itself to that record:
<code>DN-2026-00821 signed.pdf</code>, <code>DN_2026_00821.jpg</code> and
<code>DN 2026 821 copy.pdf</code> all resolve to <b>DN-2026-00821</b>. The
Linked column tells you which of three states a file is in:</p>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><td><b>✔ linked</b></td><td>The number matches a real record in AURCO</td></tr>
<tr><td><b>⚠ no record</b></td><td>A number was found but there is no such
document — usually a typo in the file name</td></tr>
<tr><td><b>— none —</b></td><td>No number in the file name. Use
<b>Link to Document</b> to attach it by hand.</td></tr>
</table>
<p>After importing older documents press <b>Re-link to Documents</b> and any scan
that could not be matched before will link itself.</p>

<h3>Browsing</h3>
<p>Search across file name, folder, document number, project, PR number and
tags. Filter by folder, sub-folder, file type, project, date, and by linked /
unlinked. Switch <b>Thumbnails</b> on for a picture grid, off for a plain list.
Selecting anything shows a live preview — PDFs are rendered, images shown
directly.</p>
<p>Buttons: <b>Sync Now</b>, <b>Open</b>, <b>Print</b>, <b>Show in Folder</b>,
<b>Link to Document</b>, <b>Copy Path</b>, <b>Export List</b> (Excel),
<b>PDF List</b> and <b>Remove from Index</b>.</p>

<h3>Missing scans</h3>
<p>If an indexed file is later deleted from the drive, the next sync flags it as
<b>MISSING</b> rather than quietly dropping it — so you can tell the difference
between "never scanned" and "the scan has been lost". Tick <b>Show missing
files</b> to list them.</p>

<h3>Overview</h3>
<p>Twelve tiles — documents indexed, PDFs, images, folders, sub-folders, how many
are linked, link coverage %, missing files and total size — plus charts by
sub-folder, file type, document type and month.</p>
"""),
    ("Admin Station", """
<h2>Admin Station</h2>
<p><b>Ctrl+Shift+A.</b> A stand-alone register for camp and office records. It is
<b>completely separate</b> from inventory: its own database file, its own backups
and its own reports. Nothing here ever changes stock.</p>
<h3>Dashboard</h3>
<p>A filter bar across the top drives the whole page: free text, camp, category,
destination, status, period, an outstanding-only switch, and a <b>measure</b>
selector that reshapes every chart by quantity, line count, value or outstanding
amount. Sixteen KPI tiles are clickable and drill through to the Records tab with
the same filters applied, and clicking a bar narrows the dashboard to that slice.
Charts cover camp, category, destination, issued-vs-returned by month, the volume
trend, return status, <b>outstanding ageing</b>, most-recorded items and
condition. <b>Export View</b> prints exactly what is on screen.</p>

<h3>Site Uploads Folder</h3>
<p><b>Admin Station → Site Uploads Folder.</b> Point AURCO at a folder on your
drive or network share. Each site admin saves their sheet there and you import
every new file in one click. AURCO remembers which files it has already read, so
the same sheet is never posted twice, guesses the sending site from the file
name, and can move imported files into an <i>Imported</i> sub-folder. If the
share is offline or read-only it says so plainly instead of failing mid-import.</p>

<h3>Uploading</h3>
<p>Paste rows from Excel or pick a file. A mapping wizard shows every uploaded
column, a sample value and the field it becomes — recognised headings match
automatically, even common misspellings. Dates in any usual format convert
themselves, and in the Return column a number works as well as the word
<i>Yes</i>. Duplicates are skipped, and <b>any import can be undone in one
click</b>.</p>
<h3>Reports</h3>
<p>Twelve, including a Camp × Category matrix, Pending Returns and Duplicate
Suspects. All print on the company letterhead.</p>
<p><b>Remember:</b> because it is deliberately separate, the Admin Station has its
own Backup button. The main database backup does not include it.</p>
"""),
    ("Cable Records", """
<h2>Cable Records <span style='color:#6b7c8f'>(Ctrl+Shift+B)</span></h2>
<p>Cable is not counted in pieces, it is counted in <b>metres left on a
drum</b> — so it gets its own register. Cable Records keeps its own database
file (<code>cable_records.db</code>), its own numbering, audit trail, backups
and reports. <b>Nothing here posts a stock movement.</b></p>

<h3>Three registers, one story</h3>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Tab</th><th>What it holds</th></tr>
<tr><td><b>🥁 Drum Register</b></td>
<td>Every drum: cable type, cores, size, voltage grade, armour, manufacturer,
batch, supplier, PO, GRN, test certificate, location — with its original
length and what is <b>still on it</b>.</td></tr>
<tr><td><b>✂ Cutting Log</b></td>
<td>Every length taken off a drum, or put back on it, tied to a cable tag, a
project, a receiver and a delivery note.</td></tr>
<tr><td><b>🧭 Cable Schedule</b></td>
<td>Tag by tag: from and to equipment, route, required length, which drum
served it, how much was pulled and the megger / IR test that closed it.</td></tr>
</table>

<h3>The remaining length is proved, never typed</h3>
<p>A drum's remaining length is derived from its own cutting log, so the
register can always be re-proved — <b>🧮 Rebuild Balances</b> recalculates every
drum from its history. Issuing more than is left is refused, and so is putting
back more than the drum ever held. Voiding a cut returns the length instantly.
Scrapping what is left needs a <b>mandatory reason</b> and is written to the
audit trail. A drum walks <i>In Stock → Partly Used → Empty</i> by itself, and
can be <b>Reserved</b> for a crew or a tag.</p>

<h3>Cutting a length</h3>
<p>Select the drum and press <b>✂ Issue Length</b>. Pick the cable tag and the
dialog fills the balance still to pull, the from/to equipment and the project;
type who received it and the DN number. The dialog shows what the drum will
hold afterwards <i>before</i> you save. <b>↩ Return Off-cut</b> is the same in
reverse. Every cut carries its own number (<code>CC-2026-00001</code>).</p>

<h3>The schedule follows the cuts</h3>
<p>A cut tied to a tag updates that tag by itself: pulled length, the drum(s)
that served it and the status. <b>✂ Pull From Drum</b> on the schedule tab does
it the other way round — it offers the drums that carry the right size and
takes the balance straight off the chosen one. <b>➡ Advance Status</b> walks a
tag through <i>Planned → Issued → Pulled → Glanded → Terminated → Tested →
Energized</i>, and <b>🎯 Record Test</b> stores the IR value in MΩ, the
continuity result, the tester and the certificate number.</p>

<h3>A dashboard you can shape</h3>
<p>Every tile and chart answers to the filter bar: text, drum status, cable
type, size, project, location, manufacturer, a period, <i>only drums with cable
left</i> and <i>only off-cuts</i>. The <b>Measure</b> selector switches the
charts between drums, length received, length remaining, length used and stock
value. <b>⚙ Customise</b> ticks which of the 29 KPI tiles and 15 charts and
tables you want, how many tiles sit on a row, <b>what length counts as an
off-cut</b> and after how many days a drum counts as <b>idle</b> — the layout
is stored with the module. Click any tile to drill into the register, or a bar
to filter by it. <b>Export View</b> prints exactly what the filters show.</p>

<h3>Off-cuts and idle drums — where the money is</h3>
<p>Two tiles pay for the module: <b>Off-cuts / Short Ends</b> lists the short
lengths worth using before a new drum is opened, and <b>Idle Drums</b> shows
what nobody has touched for months.</p>

<h3>Import and reports</h3>
<p><b>📥 Import from Excel</b> pastes an existing drum list straight in — a
header row is recognised automatically, existing drum numbers are updated and
new ones added, and <b>⬇ Excel template</b> gives the right headings. Sixteen
reports cover the register, stock summary, off-cuts, idle drums, the cutting
log, consumption by project and by tag, the schedule, cables not yet pulled,
the megger register, failed and pending tests, traceability (PO / GRN / batch /
certificate), stock value and the audit trail — all with PDF, Excel, CSV,
print and share.</p>
<p><b>Remember:</b> the module has its own <b>Backup</b> button. The main
database backup does not include it.</p>
"""),
    ("Tools, Instruments & Devices", """
<h2>Tools, Instruments &amp; Devices <span style='color:#6b7c8f'>(Ctrl+Shift+T)</span></h2>
<p>A <b>stand-alone custody register</b> for tools, instruments and devices,
built around the controlled form <i>WH-FRM-001 — Tools, Devices &amp;
Instruments Handover</i>. It answers one question: <b>who is holding which
tool, and since when.</b></p>
<p>It keeps its own database file (<code>tool_station.db</code>), its own
backups and its own reports. <b>Nothing here ever posts a stock movement</b> —
tool custody and warehouse stock are deliberately separate.</p>

<h3>The four transaction types</h3>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Type</th><th>What it means</th></tr>
<tr><td><b>Issue</b></td><td>Tool leaves the warehouse, open-ended custody</td></tr>
<tr><td><b>Transfer</b></td><td>Custody moves from one holder to another</td></tr>
<tr><td><b>Temporary Loan</b></td>
<td>Must come back by the Expected Return Date</td></tr>
<tr><td><b>Return</b></td><td>Tool comes back, closing an earlier handover</td></tr>
</table>

<h3>The dashboard is yours to shape</h3>
<p>Everything on the Dashboard tab answers to the filter bar at the top:
free text, transaction type, status, project, custodian, tool category,
warehouse, a period (or a custom date range), <i>only still out</i> and
<i>only overdue</i>. The <b>Measure</b> selector decides what the charts count
— documents, quantity handed over, or quantity still out.</p>
<p>Press <b>&#9881; Customise</b> to tick exactly which KPI tiles, charts and
tables you want and how many tiles sit on a row. The layout is stored in the
module's own database, so it is still there tomorrow. <b>Click any tile</b> to
open the register on precisely those documents, and click a bar in the project,
custodian, type or category chart to filter the whole dashboard by it.
<b>Export View</b> prints a PDF (or Excel) of exactly what the filters show,
with the KPI figures across the top.</p>

<h3>The reference number does the filing for you</h3>
<p>A reference such as <code>WH-087IS2308202601</code> is self-describing and is
decoded on sight: warehouse <b>WH</b>, project <b>087 → PRJ000087</b>, type
<b>IS = Issue</b>, date <b>23/08/2026</b>, sequence <b>01</b>. Because of that,
a folder of signed PDFs can be filed with nothing typed by hand.</p>

<h3>Sync Folder — the point of the module</h3>
<p>Point AURCO at the folder your signed handover forms sync to — a network
share, OneDrive or Google Drive. Press <b>Sync All Folders</b> and every PDF is
read: the reference is decoded and the whole form is filed, including the
custodian, iqama ID, mobile, project, and every item line with its asset ID,
serial number, make, condition grade and calibration date. Syncing twice never
double-posts the same form.</p>
<p><b>Files are only ever read.</b> Nothing in the synchronised folder is moved,
renamed or deleted — it belongs to whoever syncs it.</p>

<h3>The unified filter</h3>
<p>Every document type appears in <b>one consistent shape</b>, so Issues,
Transfers, Loans and Returns can be compared directly. Filter by type, status,
project, custodian or date range, tick <b>Overdue only</b> or <b>Outstanding
only</b>, or simply search by asset ID, serial number, iqama or project.
<b>Show one row per item</b> switches the grid between one row per document and
one row per tool.</p>

<h3>How custody is tracked</h3>
<ul>
<li>Returns can be <b>partial</b> — bring back 1 of 6 items and the handover
becomes <i>Partially Returned</i>, not closed.</li>
<li>Returning more than is outstanding is <b>blocked</b>.</li>
<li>A transfer closes the source as <b>Transferred Out</b>, never
<i>Returned</i> — the tools never came back to the warehouse, and the record
stays honest about that.</li>
<li>A Temporary Loan past its Expected Return Date turns <b>Overdue</b> by
itself and reports how many days late it is.</li>
</ul>

<h3>Assets — where is it now</h3>
<p>Built automatically from the handover history: current status (In Store /
Issued Out / On Loan / Overdue), who holds it, which project, its condition,
calibration due date and days remaining — plus the complete movement history of
that one tool.</p>

<h3>Reports</h3>
<p>Sixteen, including <b>Outstanding Custody</b>, <b>Overdue Loans</b>,
<b>Custody by Person</b>, <b>Asset Register (Where Is It Now)</b>,
<b>Calibration Due</b>, <b>Damaged / Defective Items</b> and <b>Missing
Documents &amp; Signatures</b> — the governance report that lists which
controlled forms are still missing a signature, a verification tick or a
scanned copy.</p>
<p><b>Print Form</b> reprints any handover in the controlled WH-FRM-001 layout,
with the ticked transaction type, the item grid, the verification boxes and both
signature blocks sitting directly above the footer rule.</p>
"""),
    ("Reports and dashboard", """
<h2>Dashboard</h2>
<p>KPI tiles for stock value, low/critical/out-of-stock counts, today's movements
and open material requests. <b>Every tile is clickable</b> and opens the records
behind it. Charts cover monthly in/out, stock health, category, warehouse, UOM
and consumption trend.</p>
<h2>Report Center</h2>
<p><b>Ctrl+R.</b> 33 reports with date, category, warehouse and text filters.
Choose which columns to include, toggle totals and striping, then export to PDF,
Excel or CSV. Exports print the filter context so a printed report always says
what it covers.</p>
<h3>Project closure</h3>
<p>When a job finishes and the site returns its material, three reports answer
"what did we actually get back?" — filter them with the <b>project</b> box at the
top of the Report Center.</p>
<ul>
<li><b>Project Closure Reconciliation</b> — per item: issued, returned good,
returned damaged, <b>unaccounted</b>, over-returned, recovery % and the value of
the loss.</li>
<li><b>Project Loss &amp; Damage Summary</b> — one line per project with the
recovery percentage and total loss + damage value, worst first.</li>
<li><b>Project Material Ledger</b> — every issue, return and damage movement for
the job, in date order, as the audit backing for the two above.</li>
</ul>
<p>The arithmetic is <code>unaccounted = issued − returned good − returned
damaged</code>. A return booked against a Delivery Note is credited to that
note's project even when the return itself names no project. If more comes back
than went out, it is shown as <b>over-returned</b> rather than hidden — that
usually means material was returned against the wrong job or booked twice.</p>

<h3>Reports people use most</h3>
<ul>
<li><b>Current Stock</b> — what is on hand right now</li>
<li><b>Low / Critical / Out of Stock</b> — what to buy</li>
<li><b>Stock Valuation</b> — what it is worth</li>
<li><b>Delivery Note Report</b> — what went out and to whom</li>
<li><b>PR-wise Issue Report</b> — everything issued against one PR</li>
<li><b>Item Movement History</b> — the full story of one item</li>
</ul>
"""),
    ("Data safety and multi-PC", """
<h2>Backups</h2>
<p><b>Ctrl+B</b> backs up immediately. Automatic backup on exit is on by default
and old copies are pruned. <b>Settings → Backup</b> also restores — a safety copy
is always taken first.</p>
<h3>Integrity check</h3>
<p><b>Settings → Maintenance</b> reconciles every item balance against the ledger
and reports any difference. <b>Repair balances</b> rebuilds balances from the
ledger, which is always the source of truth.</p>
<h2>Running on more than one PC</h2>
<ol>
<li>Install the application <b>locally on each PC</b>.</li>
<li>Put only the <b>data folder</b> on the shared drive.</li>
<li>Point every PC at that same folder in the Storage Wizard.</li>
</ol>
<p>Document numbers stay unique across machines and each user's role controls
what they may do.</p>
<p><b>Important:</b> if a PDF or Excel file is open in another program, Windows
locks it and it cannot be overwritten. Close the file before reprinting the same
document.</p>
<p>AURCO now includes its own <b>built-in PDF viewer</b> for document files, which
helps connected PCs review the same shared PDF inside the system without needing
a separate desktop viewer.</p>
<h2>Users and roles</h2>
<p>Administrator, Manager, Storekeeper and Viewer. Turn on <b>Require login</b> in
Settings → Security. Deleting or reversing a document can require an
administrator password. The <b>Audit Trail</b> records who did what and when.</p>
<p>Packaged Windows copies can also require an offline <b>license key</b> per PC:
the user copies the Installation ID, the developer issues the key, and the app
activates locally without depending on the shared database.</p>
"""),
    ("File protection", """
<h2>File protection — nothing gets deleted</h2>
<p><b>Settings → 🔒 File Protection.</b> On by default.</p>
<h3>What you actually get</h3>
<ol>
<li><b>AURCO never deletes a file.</b> This is a guarantee. Pressing delete in
the application moves the file into an <code>_Archive</code> folder beside it;
the bytes stay on the disk and can be restored with one click.</li>
<li><b>Windows blocks casual deletion.</b> Every stored file is set read-only —
which on Windows really does stop Explorer deleting it — and every AURCO folder
gets a permission that denies DELETE to ordinary users. A storekeeper cannot
remove anything by accident or on purpose.</li>
<li><b>Tampering is detected.</b> The size and SHA-256 fingerprint of every file
is recorded. <b>Verify Now</b> reports anything missing or altered, even if it
was removed from outside the application.</li>
</ol>
<h3>What no software can promise</h3>
<p>A machine <b>Administrator</b> can always take ownership of a folder and
strip any permission, and nobody can stop a disk being formatted. Any program
that claims otherwise is not telling you the truth. What AURCO does instead is
make deletion <i>impossible through the app</i>, <i>hard through Windows</i>,
and <i>always visible</i> afterwards.</p>
<p>For a genuine "nobody can delete", combine this with protection outside the
application: put the data folder on a network share where users are granted
Read and Write but <b>not</b> Delete, and keep backups on a separate target.</p>
<h3>Day to day</h3>
<ul>
<li><b>Protect All Folders Now</b> — apply protection after adding new files</li>
<li><b>Verify Now</b> — full integrity check</li>
<li><b>Show Issues</b> — anything missing or altered</li>
<li><b>Archived Files</b> — everything that was "deleted" but kept, with restore</li>
<li><b>Lift Protection</b> — administrator only, for maintenance or migration</li>
</ul>
<p>The live database is deliberately left writable — SQLite must be able to
write to it — but it is backed up on every exit and covered by the tamper
ledger.</p>
"""),
    ("Troubleshooting", """
<h2>Troubleshooting</h2>
<table border='1' cellpadding='6' cellspacing='0' width='100%'>
<tr><th>Symptom</th><th>What to do</th></tr>
<tr><td>"Cannot save / file in use"</td>
<td>The PDF or Excel file is open in another program. Close it and try again.</td></tr>
<tr><td>A request will not delete</td>
<td>Material has already been delivered against it. Use <b>Cancel Request</b>
instead — deleted delivery history would break the audit trail.</td></tr>
<tr><td>An item shows "not in item master"</td>
<td>Use <b>Link to Item</b> to map it to an existing item, or <b>Create Item</b>
to add it.</td></tr>
<tr><td>Balance looks wrong</td>
<td>Settings → Maintenance → <b>Validate</b>, then <b>Repair balances</b>.</td></tr>
<tr><td>Stock will not go out</td>
<td>The quantity exceeds free stock, or it is reserved for another request.
Check the Reserved and Available columns.</td></tr>
<tr><td>Report is empty</td>
<td>Widen the date range — it defaults to the last 12 months.</td></tr>
<tr><td>The header form will not reopen</td>
<td>Fixed in v2.6 — the Hide/Show details button now toggles properly. If an old
screen still opens collapsed, click <b>Show details</b> once and it is remembered.</td></tr>
<tr><td>"Cannot delete this file"</td>
<td>Working as intended — file protection is on. Use Settings → File Protection →
Lift Protection if an administrator really must remove something.</td></tr>
<tr><td>A file is reported MISSING</td>
<td>It was deleted from outside AURCO. Restore it from Backups, or from
Settings → File Protection → Archived Files if AURCO archived it.</td></tr>
<tr><td>Arabic text looks wrong</td>
<td>Settings → Appearance → Arabic font style. Kufi matches the letterhead.</td></tr>
<tr><td>Label text is cut off</td>
<td>Reduce the font size or increase the label size in the Barcode Designer. The
live preview shows the result immediately.</td></tr>
</table>
<h3>Still stuck?</h3>
<p>Settings → Maintenance → <b>Open log folder</b> and send the newest log file
along with a description of what you were doing.</p>
"""),
]


class UserManualDialog(QDialog):
    """Searchable manual. F1 anywhere in the application."""

    def __init__(self, db: Database, parent=None, topic: str = ""):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(f"User Manual — {config.APP_NAME}")
        self.resize(1060, 760)
        self.setModal(False)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)

        top = QHBoxLayout()
        self.search = W.SearchBox("Search the manual — type a word and press Enter")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        top.addWidget(W.button("📄  Save as PDF", "Accent", self._pdf,
                               tip="Print the whole manual"))
        top.addWidget(W.button("✕  Close", slot=self.close))
        v.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMaximumWidth(250)
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setStyleSheet("QTextBrowser{padding:10px; font-size:13px;}")
        split.addWidget(self.view)
        split.setSizes([250, 810])
        v.addWidget(split, 1)

        self.hint = QLabel("Press <b>F1</b> any time to reopen this manual.")
        self.hint.setStyleSheet(f"color:{W.MUTED};")
        v.addWidget(self.hint)

        self._fill()
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        if topic:
            self.goto(topic)
        else:
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------ helpers
    def _fill(self, needle: str = ""):
        self.list.clear()
        self._shown = []
        for title, body in SECTIONS:
            if needle and needle not in (title + body).lower():
                continue
            self.list.addItem(QListWidgetItem(title))
            self._shown.append((title, body))
        if self._shown:
            self.list.setCurrentRow(0)
        else:
            self.view.setHtml("<h3>Nothing found</h3><p>Try a different word.</p>")

    def _filter(self, text: str):
        self._fill(text.strip().lower())

    def _show(self, row: int):
        if 0 <= row < len(getattr(self, "_shown", [])):
            self.view.setHtml(self._shown[row][1])
            self.view.verticalScrollBar().setValue(0)

    def goto(self, topic: str):
        for i, (title, _) in enumerate(getattr(self, "_shown", [])):
            if topic.lower() in title.lower():
                self.list.setCurrentRow(i)
                return

    def _pdf(self):
        try:
            f = manual_pdf(self.db)
        except Exception as exc:  # noqa: BLE001
            W.error_box(self, f"Could not build the manual PDF.\n\n{exc}")
            return
        W.toast(self, f"Manual saved: {f.name}")
        D.open_path(f)


def _blocks(html: str) -> list[tuple[str, object]]:
    """Small HTML reader for the PDF version.

    Returns ("h3"|"li"|"p", text) or ("table", [[cell, ...], ...]) so real
    tables print as real tables instead of pipe-separated text.
    """
    import re

    out: list[tuple[str, object]] = []
    pos = 0
    pattern = re.compile(
        r"(?is)<h2>(?P<h2>.*?)</h2>|<h3>(?P<h3>.*?)</h3>|<li>(?P<li>.*?)</li>"
        r"|<p>(?P<p>.*?)</p>|<table[^>]*>(?P<tbl>.*?)</table>")
    for m in pattern.finditer(html):
        pos = m.end()
        if m.group("h2"):
            out.append(("h2", m.group("h2")))
        elif m.group("h3"):
            out.append(("h3", m.group("h3")))
        elif m.group("li"):
            out.append(("li", m.group("li")))
        elif m.group("p"):
            out.append(("p", m.group("p")))
        elif m.group("tbl") is not None:
            rows = []
            for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", m.group("tbl")):
                cells = re.findall(r"(?is)<t[hd][^>]*>(.*?)</t[hd]>", tr)
                if cells:
                    rows.append(cells)
            if rows:
                out.append(("table", rows))
    return out


def manual_pdf(db: Database, out_path: str | Path | None = None) -> Path:
    """Render the whole manual as a branded PDF."""
    import datetime as _dt
    import re

    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    out = Path(out_path) if out_path else (
        config.folder("Reports") /
        f"AURCO_User_Manual_{_dt.datetime.now():%Y%m%d}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    primary, accent = D._brand_colors(db)

    story: list = [Paragraph("AURCO Inventory Manager", D.P_TITLE),
                   D._rule(primary, accent, 186 * mm),
                   Paragraph("User Manual", D.P_SUB), Spacer(1, 5 * mm),
                   Paragraph("Contents", D.P_MD), Spacer(1, 2 * mm)]
    for i, (title, _) in enumerate(SECTIONS, 1):
        story.append(Paragraph(f"{i}.&nbsp;&nbsp;{title}", D.P_SM))
    story.append(PageBreak())

    def clean(t: str) -> str:
        t = re.sub(r"(?is)<(th|td)[^>]*>", "", t)
        t = re.sub(r"(?is)</(th|td|tr)>", "", t)
        t = re.sub(r"(?is)<code>(.*?)</code>", r"<font face='Courier'>\1</font>", t)
        t = re.sub(r"(?is)<(?!/?(b|i|u|br|font|sub|super)\b)[^>]*>", "", t)
        return re.sub(r"\s+", " ", t).strip()

    for n, (title, body) in enumerate(SECTIONS, 1):
        story += [Paragraph(f"{n}. {title}", D.P_TITLE),
                  D._rule(primary, accent, 186 * mm), Spacer(1, 3 * mm)]
        for kind, payload in _blocks(body):
            if kind == "table":
                rows = [[clean(c) for c in r] for r in payload]
                ncol = max(len(r) for r in rows)
                rows = [r + [""] * (ncol - len(r)) for r in rows]
                head, data = rows[0], rows[1:]
                if not data:
                    head, data = [f"" for _ in head], rows
                story += [Spacer(1, 1.5 * mm),
                          D._grid(head, data, [186 * mm / ncol] * ncol, font=7.6,
                                  header_color=primary),
                          Spacer(1, 2.5 * mm)]
                continue
            text = clean(payload)
            if not text or kind == "h2":
                continue
            if kind == "h3":
                story += [Spacer(1, 2.5 * mm),
                          Paragraph(f"<b>{text}</b>", D.P_MD), Spacer(1, 1 * mm)]
            elif kind == "li":
                story.append(Paragraph(f"\u2022&nbsp;&nbsp;{text}", D.P_SM))
            else:
                story += [Paragraph(text, D.P_SM), Spacer(1, 1.5 * mm)]
        if n < len(SECTIONS):
            story.append(PageBreak())

    D._build_with_totals(out, story, False, db, "__default__",
                         lambda total: D._header_footer(db, "User Manual", True,
                                                        total_pages=total))
    db.audit("EXPORTED", "manual", "", f"PDF -> {out.name}")
    return out
