# AURCO Inventory Manager v2.28.23

## Instrument Station mapping fix

This release fixes the **Site-wise Excel Sync** issue where some Excel workbooks could open with **nothing mapped** even though the instrument columns were present.

### What was fixed

- Improved Excel workbook reading so Instrument Station now scans **all sheets** in the workbook, not only the active sheet.
- The importer automatically chooses the sheet that best matches the instrument column structure.
- Improved automatic heading recognition with more tolerant/fuzzy matching.
- Improved the failed-file note when no recognisable instrument columns are found.

### Result

Instrument sheet files with headings such as:
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

now map correctly more reliably, including when:
- a cover sheet exists before the real data sheet
- title rows appear before the real header row
- header text contains small wording/extensions around the expected labels

### Validation

- `py_compile` passed on the updated Instrument Station modules and tests.
- Full regression suite passed.
- Latest result: **ALL 1391 CHECKS PASSED**.
