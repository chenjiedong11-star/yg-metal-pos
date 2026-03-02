"""
Report & summary queries (read-only).
"""

import time
import base64
import streamlit as st
import pandas as pd

from db.connection import qdf


@st.cache_data(ttl=60)
def get_monthly_invoice_summary(_start_date=None, _end_date=None, _status=None):
    df = qdf("""
        SELECT substr(issue_time,1,7) AS yyyy_mm,
               COUNT(*) AS cnt,
               COALESCE(SUM(rounding_amount),0) AS total
        FROM receipts
        WHERE voided = 0
        GROUP BY yyyy_mm
        ORDER BY yyyy_mm DESC
    """)
    if df.empty:
        return pd.DataFrame({"开票时间": ["合计"], "开票数量": [0], "合计金额": [0.0]})

    def fmt_mm_yyyy(s):
        if not s or len(s) < 7:
            return s
        y, m = s[:4], s[5:7]
        return f"{m}/{y}"

    df["开票时间"] = df["yyyy_mm"].apply(fmt_mm_yyyy)
    df["开票数量"] = df["cnt"].astype(int)
    df["合计金额"] = df["total"].round(2)
    out = df[["开票时间", "开票数量", "合计金额"]].copy()
    total_row = pd.DataFrame({
        "开票时间": ["合计"],
        "开票数量": [out["开票数量"].sum()],
        "合计金额": [round(out["合计金额"].sum(), 2)],
    })
    return pd.concat([total_row, out], ignore_index=True)


def get_daily_summary_df(start_date=None, end_date=None,
                         method_filter=None, void_filter=None,
                         withdrawn_filter=None):
    """Daily summary with optional filters matching ScrapGoGo search dialog."""
    where = []
    params = []

    if start_date:
        where.append("substr(issue_time,1,10) >= ?")
        params.append(start_date)
    if end_date:
        where.append("substr(issue_time,1,10) <= ?")
        params.append(end_date)
    if method_filter and method_filter != "All":
        where.append("ticketing_method = ?")
        params.append(method_filter)
    if void_filter == "Not Voided":
        where.append("voided = 0")
    elif void_filter == "Voided":
        where.append("voided = 1")
    if withdrawn_filter == "Undrawn":
        where.append("withdrawn = 0")
    elif withdrawn_filter == "Withdrawn":
        where.append("withdrawn = 1")

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    return qdf(f"""
        SELECT substr(issue_time,1,10) AS issue_date,
               COUNT(*) AS invoiced_quantity,
               COALESCE(SUM(subtotal),0) AS subtotal,
               COALESCE(SUM(rounding_amount),0) AS rounding_amount
        FROM receipts r
        {where_sql}
        GROUP BY issue_date ORDER BY issue_date DESC LIMIT 1000
    """, tuple(params))


def get_monthly_summary_df():
    return qdf("""
        SELECT substr(issue_time,1,7) AS issue_month,
               SUM((SELECT COALESCE(SUM(net),0) FROM receipt_lines rl
                    WHERE rl.receipt_id=r.id)) AS invoiced_quantity,
               SUM(subtotal) AS subtotal,
               SUM(rounding_amount) AS rounding_amount
        FROM receipts r WHERE voided=0
        GROUP BY issue_month ORDER BY issue_month DESC LIMIT 1000
    """)


def get_annual_summary_df():
    return qdf("""
        SELECT substr(issue_time,1,4) AS issue_year,
               SUM((SELECT COALESCE(SUM(net),0) FROM receipt_lines rl
                    WHERE rl.receipt_id=r.id)) AS invoiced_quantity,
               SUM(subtotal) AS subtotal,
               SUM(rounding_amount) AS rounding_amount
        FROM receipts r WHERE voided=0
        GROUP BY issue_year ORDER BY issue_year DESC LIMIT 100
    """)


def build_daily_report_html(from_str, to_str, rows):
    """Printable HTML for the Daily Ticket Report popup."""
    total_balance = sum(float(r["rounding_amount"] or 0) for r in rows)
    total_adj = 0.0
    total_paid = 0.0
    total_total = total_balance

    lines_html = ""
    for r in rows:
        rid = r["id"]
        status = "VOIDED" if r["voided"] else "OPEN"
        issue = (r["issue_time"] or "")[:10]
        user = r["issued_by"] or ""
        customer = r["client_name"] or ""
        bal = float(r["rounding_amount"] or 0)
        lines_html += f"""
        <tr>
          <td rowspan="2" style="vertical-align:top;">{rid}</td>
          <td rowspan="2" style="vertical-align:top;">{status}</td>
          <td rowspan="2" style="vertical-align:top;">{issue} -<br>01/01/0001</td>
          <td rowspan="2" style="vertical-align:top;">{user}</td>
          <td rowspan="2" style="vertical-align:top;">{customer}</td>
          <td></td><td></td><td></td><td></td>
        </tr>
        <tr>
          <td style="text-align:right;">{bal:,.2f}</td>
          <td style="text-align:right;">0.00</td>
          <td style="text-align:right;">0.00</td>
          <td style="text-align:right;">{bal:,.2f}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Daily Ticket Report</title>
<style>
@media print {{ @page {{ margin: 12mm; }} body {{ margin: 0; }} .no-print {{ display:none!important; }} }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 11px; color: #333; padding: 20px; }}
h2 {{ text-align:center; margin: 4px 0; font-size: 16px; }}
.meta {{ display:flex; justify-content:space-between; border-bottom:2px solid #333; padding:4px 0; margin-bottom:8px; font-size:11px; }}
table {{ width:100%; border-collapse:collapse; font-size:11px; }}
th, td {{ padding: 3px 6px; text-align:left; }}
th {{ border-bottom: 1px solid #999; font-weight:600; }}
tr.total-row td {{ border-top:3px double #333; font-weight:700; }}
.page-info {{ text-align:right; font-size:10px; margin-bottom:2px; }}
.btn-bar {{ text-align:center; margin:16px 0; }}
.btn-bar button {{ padding:8px 28px; font-size:13px; margin:0 8px; cursor:pointer; border:1px solid #999; border-radius:4px; }}
.btn-bar button.primary {{ background:#2c7be5; color:#fff; border-color:#2c7be5; }}
</style></head><body>
<div class="page-info">1 of 1</div>
<h2>Daily Ticket Report</h2>
<div class="meta"><span><b>All</b></span><span>{from_str}</span><span>{to_str}</span></div>
<table>
<thead><tr>
  <th>Ticket</th><th>Status</th><th>Start - Finish</th><th>User</th><th>Customer</th>
  <th style="text-align:right;">Balance<br>Amount</th>
  <th style="text-align:right;">Adjustment<br>Amount</th>
  <th style="text-align:right;">Paid Amount</th>
  <th style="text-align:right;">Total<br>Amount</th>
</tr></thead>
<tbody>
{lines_html}
<tr class="total-row">
  <td colspan="5" style="text-align:right;"><b>Total :-</b></td>
  <td style="text-align:right;">{total_balance:,.2f}</td>
  <td style="text-align:right;">{total_adj:,.2f}</td>
  <td style="text-align:right;">{total_paid:,.2f}</td>
  <td style="text-align:right;">{total_total:,.2f}</td>
</tr>
</tbody></table>
<div class="btn-bar no-print">
  <button onclick="window.print()" class="primary">Print</button>
  <button onclick="window.close()">Close</button>
</div>
</body></html>"""
