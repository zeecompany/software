# AURCO Inventory Manager v2.28.20

## Tools Station restored and rebuilt

This version restores **Tools Station** as a dedicated module and rebuilds it around the requested Excel/site workflow.

### Highlights
- Restored **Tools Station** in navigation as its own page
- Kept **Analytics** as a separate module
- Reworked site Excel sync around the requested sheet structure
- Added support for:
  - employee code
  - iqama / national ID
  - designation
  - division / department
  - picture path
- Added return/transfer picture-path support
- Added site-sync movement event history
- Expanded register/detail/history views with employee and picture columns
- Updated Tools Station PDF layout with richer custody details
- Upgraded dashboard KPI coverage for:
  - total tools
  - available
  - issued
  - transferred to sites
  - returned
  - pending / missing
  - synced Excel files
  - sites covered

## Validation
- `py_compile` passed
- full regression suite passed: **1384 / 1384**

## Package
- `/home/user/software/software v 44.zip`
