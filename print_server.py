"""
独立打印服务：真实 URL 返回可打印收据 HTML（ScrapGoGo 风格）。
- 浏览器新窗口打开 /print/receipt/<receipt_id>，加载后自动 window.focus(); window.print(); 不依赖 iframe/data URL。
- 测试入口：GET /print/receipt/test 返回样例收据，用于验证打印链路。

启动：python print_server.py   （默认端口 8050，PRINT_PORT=8050）
      Streamlit 端需设置 PRINT_SERVER_URL=http://localhost:8050（或同机 IP）以便保存后打开打印页。
"""
import os
import sqlite3
import html as html_module
from datetime import datetime
from flask import Flask, Response

app = Flask(__name__)

# 与 print_server.py 同目录的 DB，确保 Flask 能访问
DB_PATH = os.path.join(os.path.dirname(__file__), "scrap_pos.db")

# 端口：环境变量 PRINT_PORT，默认 8050
PORT = int(os.environ.get("PRINT_PORT", 8050))

# 热敏纸宽度：80mm 或 58mm
PAPER_WIDTH_MM = int(os.environ.get("PRINT_PAPER_MM", "80"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_receipt_html(
    company_name: str,
    ticket_number: str,
    email: str,
    issue_time: str,
    cashier: str,
    client_name: str,
    lines_rows: list,
    total_amount: float,
    rounding_amount: float,
    balance_amount: float,
    auto_print: bool = True,
) -> str:
    """生成 ScrapGoGo 风格收据 HTML，含 @page 80mm/58mm、@media print。"""
    rows_html = ""
    for r in lines_rows:
        material = r.get("material", r.get("material_name", ""))
        gross = float(r.get("gross", 0))
        tare = float(r.get("tare", 0))
        net = float(r.get("net", 0))
        unit_price = float(r.get("unit_price", 0))
        total = float(r.get("total", 0))
        rows_html += f"""
        <tr>
          <td style="padding:6px 0; font-weight:700;">{html_module.escape(str(material))}</td>
        </tr>
        <tr>
          <td>
            <table style="width:100%; border-collapse:collapse; font-size:12px;">
              <tr>
                <td>GROSS</td><td style="text-align:right;">{gross:.0f}</td>
                <td>TARE</td><td style="text-align:right;">{tare:.0f}</td>
              </tr>
              <tr>
                <td>NET</td><td style="text-align:right;">{net:.0f}</td>
                <td>PRICE</td><td style="text-align:right;">{unit_price:.3f}/Lb</td>
              </tr>
              <tr>
                <td colspan="3" style="font-weight:700;">TOTAL</td>
                <td style="text-align:right; font-weight:800;">{total:.2f}</td>
              </tr>
            </table>
            <div style="border-bottom:1px solid #000; margin:6px 0;"></div>
          </td>
        </tr>
        """

    # 热敏纸：@page 控制纸宽，@media print 隐藏屏幕上的按钮
    ticket_width = "280px" if PAPER_WIDTH_MM >= 80 else "210px"
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Receipt {html_module.escape(ticket_number)}</title>
  <style>
    @page {{
      size: {PAPER_WIDTH_MM}mm auto;
      margin: 5mm;
    }}
    @media print {{
      body {{ margin: 0; padding: 0; }}
      .no-print {{ display: none !important; }}
    }}
    @media screen {{
      body {{ background: #f0f0f0; padding: 16px; }}
    }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      color: #000;
      margin: 0;
    }}
    .ticket {{
      width: {ticket_width};
      margin: 0 auto;
      background: #fff;
      padding: 12px;
      box-sizing: border-box;
    }}
    .center {{ text-align: center; }}
    .hr {{ border-top: 1px solid #000; margin: 8px 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    .receipt-table-wrap table td {{ white-space: nowrap; }}
  </style>
</head>
<body>
  <div class="ticket">
    <div class="center" style="font-weight:900; font-size:18px;">{html_module.escape(company_name)}</div>
    <div class="center" style="font-weight:800;">RC {html_module.escape(ticket_number)}</div>
    <div class="center" style="font-size:12px;">{html_module.escape(email)}</div>

    <div class="hr"></div>

    <div style="font-size:12px; line-height:1.5;">
      <div><b>Ticket Number :</b> {html_module.escape(ticket_number)}</div>
      <div><b>Start Date :</b> {html_module.escape(issue_time)}</div>
      <div><b>By :</b> {html_module.escape(cashier)}</div>
      <div><b>Name :</b> {html_module.escape(client_name)}</div>
    </div>

    <div class="hr"></div>

    <div class="receipt-table-wrap">
    <table style="font-size:12px;">
      {rows_html}
    </table>
    </div>

    <div class="hr"></div>

    <div style="font-size:12px; line-height:1.6;">
      <div><b>Total Amount :</b> <span style="float:right;">{total_amount:.2f}</span></div>
      <div><b>Rounding Amount :</b> <span style="float:right;">{rounding_amount:.2f}</span></div>
      <div><b>Balance Amount :</b> <span style="float:right;">{balance_amount:.2f}</span></div>
    </div>

    <div class="hr"></div>

    <div style="font-size:11px; line-height:1.4;">
      I, the seller, testifies that these items are not stolen, and I have full ownership,
      and I convey the ownership of, and interest in this sale to {html_module.escape(company_name)}.
    </div>

    <div class="hr"></div>

    <div style="font-size:12px;">
      <div><b>Print Name :</b></div>
      <div style="height:26px;"></div>
      <div><b>Sign :</b></div>
      <div style="height:40px;"></div>
    </div>
  </div>

  <div class="no-print" style="margin-top:24px;text-align:center;padding:12px;">
    <button type="button" onclick="window.print();" style="padding:12px 28px;font-size:16px;cursor:pointer;font-weight:bold;">Print</button>
    <span style="display:inline-block;width:16px;"></span>
    <button type="button" onclick="window.close();" style="padding:12px 28px;font-size:16px;cursor:pointer;">Close</button>
  </div>

  <script>
    window.focus();
    """ + ("window.print();" if auto_print else "") + """
  </script>
</body>
</html>
"""
    return html_doc


def get_receipt_data(receipt_id: int):
    """从 DB 读取 receipt + receipt_lines，返回 (dict, list) 或 (None, None)。"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None, None
    cur.execute(
        "SELECT * FROM receipt_lines WHERE receipt_id = ? ORDER BY id",
        (receipt_id,),
    )
    lines = [dict(r) for r in cur.fetchall()]
    conn.close()
    return dict(row), lines


def _test_receipt_html() -> str:
    """测试入口用样例收据 HTML。"""
    now = datetime.now().strftime("%m/%d/%Y %H:%M")
    lines_rows = [
        {"material": "Test Material A", "unit_price": 0.5, "gross": 100, "tare": 10, "net": 90, "total": 45.0},
        {"material": "Test Material B", "unit_price": 0.3, "gross": 50, "tare": 5, "net": 45, "total": 13.5},
    ]
    subtotal = 58.5
    rounding = 0.5
    balance = 59.0
    return build_receipt_html(
        company_name="YGMETAL",
        ticket_number="TEST",
        email="test@ygmetal.com",
        issue_time=now,
        cashier="Test User",
        client_name="Test Client",
        lines_rows=lines_rows,
        total_amount=subtotal,
        rounding_amount=rounding,
        balance_amount=balance,
        auto_print=True,
    )


@app.route("/ping")
def ping():
    """简单测试：访问 http://localhost:8050/ping 返回 OK。"""
    return "OK"


@app.route("/print/receipt/<receipt_id>")
def receipt_print(receipt_id):
    """真实收据：/print/receipt/<id> 从 DB 读 receipt + lines；/print/receipt/test 返回样例收据。"""
    if receipt_id == "test":
        return Response(_test_receipt_html(), mimetype="text/html; charset=utf-8")

    try:
        rid = int(receipt_id)
    except ValueError:
        return "Invalid receipt id", 400

    row, lines = get_receipt_data(rid)
    if not row:
        return "Receipt not found", 404

    issue_time = row.get("issue_time") or ""
    try:
        dt = datetime.strptime(issue_time, "%Y-%m-%d %H:%M:%S")
        issue_time_fmt = dt.strftime("%m/%d/%Y %H:%M")
    except Exception:
        issue_time_fmt = issue_time

    subtotal = float(row.get("subtotal") or 0)
    rounding = float(row.get("rounding_amount") or 0)
    balance = round(subtotal + rounding, 2)

    # receipt_lines 字段为 material_name，统一成 material
    lines_rows = []
    for ln in lines:
        ln = dict(ln)
        ln["material"] = ln.get("material_name", ln.get("material", ""))
        lines_rows.append(ln)

    html = build_receipt_html(
        company_name="YGMETAL",
        ticket_number=str(row.get("withdraw_code") or ""),
        email="test@ygmetal.com",
        issue_time=issue_time_fmt,
        cashier=(row.get("issued_by") or ""),
        client_name=(row.get("client_name") or ""),
        lines_rows=lines_rows,
        total_amount=subtotal,
        rounding_amount=rounding,
        balance_amount=balance,
        auto_print=True,
    )
    return Response(html, mimetype="text/html; charset=utf-8")


if __name__ == "__main__":
    print("Print server starting...")
    print("DB path:", DB_PATH)
    print("Port:", PORT)
    print("  ping:    http://127.0.0.1:{}/ping".format(PORT))
    print("  receipt: http://127.0.0.1:{}/print/receipt/<id>".format(PORT))
    print("  test:    http://127.0.0.1:{}/print/receipt/test".format(PORT))
    app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,
        threaded=True,
    )
