# AURCO Inventory Manager v2.28.25

## 1. Employee PPE Register — import and export on the Register tab

The **Register** tab now has its own sheet row under the record buttons:

* **⬆ Import Excel / CSV** — pick a PPE sheet and AURCO reads it straight into
  the register. Before anything is written you see the **column mapping** it
  detected (employee code, name, project, item, size, qty, UOM, DN number,
  remarks, return date…) and can change or ignore any column. Duplicates are
  skipped, every column maps to a real register field, and the whole import can
  be undone from the **Import Sheet** tab, exactly like before.
* **⬇ Template** — an empty Excel sheet with the register column headings.
* **Export this view** — **Excel**, **PDF**, **CSV** and **Print** of the rows
  currently on screen, filters included. What you see is what you get: the same
  columns, the same order, the same totals row as the other AURCO reports.
* The **Synced DN Records** tab got the same four export buttons for the
  Delivery-Note rows.

Registered/imported rows are always **register** rows — a sheet import can never
create a DN-synced record.

## 2. PPE Dashboard no longer picks up Delivery-Note synced data

The dashboard now reports the **PPE register**: manual issues plus Excel / CSV
imports. Records that the DN sync created are excluded from the KPI tiles,
charts, the month graph and the "latest issues" list, so DN activity can never
be mistaken for register activity.

* The old *All Sources / MANUAL / DN* selector is replaced by a single
  **Include DN-synced records** tick box. It starts **off**, and while it is off
  the *Synced from DNs* and *Delivery Notes* tiles and the *Source Split* chart
  stay hidden.
* A line under the tiles always states the scope on screen, for example:
  *Scope: **PPE register only** — manual issues and Excel / CSV imports.
  12 DN-synced record(s) (46.00 qty) are excluded.*
* Tick the box and the DN records come back into every number on the page; the
  DN tabs themselves are unchanged.

## 3. One Delivery Note = exactly one file (picture attachments)

Attaching a picture no longer produces a "without photos" and a "with photos"
copy of the same Delivery Note, and no third work file either:

* The merge and page-count work files used to be written **next to** the
  finished PDF (`….merged.pdf`, `….count.pdf`, `….pdf.tmp`). An interrupted save
  or a PDF that was open in another program left them behind — that is why one
  DN could show up as three files. They are now written in a `_temp` scratch
  folder and removed after every render; nothing extra is ever left beside the
  document.
* If the finished PDF is open in another program and cannot be replaced, AURCO
  no longer leaves a second "with photos" file behind: it keeps the single
  official file, writes a warning to the audit trail and reports it.
* The merged document is a **single PDF**: the DN pages plus the picture pages.
* The picture itself is stored **once**, under
  `Attachments/DN/<DN number>/`; the clipboard/drop staging copy is deleted as
  soon as the attachment is filed.
* Every document renders, finalizes and re-prints through
  `one_file_per_document()`, which keeps the newest official file and removes any
  other copy of that document found in AURCO's folders (including leftovers in
  `Reports/`, the PDF Studio export folder and copies with `(1)`/` copy` in the
  name).

### Cleaning the folders you already have

Two one-click repairs were added for the extra copies older versions left in
your storage:

* **Documents → 🧹 One File per Document** — cleans the selected document, or
  every document when nothing is selected, and lists exactly what was removed
  and what was kept.
* **Settings → Backup & restore → 🧹 Clean Duplicate Files** — the same sweep
  from the maintenance row, with a dry-run summary and a confirmation first.

While **File Protection** is on (the default), removed duplicates are moved into
the document folder's `_Archive` sub-folder instead of being destroyed, so no
byte is ever lost. The `_Archive` behaviour of protection was also hardened —
the bookkeeping table is created on demand, which previously made the first
archive fail halfway.

## 4. Dependency pin: PySide6 < 6.12

While testing this build, PySide6 **6.12.0** was found to abort the interpreter
with a fatal `none_dealloc: deallocating None` refcount error the moment a table
cell is written with `QTableWidgetItem.setData()` — which every AURCO list uses.
The same code runs cleanly on 6.11 and older. `requirements.txt` now pins
`PySide6>=6.6,<6.12` so a source install cannot pick up the broken release.

## Tests

`tests/run_tests.py` gained 26 checks covering all of the above (register
import + export, dashboard scope and hidden tiles, one file per DN with planted
leftovers, work-file placement, staging-copy cleanup) — **ALL 1431 CHECKS
PASSED**.
