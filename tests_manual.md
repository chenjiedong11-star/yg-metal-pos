# Manual Testing Checklist

Run through every item below after each refactoring change.
Mark ✅ when confirmed working, ❌ if broken (with notes).

---

## 1. Ticketing — Fast Input Stability

| # | Test | Expected | Status |
|---|------|----------|--------|
| 1.1 | Select material → type Gross (e.g. 32) → press Enter → type Tare (e.g. 5) → press Enter | Gross shows 32, Tare shows 5, Confirm adds line with net=27. No digit duplication (32 never becomes 322). | |
| 1.2 | Repeat 1.1 fifty times as fast as possible | Every line has correct gross/tare. No digits lost, no duplicates. | |
| 1.3 | Select material → type Gross → immediately press Enter and start typing Tare digits | Tare field receives all typed digits without losing any. | |
| 1.4 | Press Confirm before entering Tare | Line added with tare=0. No crash, no premature second confirm. | |
| 1.5 | Use on-screen keypad instead of keyboard for 1.1 | Same result — digits appear one at a time, no duplicates. | |
| 1.6 | Click Clear mid-entry | Fields reset, no stale data in next entry. | |

## 2. Receipt / Print

| # | Test | Expected | Status |
|---|------|----------|--------|
| 2.1 | Add 3 items → Print/Save Receipt | Receipt saved to DB, print popup opens with correct data. | |
| 2.2 | Verify receipt data in DB after 2.1 | `receipts` and `receipt_lines` rows match displayed values. | |
| 2.3 | Open ticket detail → click Printout | Print popup shows correct receipt. | |

## 3. Navigation / Page Switching

| # | Test | Expected | Status |
|---|------|----------|--------|
| 3.1 | Click 管理 tab → click 开票 tab → click 管理 tab | Each switch renders immediately, no blank page. | |
| 3.2 | In 管理, click 月票据汇总 → click 票据明细 → click 月票据汇总 | Page content switches every time, no "stuck" page. | |
| 3.3 | Click same tab/menu item twice | Page still displays correctly (no need for browser refresh). | |

## 4. Report / Export

| # | Test | Expected | Status |
|---|------|----------|--------|
| 4.1 | 月票据汇总 → 导出数据到 excel | XLSX downloads with correct summary data. | |
| 4.2 | 月票据汇总 → 刷新数据 | Table refreshes, shows latest data. | |
| 4.3 | 票据明细 → click 📋 report button | Report popup opens with correct ticket list. | |

## 5. Client Management

| # | Test | Expected | Status |
|---|------|----------|--------|
| 5.1 | In Receiving Area → click Add → create client | Client appears in dropdown. | |
| 5.2 | Search client by code / name / phone | Dropdown filters correctly. | |

## 6. Data Integrity

| # | Test | Expected | Status |
|---|------|----------|--------|
| 6.1 | Save receipt while DB is busy (simulate with concurrent access) | Transaction completes or rolls back cleanly (no partial writes). | |
| 6.2 | Void a ticket | `voided=1` set, ticket no longer in active queries. | |
| 6.3 | Edit receipt lines in detail view → Confirm Change | Lines updated, subtotal recalculated correctly. | |
