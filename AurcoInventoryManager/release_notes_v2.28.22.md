# AURCO Inventory Manager v2.28.22

## Instrument Station Excel sync fix

This release fixes the Instrument Station sync issue where an Excel template file could appear as **Unreadable** in the signed handover folder area.

### What was fixed

- The **Signed Handover PDF** sync now reads **PDF files only**.
- Excel / CSV sheet files are no longer incorrectly listed there as unreadable handover files.
- Spreadsheet files are now clearly treated as belonging to the **Site-wise Excel Sync** workflow instead.

### Excel sync usability improvements

- Reworked the **Sync Folder** page into two clearer inner tabs:
  - **Signed Handover PDFs**
  - **Site-wise Excel Sync**
- Added clearer on-screen guidance explaining which sync mode to use.
- Added the exact expected sample headings on screen:
  - Instrument Description
  - Serial No.
  - Make / Model
  - Location
  - Quantity
  - Status
  - Issued To / Employee Name
  - Employee Code
  - Iqama ID
  - Designation
  - Division/Department
  - Current Project
  - Issued By
  - Remarks
  - Picture Path
- Wrapped the Site-wise Excel Sync area in a scrollable layout so the folder settings, file history, mapping/import actions, and inventory details display properly on screen.

### Mapping / import support

- Confirmed the Excel sync reader correctly detects the real header row even when title rows come before it.
- Confirmed the mapping engine recognises the user’s exact instrument column names.
- Confirmed the mapping preview builds usable instrument records from that Excel template structure.

### Validation

- `py_compile` passed on the updated Instrument Station modules and tests.
- Full regression suite passed.
- Latest result: **ALL 1391 CHECKS PASSED**.
