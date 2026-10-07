# AURCO Inventory Manager v2.28.24

## Instrument Station — rebuilt on your Excel sheet

Everything in the Instrument Station now follows the sheet columns you sent,
column for column, and nothing else:

| Column |
|---|
| Instrument Description |
| Serial No. |
| Make / Model |
| Location |
| Quantity |
| Status |
| Issued To / Employee Name |
| Employee Code |
| Iqama ID |
| Designation |
| Division/Department |
| Current Project |
| Issued By |
| Remarks |

*(plus **Picture Path** and **Site Name**, kept behind the scenes for the
picture proof and for the folder sync)*

### The register
The **Instruments** tab is that sheet: same headings, same order, sortable,
filterable (text, status, location, division, project, *issued only*, *with
picture*), with the picture of the selected instrument and its own track record
beside the grid. **Excel** and **PDF** buttons export exactly what is on screen.

### Dashboard
KPI tiles and charts built only from those columns — instruments, total
quantity, issued/with an employee, in store, employees holding, locations,
movements in the last 30 days, with a picture. Status donut, location chart,
employee chart, instrument chart, project chart and the monthly handover trend,
plus the latest movements. Click a tile or a bar to open the register on exactly
those instruments.

### Manual entry with picture proof
**➕ New Entry** — one form with every register column. **Choose picture**
*copies* the photo into the module's own Pictures folder (your original file is
never moved or renamed). **View** opens it at full size. The register shows a ✓
in the Picture column.

### Issue · Transfer · Return
Select an instrument and press **Issue**, **Transfer** or **Return** — one
dialog does all three, with date, quantity, status, remarks and picture.

* **Issue** hands it to an employee.
* **Transfer** moves custody from the present holder to another employee — both
  names stay on the movement line.
* **Return** takes it back into store, clears the holder and sets the status
  back to Available.

Every movement gets its own reference (`IS-261007-01`, `TR-…`, `RT-…`) and is
written into the instrument's own history, so **when it was handed over, to
whom, by whom, and when it came back** is always answerable. **🖨 Slip** prints
a signed handover / transfer / return slip with the picture proof on it.

### Employee Code fills the rest
Type the **Employee Code** (or the Iqama ID, or pick the name): the name, Iqama,
designation, division and current project are read from the **Employee Master**
and filled in — and stamped onto the movement line so the history keeps them as
they were on the day of the handover. If the person is not registered yet, the
details typed by hand are saved as they are.

### Movements tab
Every handover, transfer and return: date, reference, movement type, instrument,
serial, from, to, employee code, Iqama, designation, division, project, location,
quantity, issued by and remarks — filterable by text, type and date range, and
exportable to Excel / PDF / print.

### Excel Sync
Point at the folder(s) the sites drop their Excel files into and press
**Sync all folders**: every `.xlsx`, `.xlsm`, `.csv` and `.txt` file inside them
(sub-folders included) is read into the register.

* The reader finds the real heading row even behind a company title or a cover
  sheet, and matches all fourteen columns automatically.
* The mapping dialog lets you correct any column and preview the rows before
  importing.
* **Excel template** gives you a sheet with exactly these headings for the sites.
* Importing twice never duplicates — rows are matched on the serial number (or
  the description and make), and only real changes are written. A change of
  holder in the sheet becomes a **Transfer** in the track record.
* **Files are only ever read** — nothing in the folder is moved, renamed or
  deleted. Tick **Auto** to re-read a folder on a timer.

### Reports
Twelve reports, each with PDF, Excel, CSV and print: Instrument Register (every
column), Issued / Handed-over, In Store, By Location/Site, By Employee
(custody), By Instrument Description, By Project, Status Summary, Movement
History, Transfers Between Employees, Returns to Store and Instruments Without a
Picture.

### Also in this version
* The module's own database is now `instrument_station.db` inside the
  **Instrument Station** folder; an existing `tool_station.db` is adopted
  automatically (copied, never moved) and its rows are carried over.
* The separate **Analytics → Site Sync** tab reads this same register and shows
  location-wise quantity, status mix, project-wise quantity, employee custody
  and the latest movements.
* The in-app User Manual and the User Guide rewrite the Instrument Station
  chapter around the new register.

### Validation
Full regression suite: **ALL 1405 CHECKS PASSED** (99 checks in the three
Instrument Station sections alone).
