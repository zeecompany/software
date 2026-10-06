# AURCO Inventory Manager v2.28.21

## Instrument Station replaces Tools Station

This release removes the visible **Tools Station** module and replaces it with the new **Instrument Station** module, aligned to the user-provided instrument sheet layout.

### What changed

- Renamed the visible module in navigation, page titles, dashboard wording, exports, backup/restore prompts, user manual text, and related analytics references from **Tools Station** to **Instrument Station**.
- Changed the standard module storage folder to **Instrument Station**.
- Added automatic migration support from older legacy folders:
  - `Tools Station`
  - `Tools, Instruments & Devices`
  - `Tool Station`
- Kept the separate-module architecture and its own standalone database (`tool_station.db`) with no stock impact.

### Instrument-focused sync and dashboard

- Preserved and adapted the Excel/site-sync workflow around the instrument-style sheet structure.
- Updated sample/export naming to **Instrument Station**.
- Kept the site-wise Excel/CSV import, folder sync, file history, sync runs, and inventory preview.
- Kept Analytics integration for synced site inventory visibility.

### Manual instrument custody actions

- Added direct **manual instrument entry** inside the synced inventory area.
- Added direct **Edit Selected**, **Transfer Selected**, and **Return Selected** actions.
- Added **Picture Proof** capture/path support in the manual instrument dialog.
- Added movement-history logging for manual actions so add / transfer / return activity is tracked alongside sync-driven changes.
- Added quick **Open Picture Proof** access from the inventory preview.

### Validation

- `py_compile` passed on the updated Instrument Station/core/UI modules.
- Full regression suite passed.
- Latest result: **ALL 1387 CHECKS PASSED**.
