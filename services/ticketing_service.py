"""
Business logic for the ticketing workflow.
No Streamlit widgets here — only st.session_state reads/writes and pure computation.
"""

import re
import html as html_module
from datetime import datetime

import streamlit as st
import pandas as pd

from core.config import RECEIPT_HEADER_LINES, RECEIPT_WIDTH, LEGAL_TEXT
from core.utils import calc_line, recompute_receipt_df, rpad, rjust, sanitize_style_block
from core.state import (
    record_action, bump_receipt_ver, STEP_SELECT_ITEM,
)
from db.connection import qdf, qone
from db.repo_ticketing import get_receipt, get_receipt_lines


# ---------------------------------------------------------------------------
# Add a line to the in-memory receipt DataFrame
# ---------------------------------------------------------------------------

def add_line_to_receipt(override_gross=None, override_tare=None,
                        override_unit_price=None):
    if not st.session_state.picked_material_name:
        return

    unit_price = (override_unit_price if override_unit_price is not None
                  else st.session_state.unit_price_input)
    gross = (override_gross if override_gross is not None
             else st.session_state.gross_input)
    tare = (override_tare if override_tare is not None
            else st.session_state.tare_input)

    net, total = calc_line(unit_price, gross, tare)
    new_row = {
        "Del": False,
        "material": st.session_state.picked_material_name,
        "unit_price": float(unit_price or 0),
        "gross": float(gross or 0),
        "tare": float(tare or 0),
        "net": float(net),
        "total": float(round(total, 2)),
    }
    df = st.session_state.receipt_df
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    st.session_state.receipt_df = recompute_receipt_df(df)

    st.session_state._reset_line_fields = True
    st.session_state.focus_request = "gross"

    # Bug 3 fix: bump version so data_editor key changes → forces fresh render
    bump_receipt_ver()

    # Phase 2: reset state machine
    st.session_state.active_step = STEP_SELECT_ITEM
    record_action()


# ---------------------------------------------------------------------------
# Receipt text / HTML formatters
# ---------------------------------------------------------------------------

def generate_print_receipt(receipt_id: int):
    """Build ScrapGoGo-format receipt dict {text, html} from DB data."""
    row = get_receipt(receipt_id)
    if not row:
        return {"text": "", "html": ""}
    lines_df = get_receipt_lines(receipt_id)

    rid = row["id"]
    issue_time_raw = row["issue_time"] or ""
    try:
        dt = datetime.strptime(issue_time_raw, "%Y-%m-%d %H:%M:%S")
        issue_time = dt.strftime("%m/%d/%Y %H:%M")
    except Exception:
        issue_time = issue_time_raw
    operator_name = (row["issued_by"] or "").strip()
    client_name = (row["client_name"] or "").strip() or "—"
    subtotal = float(row["subtotal"] or 0)
    rounding = float(row["rounding_amount"] or 0)
    balance = round(subtotal + rounding, 2)

    w = RECEIPT_WIDTH
    hline = "—" * (w // 2) if w % 2 == 0 else "—" * (w // 2) + "—"

    out = []
    for line in RECEIPT_HEADER_LINES:
        out.append(line.center(w))
    out.append(hline)

    def kv(lbl, val):
        v = str(val)
        return lbl + " " * (w - len(lbl) - len(v)) + v

    out.append(kv("Ticket Number : ", rid))
    out.append(kv("Start Date : ", issue_time))
    out.append(kv("End Date : ", issue_time))
    out.append(kv("By : ", operator_name))
    out.append(kv("Hold Until : ", ""))
    out.append(hline)

    col_g, col_t, col_n, col_p, col_tot = 6, 6, 6, 12, 10
    out.append(
        rpad("GROSS", col_g) + rpad("TARE", col_t) + rpad("NET", col_n)
        + rpad("PRICE", col_p) + rpad("TOTAL", col_tot)
    )
    out.append(hline)

    sum_gross = sum_tare = sum_net = sum_total = 0.0
    for _, r in lines_df.iterrows():
        mat = (r["material_name"] or "").strip()
        g = float(r["gross"] or 0)
        t = float(r["tare"] or 0)
        n = float(r["net"] or 0)
        p = float(r["unit_price"] or 0)
        tot = float(r["total"] or 0)
        sum_gross += g; sum_tare += t; sum_net += n; sum_total += tot
        out.append(mat[:w])
        price_str = f"${p:.3f}/Lb"
        tot_str = f"${tot:.2f}"
        out.append(
            rjust(str(int(g)), col_g) + rjust(str(int(t)), col_t)
            + rjust(str(int(n)), col_n) + rjust(price_str, col_p)
            + rjust(tot_str, col_tot)
        )

    out.append(hline)
    out.append(
        rjust(str(int(sum_gross)), col_g) + rjust(str(int(sum_tare)), col_t)
        + rjust(str(int(sum_net)), col_n) + rpad("", col_p)
        + rjust(f"${sum_total:,.2f}", col_tot)
    )
    out.append(hline)

    out.append(kv("Total Amount : ", f"{subtotal:,.2f}"))
    out.append(kv("Rounding Amount : ", f"{rounding:,.2f}"))
    out.append(kv("Adjustment Amount : ", "0.00"))
    out.append(kv("Paid Amount : ", "0.00"))
    out.append(kv("Balance Amount : ", f"{balance:,.2f}"))
    out.append(hline)
    out.append(kv("Name : ", client_name))
    out.append(kv("DL # : ", ""))
    out.append(hline)
    out.append(LEGAL_TEXT)
    out.append("YGMETAL")
    out.append(kv("Print Name : ", client_name))
    out.append(kv("Sign : ", ""))
    out.append(hline)
    text = "\n".join(out)

    # --- HTML version ---
    hl = []
    hl.append("<div class='receipt-print' style='font-family:monospace;font-size:12px;"
              "line-height:1.4;max-width:360px;margin:0 auto;padding:12px;white-space:pre-wrap;'>")
    hl.append("<div style='text-align:center;font-weight:bold;'>YG METAL</div>")
    hl.append("<div style='text-align:center;'>RC 4449276</div>")
    hl.append("<div style='text-align:center;'>test@ygmetal.com</div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Ticket Number :</span><span>{rid}</span></div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Start Date :</span><span>{issue_time}</span></div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>End Date :</span><span>{issue_time}</span></div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>By :</span><span>{operator_name}</span></div>")
    hl.append("<div style='display:flex;justify-content:space-between;'><span>Hold Until :</span><span></span></div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append("<div style='font-weight:bold;display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;gap:2px;'>")
    hl.append("<span>GROSS</span><span>TARE</span><span>NET</span><span>PRICE</span><span>TOTAL</span>")
    hl.append("</div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    for _, r in lines_df.iterrows():
        mat = (r["material_name"] or "").strip()
        g = int(r["gross"] or 0)
        t = int(r["tare"] or 0)
        n = int(r["net"] or 0)
        p = float(r["unit_price"] or 0)
        tot = float(r["total"] or 0)
        hl.append(f"<div style='text-decoration:underline;'>{mat}</div>")
        hl.append(
            f"<div style='display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;"
            f"gap:2px;text-align:right;'><span>{g}</span><span>{t}</span>"
            f"<span>{n}</span><span>${p:.3f}/Lb</span><span>${tot:.2f}</span></div>"
        )
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append(f"<div style='font-weight:bold;display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;gap:2px;text-align:right;'>")
    hl.append(f"<span>{int(sum_gross)}</span><span>{int(sum_tare)}</span><span>{int(sum_net)}</span><span></span><span>${sum_total:,.2f}</span>")
    hl.append("</div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Total Amount :</span><span>{subtotal:,.2f}</span></div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Rounding Amount :</span><span>{rounding:,.2f}</span></div>")
    hl.append("<div style='display:flex;justify-content:space-between;'><span>Adjustment Amount :</span><span>0.00</span></div>")
    hl.append("<div style='display:flex;justify-content:space-between;'><span>Paid Amount :</span><span>0.00</span></div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Balance Amount :</span><span>{balance:,.2f}</span></div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Name :</span><span>{client_name}</span></div>")
    hl.append("<div style='display:flex;justify-content:space-between;'><span>DL # :</span><span></span></div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append(f"<div>{LEGAL_TEXT}</div>")
    hl.append("<div>YGMETAL</div>")
    hl.append(f"<div style='display:flex;justify-content:space-between;'><span>Print Name :</span><span>{client_name}</span></div>")
    hl.append("<div style='display:flex;justify-content:space-between;'><span>Sign :</span><span></span></div>")
    hl.append("<hr style='border:none;border-top:1px solid #000;'/>")
    hl.append("</div>")
    html_str = "\n".join(hl)
    return {"text": text, "html": html_str}


def generate_print_html(receipt_id: int) -> str:
    result = generate_print_receipt(receipt_id)
    body_html = result["html"] if result["html"] else "<p>No receipt data.</p>"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        "html,body{background:#fff !important;color:#000 !important;"
        "font-family:monospace;font-size:12px;line-height:1.4;margin:12px;padding:20px;}"
        "*{color:#000 !important;background-color:transparent !important;} "
        "body *{background:transparent !important;} body{background:#fff !important;}"
        "</style>"
        "</head><body>" + body_html + "</body></html>"
    )


def build_receipt_html_for_print(
    company_name, ticket_number, email, issue_time, cashier, client_name,
    lines_df, total_amount, rounding_amount=0.0,
    adjustment_amount=0.0, paid_amount=0.0, balance_amount=0.0,
):
    """Full HTML document in ScrapGoGo receipt style."""
    items_html = ""
    sum_gross = sum_tare = sum_net = sum_total = 0.0
    for r in lines_df.itertuples(index=False):
        g = float(r.gross); t = float(r.tare); n = float(r.net)
        p = float(r.unit_price); tot = float(r.total)
        sum_gross += g; sum_tare += t; sum_net += n; sum_total += tot
        items_html += f"""
          <tr><td colspan="5" style="text-decoration:underline; font-weight:700; padding-top:4px;">{html_module.escape(str(r.material))}</td></tr>
          <tr>
            <td style="text-align:right;">{g:.0f}</td>
            <td style="text-align:right;">{t:.0f}</td>
            <td style="text-align:right;">{n:.0f}</td>
            <td style="text-align:right;">{p:.3f}/Lb</td>
            <td style="text-align:right;">{tot:.2f}</td>
          </tr>"""

    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Receipt</title>
  <style>
    @page {{ size: auto; margin: 10mm; }}
    @media print {{ body {{ margin: 0; padding: 0; background: #fff; }} }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #000; margin: 0; padding: 0; background: #fff;
    }}
    .ticket {{ width: 280px; margin: 0 auto; font-size: 12px; line-height: 1.45; }}
    .center {{ text-align: center; }}
    .hr {{ border-top: 1px solid #000; margin: 6px 0; }}
    .kv {{ display: flex; justify-content: space-between; }}
    .kv b {{ white-space: nowrap; }}
    .items-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .items-table td, .items-table th {{ border: none; padding: 1px 2px; }}
    .items-table th {{ text-align: right; font-weight: 700; text-decoration: underline; }}
    .items-table th:first-child {{ text-align: right; }}
    .summary-row td {{ font-weight: 700; padding-top: 3px; }}
  </style>
</head>
<body>
  <div class="ticket">
    <div class="center" style="font-weight:900; font-size:16px;">{html_module.escape(company_name)}</div>
    <div class="center" style="font-weight:800;">RC {html_module.escape(ticket_number)}</div>
    <div class="center">{html_module.escape(email)}</div>
    <div class="hr"></div>
    <div class="kv"><b>Ticket Number :-</b><span>{html_module.escape(ticket_number)}</span></div>
    <div class="kv"><b>Start Date :-</b><span>{html_module.escape(issue_time)}</span></div>
    <div class="kv"><b>End Date :-</b><span></span></div>
    <div class="kv"><b>By :-</b><span>{html_module.escape(cashier)}</span></div>
    <div class="kv"><b>Hold Until :-</b><span></span></div>
    <div class="hr"></div>
    <table class="items-table">
      <tr>
        <th style="text-align:right;">GROSS</th><th style="text-align:right;">TARE</th>
        <th style="text-align:right;">NET</th><th style="text-align:right;">PRICE</th>
        <th style="text-align:right;">TOTAL</th>
      </tr>
      {items_html}
    </table>
    <div class="hr"></div>
    <table class="items-table">
      <tr class="summary-row">
        <td style="text-align:right;">{sum_gross:.0f}</td>
        <td style="text-align:right;">{sum_tare:.0f}</td>
        <td style="text-align:right;">{sum_net:.0f}</td>
        <td></td>
        <td style="text-align:right;">{sum_total:,.2f}</td>
      </tr>
    </table>
    <div class="hr"></div>
    <div class="kv"><b>Total Amount :-</b><span>{total_amount:,.2f}</span></div>
    <div class="kv"><b>Rounding Amount :-</b><span>{rounding_amount:,.2f}</span></div>
    <div class="kv"><b>Adjustment Amount:-</b><span>{adjustment_amount:,.2f}</span></div>
    <div class="kv"><b>Paid Amount :-</b><span>{paid_amount:,.2f}</span></div>
    <div class="kv"><b>Balance Amount :-</b><span style="font-weight:800;">{balance_amount:,.2f}</span></div>
    <div class="hr"></div>
    <div class="kv"><b>Name :-</b><span>{html_module.escape(client_name)}</span></div>
    <div class="kv"><b>DL # :-</b><span></span></div>
    <div class="hr"></div>
    <div style="font-size:11px; line-height:1.4;">
      I, the seller, testifies that these items are not stolen, and I
      have full ownership, and I convey the ownership of, and interest in
      these items in this sale to YG Eco Metal Inc.
    </div>
    <div style="margin-top:6px; font-weight:700;">{html_module.escape(company_name)}</div>
    <div class="kv" style="margin-top:6px;"><b>Print Name :-</b><span>{html_module.escape(client_name)}</span></div>
    <div class="kv"><b>Sign :-</b><span></span></div>
    <div style="height:30px;"></div>
    <div class="hr"></div>
    <div class="center" style="font-size:11px; margin-top:4px;">www.ygMetals.com</div>
    <div class="center" style="font-size:10px; font-style:italic; margin-top:4px;">
      Powered by BuyScrapApp.com software for<br/>recycling companies
    </div>
  </div>
</body>
</html>"""
    match = re.search(r"<style>(.*?)</style>", html_doc, re.DOTALL)
    if match:
        clean_style = sanitize_style_block(match.group(1))
        html_doc = html_doc[:match.start(1)] + clean_style + html_doc[match.end(1):]
    return html_doc


def wrap_receipt_for_preview(receipt_html: str, scrollable: bool = False) -> str:
    close_scroll = "</div>" if scrollable else ""
    buttons = f"""
    {close_scroll}
    <div class="print-hide" style="margin-top:24px;text-align:center;padding:12px;">
      <button type="button" onclick="window.print();" style="padding:12px 28px;font-size:16px;cursor:pointer;font-weight:bold;">Print</button>
      <span style="display:inline-block;width:16px;"></span>
      <button type="button" onclick="window.close();" style="padding:12px 28px;font-size:16px;cursor:pointer;">Close</button>
    </div>
    """
    print_style = """
    <style>@media print { .print-hide { display: none !important; } }</style>
    """
    idx = receipt_html.rfind("</body>")
    if idx >= 0:
        return receipt_html[:idx] + buttons + print_style + "\n</body>" + receipt_html[idx + 7:]
    return receipt_html + buttons


def get_receipt_preview_html(rid: int) -> str:
    """Generate full receipt HTML for a real-URL preview page."""
    row = qone("SELECT * FROM receipts WHERE id = ?", (rid,))
    if not row:
        return ""
    lines_df = qdf(
        "SELECT * FROM receipt_lines WHERE receipt_id = ? ORDER BY id", (rid,))
    lines_df = lines_df.rename(columns={"material_name": "material"})
    issue_time = row["issue_time"] or ""
    try:
        dt = datetime.strptime(issue_time, "%Y-%m-%d %H:%M:%S")
        issue_time_fmt = dt.strftime("%m/%d/%Y %H:%M")
    except Exception:
        issue_time_fmt = issue_time
    subtotal = float(row["subtotal"] or 0)
    rounding = float(row["rounding_amount"] or 0)
    balance = round(subtotal + rounding, 2)
    html_body = build_receipt_html_for_print(
        company_name="YGMETAL",
        ticket_number=str(row["withdraw_code"] or ""),
        email="test@ygmetal.com",
        issue_time=issue_time_fmt,
        cashier=(row["issued_by"] or ""),
        client_name=(row["client_name"] or ""),
        lines_df=lines_df,
        total_amount=subtotal,
        rounding_amount=rounding,
        adjustment_amount=0.0,
        paid_amount=0.0,
        balance_amount=balance,
    )
    html_body = html_body.replace(
        "<body>",
        '<body><div class="receipt-scroll" style="max-height:85vh;overflow-y:auto;">',
        1,
    )
    return wrap_receipt_for_preview(html_body, scrollable=True)
