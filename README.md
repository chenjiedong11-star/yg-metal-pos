# SCRAPGOGO POS — YG Metals

Streamlit-based Point-of-Sale system for scrap metal recycling.

## Quick Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Project Structure

```
app.py                  ← Thin entry point (routing + page config)
core/
  config.py             ← Global constants (DB_PATH, receipt format, etc.)
  state.py              ← Session-state init + Phase-2 ticketing state machine
  utils.py              ← Pure helper functions (calc_line, recompute_receipt_df)
db/
  connection.py         ← SQLite connection pool, context manager, qdf/qone/exec_sql
  schema.py             ← CREATE TABLE + seed data (init_db)
  repo_ticketing.py     ← Ticket/receipt CRUD (finalize_ticket is atomic)
  repo_customers.py     ← Client CRUD
  repo_products.py      ← Materials, categories, operators, settings
services/
  ticketing_service.py  ← add_line_to_receipt, receipt HTML formatters
  report_service.py     ← Summary queries, report HTML builder
  export_service.py     ← Excel export
ui/
  page_ticketing.py     ← 开票 page (Streamlit widgets only)
  page_manage.py        ← 管理 page + all sub-pages
  page_report.py        ← Report page (extension point)
components/
  keypad.py             ← On-screen keypad + Enter workflow JS
  printer.py            ← All print-related JS injection
  navigation.py         ← CSS, top bar, page switching
```

## Where to Change What

| I want to…                        | Edit this file              |
|-----------------------------------|-----------------------------|
| Change DB schema                  | `db/schema.py`              |
| Add a new DB query                | `db/repo_*.py`              |
| Change how tickets are saved      | `db/repo_ticketing.py`      |
| Change receipt formatting/layout  | `services/ticketing_service.py` |
| Change business rules             | `services/*.py`             |
| Change UI layout / widgets        | `ui/page_*.py`              |
| Change keypad behavior            | `components/keypad.py`      |
| Change print behavior             | `components/printer.py`     |
| Change navigation / CSS           | `components/navigation.py`  |
| Change session-state keys         | `core/state.py`             |
| Change global constants           | `core/config.py`            |

## Architecture Rules

1. **`ui/`** contains Streamlit rendering only — no SQL, no business rules.
2. **`services/`** contains business rules — pure Python, calls repo functions.
3. **`db/`** contains ALL SQLite access — no SQL anywhere else.
4. **`core/state.py`** is the single source of truth for session_state keys.
5. **`components/`** wraps HTML/JS injection — one place for each concern.

## Stability Features (Phases 2–5)

- **Phase 2 — State Machine**: Ticketing uses step enums (`SELECT_ITEM` → `GROSS_INPUT` → `TARE_INPUT` → `CONFIRM` → `DONE`) with `transition_lock` to prevent race conditions.
- **Phase 3 — DB Transactions**: `get_connection()` context manager with auto-commit/rollback. `finalize_ticket()` is fully atomic.
- **Phase 4 — JS Debounce**: Keypad clicks are debounced (~150 ms). Enter key freezes input during transition
- **Phase 5 — Navigation**: Page switches use a sentinel value (`__switching__`) to force Streamlit to detect changes.

## Testing

See `tests_manual.md` for the manual testing checklist.
