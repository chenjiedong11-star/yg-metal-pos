import io
import time
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import random
import base64
import html
import json
import uuid
import streamlit.components.v1 as components

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="SCRAPGOGO Clone • YG Metals", layout="wide")
DB_PATH = "scrap_pos.db"

# -----------------------------
# Popup 打印：仅在新开小窗口内 print()，严禁对主页面 window.print()。
# 只打印 receipt HTML（小票），不包含 Streamlit UI；弹窗被拦时在注入区显示明确提示。
# -----------------------------
def render_and_print_receipt(receipt_html: str) -> None:
    """
    在按钮点击事件内通过 window.open 打开 1x1 小窗口，写入完整收据 HTML，
    在 popup 内调用 print()（双保险：onload 后 + setTimeout 600ms 再试一次），然后关闭 popup。
    若 window.open 返回 null，在注入的 iframe 内显示「请允许弹窗」提示（height=90 可见）。
    """
    js = f"""
    <script>
    (function() {{
      var html = {json.dumps(receipt_html)};
      var w = window.open("", "_blank", "width=1,height=1,left=0,top=0");
      if (!w) {{
        document.body.innerHTML = '<div style="font-family:sans-serif;color:#b00;padding:10px;font-size:14px;line-height:1.4;">请允许此网站弹窗后再打印。<br/>在地址栏右侧或弹窗图标处点击「允许」即可。</div>';
        document.body.style.background = '#fff';
        return;
      }}
      w.document.open();
      w.document.write(html);
      w.document.close();
      w.focus();
      function doPrint() {{
        try {{
          w.print();
          setTimeout(function() {{ try {{ w.close(); }} catch(e) {{}} }}, 500);
        }} catch(e) {{}}
      }}
      w.onload = doPrint;
      setTimeout(doPrint, 350);
      setTimeout(doPrint, 600);
    }})();
    </script>
    """
    components.html(js, height=90, scrolling=False)


# -----------------------------
# DB helpers
# -----------------------------
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def qdf(sql, params=()):
    conn = db()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df

def save_preview_html(html_content: str) -> str:
    """存 print preview HTML，返回 token。"""
    token = str(uuid.uuid4())
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO print_previews(token, html, created_at) VALUES(?,?,?)",
        (token, html_content, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return token

def get_preview_html(token: str):
    """按 token 取 print preview HTML。"""
    row = qone("SELECT html FROM print_previews WHERE token = ?", (token,))
    return row["html"] if row else None


# -----------------------------
# 票据汇总（月/日/年复用）
# -----------------------------
@st.cache_data(ttl=60)
def get_monthly_invoice_summary(_start_date=None, _end_date=None, _status=None):
    """按月聚合 receipts：开票时间(MM/YYYY)、开票数量、合计金额。仅统计 voided=0。返回带合计行的 DataFrame。"""
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
    # 格式化为 MM/YYYY
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

def qone(sql, params=()):
    conn = db()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row

def exec_sql(sql, params=()):
    conn = db()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        name TEXT,
        phone TEXT,
        email TEXT,
        id_number TEXT,
        deleted INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS operators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        deleted INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS material_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        sort_order INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER,
        item_code TEXT,
        name TEXT,
        unit TEXT DEFAULT 'LB',
        unit_price REAL DEFAULT 0,
        min_unit_price REAL DEFAULT 0,
        max_unit_price REAL DEFAULT 0,
        deleted INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(category_id) REFERENCES material_categories(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_time TEXT,
        issued_by TEXT,
        ticketing_method TEXT DEFAULT 'Print',
        withdraw_code TEXT,
        client_code TEXT,
        client_name TEXT,
        subtotal REAL DEFAULT 0,
        rounding_amount REAL DEFAULT 0,
        voided INTEGER DEFAULT 0,
        withdrawn INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS receipt_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER,
        material_name TEXT,
        unit_price REAL,
        gross REAL,
        tare REAL,
        net REAL,
        total REAL,
        FOREIGN KEY(receipt_id) REFERENCES receipts(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS print_previews (
        token TEXT PRIMARY KEY,
        html TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()

    # Seed defaults
    cur.execute("SELECT COUNT(*) c FROM operators")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO operators(email,name,created_at) VALUES(?,?,?)",
            ("admin@youli-trade.com", "Andy Chen", datetime.now().isoformat(timespec="seconds"))
        )

    cur.execute("SELECT COUNT(*) c FROM material_categories")
    if cur.fetchone()["c"] == 0:
        cats = [("Copper", 1), ("Alum", 2), ("Wire", 3), ("Others", 4), ("Metal", 5)]
        cur.executemany("INSERT INTO material_categories(name, sort_order) VALUES(?,?)", cats)

    cur.execute("SELECT COUNT(*) c FROM materials")
    if cur.fetchone()["c"] == 0:
        cur.execute("SELECT id,name FROM material_categories")
        cmap = {r["name"]: r["id"] for r in cur.fetchall()}
        seed = [
            (cmap["Copper"], "1001", "Bare Bright 光亮铜", "LB", 4.70, 2.70, 5.00),
            (cmap["Copper"], "1002", "Cu#1 一号铜", "LB", 4.45, 2.50, 4.60),
            (cmap["Copper"], "1003", "Cu#2 二号铜", "LB", 4.00, 2.20, 4.30),
            (cmap["Wire"],   "2001", "Romex 电线", "LB", 2.50, 1.50, 3.50),
            (cmap["Metal"],  "3001", "H/G 高铁", "LB", 0.18, 0.10, 0.30),
            (cmap["Alum"],   "4001", "Alum Clean 干净铝", "LB", 0.75, 0.40, 1.20),
            (cmap["Others"], "5001", "E-Motor 马达", "LB", 0.20, 0.10, 0.40),
        ]
        cur.executemany("""
            INSERT INTO materials(category_id,item_code,name,unit,unit_price,min_unit_price,max_unit_price,created_at)
            VALUES(?,?,?,?,?,?,?,?)
        """, [(a,b,c,d,e,f,g, datetime.now().isoformat(timespec="seconds")) for (a,b,c,d,e,f,g) in seed])

    cur.execute("SELECT COUNT(*) c FROM clients")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO clients(code,name,phone,created_at) VALUES(?,?,?,?)",
            ("000001", "Walk-in", "", datetime.now().isoformat(timespec="seconds"))
        )

    cur.execute("SELECT COUNT(*) c FROM settings")
    if cur.fetchone()["c"] == 0:
        cur.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                    ("unit_price_adjustment_permitted", "Yes"))

    conn.commit()
    conn.close()

def get_setting(key, default=""):
    r = qone("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default

def gen_code_6():
    for _ in range(200):
        code = f"{random.randint(0, 999999):06d}"
        if not qone("SELECT 1 FROM clients WHERE code=?", (code,)):
            return code
    mx = qone("SELECT MAX(CAST(code as INTEGER)) AS m FROM clients")
    m = int(mx["m"] or 0)
    return f"{(m+1)%1000000:06d}"

def gen_withdraw_code():
    return str(random.randint(100000, 999999))

# -----------------------------
# Session state
# -----------------------------
def ss_init():
    if "top_nav" not in st.session_state:
        st.session_state.top_nav = "开票"
    if "manage_page" not in st.session_state:
        st.session_state.manage_page = "月票据汇总信息查询"

    if "ticket_client_code" not in st.session_state:
        st.session_state.ticket_client_code = "000001"

    if "ticket_operator" not in st.session_state:
        op = qone("SELECT email FROM operators WHERE deleted=0 ORDER BY id LIMIT 1")
        st.session_state.ticket_operator = op["email"] if op else "admin@youli-trade.com"

    if "active_cat" not in st.session_state:
        st.session_state.active_cat = "Copper"

    if "picked_material_id" not in st.session_state:
        st.session_state.picked_material_id = None
    if "picked_material_name" not in st.session_state:
        st.session_state.picked_material_name = ""

    if "unit_price" not in st.session_state:
        st.session_state.unit_price = ""

    if "client_search" not in st.session_state:
        st.session_state.client_search = ""
    if "_show_add_client" not in st.session_state:
        st.session_state._show_add_client = False

    if "receipt_df" not in st.session_state:
        st.session_state.receipt_df = pd.DataFrame(columns=[
            "Del", "material", "unit_price", "gross", "tare", "net", "total"
        ])

    if "focus_request" not in st.session_state:
        st.session_state.focus_request = None
    if "_keypad_pending" not in st.session_state:
        st.session_state._keypad_pending = None

    if "key_target" not in st.session_state:
        st.session_state.key_target = "gross"

    # ✅ 关键：清零用 flag（避免 widget 已创建后再改 session_state[widget_key]）
    if "_reset_line_fields" not in st.session_state:
        st.session_state._reset_line_fields = False
    if "_form_reset_key" not in st.session_state:
        st.session_state._form_reset_key = 0
    if "_entered_tare_for_line" not in st.session_state:
        st.session_state._entered_tare_for_line = False

    # ✅ 给 widget key 一个初始值（避免第一次为空时奇怪）
    if "gross_input" not in st.session_state:
        st.session_state.gross_input = ""
    if "tare_input" not in st.session_state:
        st.session_state.tare_input = ""
    if "unit_price_input" not in st.session_state:
        st.session_state.unit_price_input = ""

# -----------------------------
# UI helpers
# -----------------------------
def css():
    st.markdown("""
    <style>
      /* 根字体：随浏览器缩放与视口自动调节（100% 继承浏览器，clamp 做视口适配） */
      html { font-size: 100%; }
      [data-testid="stAppViewContainer"],
      [data-testid="stAppViewContainer"] main {
        font-size: clamp(0.875rem, 1.5vw + 0.75rem, 1.25rem) !important;
      }
      div.block-container {
        padding-top: 1rem !important;
        max-width: 100% !important;
      }

      .topbar{
        height: 2.75rem;
        background:#2f2f2f;
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:space-between;
        padding:0 0.875rem;
        border-radius:0.375rem;
        margin-bottom:0.625rem;
        font-weight:800;
        font-size: 1em;
      }
      /* 去掉左中右三块区域的边框和背景，不再显示为长框 */
      .box{
        border: none !important;
        border-radius: 0;
        padding: 0.25rem 0;
        background: transparent !important;
        font-size: 1em;
      }
      .subtle{ color:#6b7280; font-size: 0.875em; }

      [data-testid="stDataFrame"] td,
      [data-testid="stDataFrame"] th {
        white-space: nowrap !important;
        font-size: inherit !important;
      }
      [data-testid="stDataFrame"] { font-size: 1em !important; }

      [data-testid="stVerticalBlock"] { gap: 0.35rem !important; }

      [data-testid="stTextInput"] input:placeholder-shown {
        background: transparent !important;
        border-color: transparent !important;
        box-shadow: none !important;
      }
      [data-testid="stTextInput"] > div {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
      }

      /* 按钮、输入框、标签等随根字体缩放 */
      [data-testid="stButton"] button,
      [data-testid="stTextInput"] input,
      [data-testid="stSelectbox"] div,
      label, p, .stMarkdown {
        font-size: inherit !important;
      }
      [data-testid="column"] { font-size: inherit !important; }

      /* 去掉椭圆形圆角框：按钮改为小圆角、扁平样式，与整体更协调 */
      [data-testid="stButton"] button {
        border-radius: 0.25rem !important;
        box-shadow: none !important;
      }

      /* Receiving Area 右侧区：Keypad 等按钮稍高，触屏好按 */
      [data-testid="stHorizontalBlock"] > div:nth-child(3) [data-testid="stButton"] button {
        min-height: 3.25rem !important;
        padding: 0.6rem 0.75rem !important;
      }
    </style>
    """, unsafe_allow_html=True)

def topbar(active):
    user = st.session_state.ticket_operator
    st.markdown(
        f"""
        <div class="topbar">
          <div>SCRAPGOGO • 开票端 • [Y&G METALS INC.]</div>
          <div>{active} &nbsp;&nbsp; {user}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def calc_line(unit_price, gross, tare):
    p = float(unit_price or 0)
    g = float(gross or 0)
    t = float(tare or 0)
    net = max(0.0, g - t)
    total = net * p
    return net, total

def recompute_receipt_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ["unit_price","gross","tare"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["net"] = (out["gross"] - out["tare"]).clip(lower=0.0)
    out["total"] = (out["net"] * out["unit_price"]).round(2)
    if "Del" in out.columns:
        out["Del"] = out["Del"].fillna(False).astype(bool)
    out["material"] = out["material"].fillna("").astype(str)
    return out

def current_subtotal():
    df = st.session_state.receipt_df
    if df.empty:
        return 0.0
    df = recompute_receipt_df(df)
    return float(df["total"].sum())

# -----------------------------
# ScrapGoGo receipt print format (text + HTML)
# -----------------------------
RECEIPT_HEADER_LINES = ["YG METAL", "RC 4449276", "test@ygmetal.com"]
RECEIPT_WIDTH = 48
LEGAL_TEXT = (
    "I, the seller, testifies that these items are not stolen, and I have full ownership, "
    "and I convey the ownership of, and interest in these items in this sale to YG Eco Metal Inc."
)

def _rpad(s, w):
    return str(s)[:w].ljust(w)

def _rjust(s, w):
    return str(s).rjust(w)

def generate_print_receipt(receipt_id: int):
    """
    Fetch receipt + receipt_lines, build ScrapGoGo-format receipt.
    Returns {"text": str, "html": str} for display/print and download.
    """
    row = qone("SELECT * FROM receipts WHERE id = ?", (receipt_id,))
    if not row:
        return {"text": "", "html": ""}
    lines_df = qdf("SELECT * FROM receipt_lines WHERE receipt_id = ? ORDER BY id", (receipt_id,))

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

    # SECTION 1 — HEADER
    for line in RECEIPT_HEADER_LINES:
        out.append(line.center(w))
    out.append(hline)

    # SECTION 2 — RECEIPT INFO (label left, value right; total width w)
    def kv(lbl, val):
        v = str(val)
        return lbl + " " * (w - len(lbl) - len(v)) + v
    out.append(kv("Ticket Number : ", rid))
    out.append(kv("Start Date : ", issue_time))
    out.append(kv("End Date : ", issue_time))
    out.append(kv("By : ", operator_name))
    out.append(kv("Hold Until : ", ""))
    out.append(hline)

    # SECTION 3 — ITEM TABLE
    col_g, col_t, col_n, col_p, col_tot = 6, 6, 6, 12, 10
    out.append(_rpad("GROSS", col_g) + _rpad("TARE", col_t) + _rpad("NET", col_n) + _rpad("PRICE", col_p) + _rpad("TOTAL", col_tot))
    out.append(hline)

    sum_gross = sum_tare = sum_net = sum_total = 0.0
    for _, r in lines_df.iterrows():
        mat = (r["material_name"] or "").strip()
        g, t, n = float(r["gross"] or 0), float(r["tare"] or 0), float(r["net"] or 0)
        p, tot = float(r["unit_price"] or 0), float(r["total"] or 0)
        sum_gross += g
        sum_tare += t
        sum_net += n
        sum_total += tot
        out.append(mat[:w])
        price_str = f"${p:.3f}/Lb"
        tot_str = f"${tot:.2f}"
        out.append(_rjust(str(int(g)), col_g) + _rjust(str(int(t)), col_t) + _rjust(str(int(n)), col_n) + _rjust(price_str, col_p) + _rjust(tot_str, col_tot))

    out.append(hline)
    out.append(_rjust(str(int(sum_gross)), col_g) + _rjust(str(int(sum_tare)), col_t) + _rjust(str(int(sum_net)), col_n) + _rpad("", col_p) + _rjust(f"${sum_total:,.2f}", col_tot))
    out.append(hline)

    # SECTION 4 — TOTAL SUMMARY
    out.append(kv("Total Amount : ", f"{subtotal:,.2f}"))
    out.append(kv("Rounding Amount : ", f"{rounding:,.2f}"))
    out.append(kv("Adjustment Amount : ", "0.00"))
    out.append(kv("Paid Amount : ", "0.00"))
    out.append(kv("Balance Amount : ", f"{balance:,.2f}"))
    out.append(hline)

    # SECTION 5 — CLIENT INFO
    out.append(kv("Name : ", client_name))
    out.append(kv("DL # : ", ""))
    out.append(hline)

    # SECTION 6 — LEGAL TEXT
    out.append(LEGAL_TEXT)
    out.append("YGMETAL")
    out.append(kv("Print Name : ", client_name))
    out.append(kv("Sign : ", ""))
    out.append(hline)

    text = "\n".join(out)

    # HTML version (monospace, fixed width, print-friendly)
    html_lines = []
    html_lines.append("<div class='receipt-print' style='font-family:monospace;font-size:12px;line-height:1.4;max-width:360px;margin:0 auto;padding:12px;white-space:pre-wrap;'>")
    html_lines.append("<div style='text-align:center;font-weight:bold;'>YG METAL</div>")
    html_lines.append("<div style='text-align:center;'>RC 4449276</div>")
    html_lines.append("<div style='text-align:center;'>test@ygmetal.com</div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Ticket Number :</span><span>{rid}</span></div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Start Date :</span><span>{issue_time}</span></div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>End Date :</span><span>{issue_time}</span></div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>By :</span><span>{operator_name}</span></div>")
    html_lines.append("<div style='display:flex;justify-content:space-between;'><span>Hold Until :</span><span></span></div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append("<div style='font-weight:bold;display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;gap:2px;'>")
    html_lines.append("<span>GROSS</span><span>TARE</span><span>NET</span><span>PRICE</span><span>TOTAL</span>")
    html_lines.append("</div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    for _, r in lines_df.iterrows():
        mat = (r["material_name"] or "").strip()
        g, t, n = int(r["gross"] or 0), int(r["tare"] or 0), int(r["net"] or 0)
        p, tot = float(r["unit_price"] or 0), float(r["total"] or 0)
        html_lines.append(f"<div style='text-decoration:underline;'>{mat}</div>")
        html_lines.append(f"<div style='display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;gap:2px;text-align:right;'><span>{g}</span><span>{t}</span><span>{n}</span><span>${p:.3f}/Lb</span><span>${tot:.2f}</span></div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append(f"<div style='font-weight:bold;display:grid;grid-template-columns:6ch 6ch 6ch 12ch 10ch;gap:2px;text-align:right;'>")
    html_lines.append(f"<span>{int(sum_gross)}</span><span>{int(sum_tare)}</span><span>{int(sum_net)}</span><span></span><span>${sum_total:,.2f}</span>")
    html_lines.append("</div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Total Amount :</span><span>{subtotal:,.2f}</span></div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Rounding Amount :</span><span>{rounding:,.2f}</span></div>")
    html_lines.append("<div style='display:flex;justify-content:space-between;'><span>Adjustment Amount :</span><span>0.00</span></div>")
    html_lines.append("<div style='display:flex;justify-content:space-between;'><span>Paid Amount :</span><span>0.00</span></div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Balance Amount :</span><span>{balance:,.2f}</span></div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Name :</span><span>{client_name}</span></div>")
    html_lines.append("<div style='display:flex;justify-content:space-between;'><span>DL # :</span><span></span></div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append(f"<div>{LEGAL_TEXT}</div>")
    html_lines.append("<div>YGMETAL</div>")
    html_lines.append(f"<div style='display:flex;justify-content:space-between;'><span>Print Name :</span><span>{client_name}</span></div>")
    html_lines.append("<div style='display:flex;justify-content:space-between;'><span>Sign :</span><span></span></div>")
    html_lines.append("<hr style='border:none;border-top:1px solid #000;'/>")
    html_lines.append("</div>")

    html = "\n".join(html_lines)
    return {"text": text, "html": html}

def generate_print_html(receipt_id: int) -> str:
    """
    Returns a full HTML document with receipt content (no script).
    Explicit white background and black text to avoid black screen in any context.
    """
    result = generate_print_receipt(receipt_id)
    body_html = result["html"] if result["html"] else "<p>No receipt data.</p>"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>"
        "html,body{background:#fff !important;color:#000 !important;font-family:monospace;font-size:12px;line-height:1.4;margin:12px;padding:20px;}"
        "*{color:#000 !important;background-color:transparent !important;} body *{background:transparent !important;} body{background:#fff !important;}"
        "</style>"
        "</head><body>" + body_html + "</body></html>"
    )

def build_receipt_html_for_print(
    company_name: str,
    ticket_number: str,
    email: str,
    issue_time: str,
    cashier: str,
    client_name: str,
    lines_df,
    total_amount: float,
    rounding_amount: float = 0.0,
    adjustment_amount: float = 0.0,
    paid_amount: float = 0.0,
    balance_amount: float = 0.0,
):
    """简易打印样式：窄票据 + 表格，可用于测试打印窗口是否正常弹出。"""
    rows_html = ""
    for r in lines_df.itertuples(index=False):
        rows_html += f"""
        <tr>
          <td style="padding:6px 0; font-weight:700;">{html.escape(str(r.material))}</td>
        </tr>
        <tr>
          <td>
            <table style="width:100%; border-collapse:collapse; font-size:12px;">
              <tr>
                <td>GROSS</td><td style="text-align:right;">{float(r.gross):.0f}</td>
                <td>TARE</td><td style="text-align:right;">{float(r.tare):.0f}</td>
              </tr>
              <tr>
                <td>NET</td><td style="text-align:right;">{float(r.net):.0f}</td>
                <td>PRICE</td><td style="text-align:right;">{float(r.unit_price):.3f}/Lb</td>
              </tr>
              <tr>
                <td colspan="3" style="font-weight:700;">TOTAL</td>
                <td style="text-align:right; font-weight:800;">{float(r.total):.2f}</td>
              </tr>
            </table>
            <div style="border-bottom:1px solid #000; margin:6px 0;"></div>
          </td>
        </tr>
        """

    html_doc = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <title>Receipt</title>
      <style>
        @page {{ size: auto; margin: 10mm; }}
        @media print {{ body {{ margin: 0; padding: 0; background: #fff; }} }}
        body {{
          font-family: Arial, Helvetica, sans-serif;
          color: #000;
          margin: 0;
          padding: 0;
          background: #fff;
        }}
        .ticket {{
          width: 280px;
          margin: 0 auto;
        }}
        .center {{ text-align: center; }}
        .hr {{ border-top: 1px solid #000; margin: 8px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #000; }}
        .receipt-table-wrap {{ overflow-x: auto; }}
        .receipt-table-wrap table td {{ white-space: nowrap; }}
        .amount-bold {{ font-weight: 800; }}
      </style>
    </head>
    <body>
      <div class="ticket">
        <div class="center" style="font-weight:900; font-size:18px;">{html.escape(company_name)}</div>
        <div class="center" style="font-weight:800;">RC {html.escape(ticket_number)}</div>
        <div class="center" style="font-size:12px;">{html.escape(email)}</div>

        <div class="hr"></div>

        <div style="font-size:12px; line-height:1.5;">
          <div><b>Ticket Number :</b> {html.escape(ticket_number)}</div>
          <div><b>Start Date :</b> {html.escape(issue_time)}</div>
          <div><b>By :</b> {html.escape(cashier)}</div>
          <div><b>Name :</b> {html.escape(client_name)}</div>
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
          <div><b>Adjustment Amount :</b> <span style="float:right;">{adjustment_amount:.2f}</span></div>
          <div><b>Paid Amount :</b> <span style="float:right;">{paid_amount:.2f}</span></div>
          <div><b>Balance Amount :</b> <span class="amount-bold" style="float:right;">{balance_amount:.2f}</span></div>
        </div>

        <div class="hr"></div>

        <div style="font-size:11px; line-height:1.4;">
          I, the seller, testifies that these items are not stolen, and I have full ownership,
          and I convey the ownership of, and interest in this sale to {html.escape(company_name)}.
        </div>

        <div class="hr"></div>

        <div style="font-size:12px;">
          <div><b>Print Name :</b></div>
          <div style="height:26px;"></div>
          <div><b>Sign :</b></div>
          <div style="height:40px;"></div>
        </div>
      </div>
    </body>
    </html>
    """
    return html_doc

def _inject_blob_preview_open(b64: str):
    """D: Blob URL fallback — 用 UTF-8 解码 base64 后建 Blob，window.open(blobUrl)。"""
    script = f"""<script>
(function() {{
  try {{
    var b64 = "{b64}";
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var html = new TextDecoder("utf-8").decode(bytes);
    var blob = new Blob([html], {{ type: "text/html;charset=utf-8" }});
    var url = URL.createObjectURL(blob);
    window.open(url, "_blank");
  }} catch(e) {{
    alert("Blob open failed: " + e.message);
  }}
}})();
</script>"""
    components.html(script, height=0)

def _run_print_test():
    """E: 最小可复现 — 固定简单 HTML（Hello + 当前时间 + Print 按钮），存 server 后打开 ?preview_token=xxx。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    minimal_html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Print Test</title></head><body>
<h1>Hello</h1>
<p>Time: {now}</p>
<button type="button" onclick="window.print();" style="padding:12px 24px;font-size:16px;cursor:pointer;">Print</button>
<button type="button" onclick="window.close();" style="padding:12px 24px;margin-left:8px;">Close</button>
</body></html>"""
    token = save_preview_html(minimal_html)
    script = f"""<script>
(function() {{
  var url = window.location.origin + window.location.pathname + "?preview_token=" + "{token}";
  var w = window.open(url, "_blank");
  alert(w ? "Print Test tab opened. Click Print there." : "Popup blocked.");
}})();
</script>"""
    components.html(script, height=0)

def wrap_receipt_for_preview(receipt_html: str, scrollable: bool = False) -> str:
    """
    在收据 HTML 末尾加入 Print / Close 按钮，供新窗口 Print Preview 使用。
    不自动调用 window.print()，由用户在预览页点击 Print 触发，保证稳定。
    @media print 隐藏按钮。
    scrollable=True 时在收据主体外加可滚动容器，避免明细多时只看到前几条。
    """
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
    """
    方案1：从 DB 按 receipt id 读取 receipts + receipt_lines，生成完整收据 HTML（真实 URL 预览页用）。
    包含商户信息、单号/时间、客户、明细表（不换行+横向滚动）、Subtotal/Rounding/Total、Withdraw Code、Print/Close。
    """
    row = qone("SELECT * FROM receipts WHERE id = ?", (rid,))
    if not row:
        return ""
    lines_df = qdf("SELECT * FROM receipt_lines WHERE receipt_id = ? ORDER BY id", (rid,))
    lines_df = lines_df.rename(columns={"material_name": "material"})
    issue_time = (row["issue_time"] or "")
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
    # 明细多时：收据主体放入可滚动区域，避免只看到前几条
    html_body = html_body.replace("<body>", "<body><div class=\"receipt-scroll\" style=\"max-height:85vh;overflow-y:auto;\">", 1)
    return wrap_receipt_for_preview(html_body, scrollable=True)

def open_print_preview_window(receipt_html: str):
    """
    稳定方案 C：preview_html 存 server 端，用 ?preview_token=xxx 真实 URL 打开，避免 data URL/编码/策略问题。
    带诊断 A：length、base64 长度、try/catch、alert(opened/blocked)；可选 Blob fallback D。
    """
    preview_html = wrap_receipt_for_preview(receipt_html)
    token = save_preview_html(preview_html)
    b64 = base64.b64encode(preview_html.encode("utf-8")).decode("ascii")

    # A: 诊断 — 存到 session 供页面显示
    st.session_state._print_diag = {
        "html_len": len(preview_html),
        "b64_len": len(b64),
        "first200": preview_html[:200],
    }
    st.session_state._pending_preview_token = token
    st.session_state._pending_preview_b64 = b64  # 备用 data URL 链接

    # C: 用真实 URL 打开（最稳）
    script = f"""<script>
(function() {{
  try {{
    var token = "{token}";
    var url = window.location.origin + window.location.pathname + "?preview_token=" + token;
    console.log("Print preview URL:", url);
    var w = window.open(url, "_blank");
    if (w) {{
      alert("Preview opened. In the new tab click Print to print.");
    }} else {{
      alert("Popup blocked. Use the link below to open Print Preview.");
    }}
  }} catch(e) {{
    console.error("Print preview error:", e);
    alert("Error: " + e.message);
  }}
}})();
</script>"""
    components.html(script, height=0)

def print_receipt_in_place(receipt_html: str):
    """
    在 Streamlit 原页面触发打印：创建隐藏 iframe -> 写入 receipt_html -> 触发 iframe.print()
    不使用 window.open，不在页面显示 preview。iframe 挂在 parent（Streamlit 宿主页）上。
    """
    safe_html_js = json.dumps(receipt_html)
    js = f"""
    <script>
    (function() {{
      try {{
        const parentDoc = window.parent.document;
        let iframe = parentDoc.getElementById("yg_print_iframe");
        if (!iframe) {{
          iframe = parentDoc.createElement("iframe");
          iframe.id = "yg_print_iframe";
          iframe.style.position = "fixed";
          iframe.style.right = "0";
          iframe.style.bottom = "0";
          iframe.style.width = "0";
          iframe.style.height = "0";
          iframe.style.border = "0";
          iframe.style.opacity = "0";
          iframe.style.pointerEvents = "none";
          parentDoc.body.appendChild(iframe);
        }}

        const doc = iframe.contentWindow.document;
        const htmlStr = {safe_html_js};

        doc.open();
        doc.write(htmlStr);
        doc.close();

        setTimeout(() => {{
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        }}, 120);
      }} catch(e) {{
        console.error("Print failed:", e);
        alert("Print failed: " + e);
      }}
    }})();
    </script>
    """
    components.html(js, height=0)

def _inject_print_via_hidden_iframe(receipt_html: str) -> str:
    """
    在当前页（components 所在的 iframe）内插入隐藏 iframe，把 receipt HTML 写入该 iframe，
    然后调用 iframe.contentWindow.print() 直接弹出系统打印窗口。不打开新窗口，页面不显示 preview。
    """
    b64 = base64.b64encode(receipt_html.encode("utf-8")).decode("ascii")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
(function() {{
  var html = atob("{b64}");
  var iframe = document.createElement("iframe");
  iframe.style.cssText = "position:absolute;width:0;height:0;border:none;left:-9999px;top:0;";
  document.body.appendChild(iframe);
  iframe.contentWindow.document.open();
  iframe.contentWindow.document.write(html);
  iframe.contentWindow.document.close();
  iframe.contentWindow.focus();
  setTimeout(function() {{
    iframe.contentWindow.print();
    setTimeout(function() {{ if (iframe.parentNode) iframe.parentNode.removeChild(iframe); }}, 1000);
  }}, 200);
}})();
</script>
</body></html>"""

def add_line_to_receipt(override_gross=None, override_tare=None, override_unit_price=None):
    if not st.session_state.picked_material_name:
        st.warning("Please pick a material.")
        return

    # ✅ 若传入 override 则用表单提交时的快照，避免 keypad+Enter 同时按导致被覆盖成 0
    unit_price = override_unit_price if override_unit_price is not None else st.session_state.unit_price_input
    gross = override_gross if override_gross is not None else st.session_state.gross_input
    tare = override_tare if override_tare is not None else st.session_state.tare_input

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

    # ✅ 用 flag：下一次 rerun（控件创建前）再清零
    st.session_state._reset_line_fields = True
    st.session_state.focus_request = "gross"

def focus_js(target: str, unique_id: int = 0):
    """选 item 后自动聚焦到 Gross 或 Tare；只抢焦一次，之后不抢，方便用户再点 Gross"""
    idx = 1 if target == "gross" else 2  # 0=Unit Price, 1=Gross, 2=Tare
    html = f"""
    <!-- focus_{unique_id} -->
    <script>
      (function(){{
        var didFocus = false;
        function findInput(doc) {{
          var m = doc.getElementById('scrap-gross-tare-marker');
          if (!m) return null;
          var form = m.closest('form') || m.parentElement;
          while (form && form !== doc.body) {{
            var inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"])');
            if (inputs.length >= 3 && {idx} < inputs.length) return inputs[{idx}];
            form = form.parentElement;
          }}
          return null;
        }}
        function tryFocus() {{
          if (didFocus) return true;
          var doc = window.parent.document;
          if (!doc.getElementById('scrap-gross-tare-marker')) doc = window.top.document;
          var el = findInput(doc);
          if (el) {{ el.focus(); didFocus = true; return true; }}
          return false;
        }}
        var n = 0;
        function startPoll() {{
          var t = setInterval(function() {{
            n++;
            if (tryFocus() || n > 100) clearInterval(t);
          }}, 80);
        }}
        setTimeout(startPoll, 50);
        setTimeout(startPoll, 300);
        setTimeout(startPoll, 800);
      }})();
    </script>
    """
    components.html(html, height=0)

def enter_workflow_js():
    """Gross Enter → Tare；Tare Enter → Confirm。Enter 在 Gross 时点 →Tare 更新 key_target，再 focus Tare"""
    html = """
    <script>
      (function(){
        var doc = window.parent.document;
        if (!doc.getElementById('scrap-gross-tare-marker')) doc = window.top.document;
        function getGrossTare(){
          var m = doc.getElementById('scrap-gross-tare-marker');
          if (m) {
            var form = m.closest('form') || m.parentElement;
            while (form && form !== doc.body) {
              var inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"])');
              if (inputs.length >= 3) return { g: inputs[1], t: inputs[2] };
              form = form.parentElement;
            }
          }
          var blocks = doc.querySelectorAll('[data-testid="stTextInput"]');
          var g = null, t = null;
          for (var i = 0; i < blocks.length; i++) {
            var lb = blocks[i].querySelector('label');
            var lbl = (lb && lb.textContent) ? lb.textContent.trim() : '';
            if (lbl.indexOf('Gross') >= 0) g = blocks[i].querySelector('input');
            if (lbl.indexOf('Tare') >= 0) t = blocks[i].querySelector('input');
          }
          return { g: g, t: t };
        }
        function findBtn(txt){
          var btns = doc.querySelectorAll('button');
          for(var i=0; i<btns.length; i++){
            var t = (btns[i].innerText || btns[i].textContent || '').trim();
            if(t.indexOf(txt) !== -1) return btns[i];
          }
          return null;
        }
        function onKeyDown(e){
          if (e.key !== 'Enter') return;
          var r = getGrossTare();
          if (!r.g || !r.t) return;
          var active = doc.activeElement;
          if (active === r.g) {
            e.preventDefault();
            e.stopPropagation();
            var toTare = findBtn('→Tare');
            if (toTare) toTare.click();
          } else if (active === r.t) {
            e.preventDefault();
            e.stopPropagation();
            var c = findBtn('Confirm');
            if (c) c.click();
          }
        }
        if (!doc.__enterBound) {
          doc.__enterBound = true;
          doc.addEventListener('keydown', onKeyDown, true);
        }
        // 点击 Gross 时更新 key_target 为 gross，点击 Tare 时仅更新 key_target（不抢焦）
        function bindFocusSync() {
          var r = getGrossTare();
          if (!r.g || !r.t) return;
          r.g.addEventListener('focus', function(){ var b = findBtn('→Gross'); if(b) b.click(); });
          r.t.addEventListener('focus', function(){ var b = findBtn('TareKey'); if(b) b.click(); });
        }
        setTimeout(bindFocusSync, 100);
        setTimeout(bindFocusSync, 400);
        // 隐藏 →Tare / →Gross 按钮（JS 仍可 programmatic click）
        setTimeout(function(){
          var toTare = findBtn('→Tare');
          if (toTare) {
            var block = toTare.closest('[data-testid="stHorizontalBlock"]');
            if (block) block.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;opacity:0';
          }
        }, 50);
        // 屏蔽浏览器记忆/自动补全（Unit Price、Gross、Tare）
        function disableAutocomplete(){
          var m = doc.getElementById('scrap-gross-tare-marker');
          if (m) {
            var form = m.closest('form') || m.parentElement;
            while (form && form !== doc.body) {
              var inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"])');
              for (var i = 0; i < inputs.length; i++) {
                inputs[i].setAttribute('autocomplete', 'off');
              }
              return;
            }
          }
        }
        setTimeout(disableAutocomplete, 100);
        setTimeout(disableAutocomplete, 400);
      })();
    </script>
    """
    components.html(html, height=0)

# -----------------------------
# Ticketing page
# -----------------------------
def ticketing_page():
    topbar("开票")

    clients = qdf("SELECT code, name, phone FROM clients WHERE deleted=0 ORDER BY id DESC")
    operators = qdf("SELECT email, name FROM operators WHERE deleted=0 ORDER BY id DESC")
    cats = qdf("SELECT id,name FROM material_categories ORDER BY sort_order, name")
    mats = qdf("""
        SELECT m.id, c.name AS category, m.item_code, m.name, m.unit, m.unit_price
        FROM materials m
        JOIN material_categories c ON c.id=m.category_id
        WHERE m.deleted=0
        ORDER BY c.sort_order, m.item_code
    """)

    left, mid, right = st.columns([1.25, 2.1, 1.25], gap="medium")

    # ---------- left: Receipt Preview Area
    with left:
        st.markdown("### Receipt Preview Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        csel = clients[clients["code"] == st.session_state.ticket_client_code]
        clabel = "(未选择)"
        if len(csel) > 0:
            clabel = f'{csel.iloc[0]["name"]}'.strip()

        st.markdown(f"<div class='subtle'>Client:</div><div style='font-weight:900'>{clabel}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='subtle' style='margin-top:0.375rem'>Subtotal:</div>"
                    f"<div style='font-size:1.75rem;font-weight:950'>${current_subtotal():.2f}</div>", unsafe_allow_html=True)

        df = recompute_receipt_df(st.session_state.receipt_df)
        if "Del" not in df.columns:
            df.insert(0, "Del", False)
            st.session_state.receipt_df = df

        st.write("")
        if df.empty:
            st.info("No items yet.")
        else:
            edited = st.data_editor(
                df,
                use_container_width=True,
                height=420,
                hide_index=True,
                key="receipt_data_editor",
                column_config={
                    "Del": st.column_config.CheckboxColumn("删", help="勾选即删除此行"),
                    "material": st.column_config.TextColumn("material", disabled=True),
                    "unit_price": st.column_config.NumberColumn("price", step=0.01, format="%.2f"),
                    "gross": st.column_config.NumberColumn("gross", step=1.0, format="%.0f"),
                    "tare": st.column_config.NumberColumn("tare", step=1.0, format="%.0f"),
                    "net": st.column_config.NumberColumn("net", disabled=True, format="%.0f"),
                    "total": st.column_config.NumberColumn("total", disabled=True, format="%.2f"),
                }
            )
            edited = recompute_receipt_df(edited)
            # 勾选删的那一行直接删掉
            if edited["Del"].any():
                keep = edited[edited["Del"] == False].drop(columns=["Del"])
                keep.insert(0, "Del", False)
                st.session_state.receipt_df = recompute_receipt_df(keep)
                st.rerun()
            st.session_state.receipt_df = edited
            # 修改了 unit_price/gross/tare 时 rerun，左侧表格立即显示重新计算后的 net/total
            if not edited[["unit_price", "gross", "tare"]].equals(df[["unit_price", "gross", "tare"]]):
                st.rerun()

        st.write("")
        colA, colB = st.columns(2)
        with colA:
            if st.button("Clear Receipt", use_container_width=True):
                st.session_state.receipt_df = pd.DataFrame(columns=["Del","material","unit_price","gross","tare","net","total"])
                for k in ("_pending_preview_b64", "_pending_preview_token", "_print_diag"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
        with colB:
            if st.button("Print / Save Receipt", type="primary", use_container_width=True):
                st.toast("PRINT CLICKED", icon="🖨️")
                st.session_state["_print_debug_ts"] = time.time()

                df2 = recompute_receipt_df(st.session_state.receipt_df)
                if df2.empty:
                    st.warning("Receipt is empty.")
                    st.stop()

                subtotal = float(df2["total"].sum())
                rounding = round(subtotal, 2)
                wcode = gen_withdraw_code()

                operator_email = st.session_state.ticket_operator
                operator_name = ""
                op = operators[operators["email"] == operator_email]
                if len(op) > 0:
                    operator_name = op.iloc[0]["name"]

                client_code = st.session_state.ticket_client_code
                csel2 = clients[clients["code"] == client_code]
                client_name = csel2.iloc[0]["name"] if len(csel2) > 0 else ""

                issue_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                conn = db()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO receipts(issue_time, issued_by, ticketing_method, withdraw_code,
                                         client_code, client_name, subtotal, rounding_amount, voided, withdrawn)
                    VALUES(?,?,?,?,?,?,?,?,0,0)
                """, (issue_time, operator_name or operator_email, "Print", wcode,
                      client_code, client_name, float(subtotal), float(rounding)))
                rid = cur.lastrowid

                rows = []
                for r in df2.itertuples(index=False):
                    rows.append((
                        rid, r.material, float(r.unit_price), float(r.gross),
                        float(r.tare), float(r.net), float(r.total)
                    ))
                cur.executemany("""
                    INSERT INTO receipt_lines(receipt_id, material_name, unit_price, gross, tare, net, total)
                    VALUES(?,?,?,?,?,?,?)
                """, rows)
                conn.commit()
                conn.close()

                receipt_html = build_receipt_html_for_print(
                    company_name="YGMETAL",
                    ticket_number=str(wcode),
                    email="test@ygmetal.com",
                    issue_time=issue_time,
                    cashier=(operator_name or operator_email),
                    client_name=client_name,
                    lines_df=df2,
                    total_amount=float(rounding),
                    rounding_amount=float(rounding - subtotal),
                    adjustment_amount=0.0,
                    paid_amount=0.0,
                    balance_amount=float(rounding),
                )
                if not receipt_html or len(receipt_html) < 200:
                    st.error("receipt_html empty/too short")
                    st.stop()

                st.success(f"Saved. Withdraw code: {wcode}")

                with st.expander("DEBUG receipt_html (first 400 chars)"):
                    st.code(receipt_html[:400], language="html")

                render_and_print_receipt(receipt_html)
                st.stop()

        st.caption(f"print_debug_ts={st.session_state.get('_print_debug_ts')}")
        # Popup 打印：不再显示跳转/备用链接

        st.markdown("</div>", unsafe_allow_html=True)

    # ---------- middle: Material List Area
    with mid:
        st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
        st.markdown("### Material List Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        catcol, prodcol = st.columns([0.35, 1.65], gap="medium")

        with catcol:
            for cname in cats["name"].tolist():
                is_active = (st.session_state.active_cat == cname)
                btn_type = "primary" if is_active else "secondary"
                if st.button(cname, type=btn_type, use_container_width=True, key=f"cat_{cname}"):
                    st.session_state.active_cat = cname
                    st.rerun()

        with prodcol:
            show = mats[mats["category"] == st.session_state.active_cat].copy()
            if show.empty:
                st.info("No materials in this category.")
            else:
                cols = st.columns(2, gap="small")
                for i, row in enumerate(show.itertuples(index=False)):
                    c = cols[i % 2]
                    with c:
                        if st.button(row.name, use_container_width=True, key=f"mat_{row.id}"):
                            st.session_state.picked_material_id = int(row.id)
                            st.session_state.picked_material_name = row.name

                            # ✅ 价格写进 unit_price_input（widget key）
                            st.session_state.unit_price_input = str(row.unit_price if row.unit_price is not None else "")

                            # ✅ 清零用 flag（下一次 rerun 在控件创建前生效）
                            st.session_state._reset_line_fields = True
                            st.session_state.focus_request = "gross"
                            st.session_state.key_target = "gross"
                            st.rerun()

        st.markdown(
            "<hr style='margin:3rem 0 0.25rem; border:none; border-top:1px solid #e5e7eb;'>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<div style='min-height:120px;'></div>",
            unsafe_allow_html=True
        )
        cam1, cam2 = st.columns(2, gap="small")
        with cam1:
            st.markdown(
                '<div style="aspect-ratio:1; width:100%; max-width:100%; border:1px dashed #9ca3af; border-radius:0.25rem; '
                'display:flex; align-items:center; justify-content:center; color:#6b7280; font-size:0.875em;">'
                '📷 摄像头 1</div>',
                unsafe_allow_html=True
            )
        with cam2:
            st.markdown(
                '<div style="aspect-ratio:1; width:100%; max-width:100%; border:1px dashed #9ca3af; border-radius:0.25rem; '
                'display:flex; align-items:center; justify-content:center; color:#6b7280; font-size:0.875em;">'
                '📷 摄像头 2</div>',
                unsafe_allow_html=True
            )
        st.markdown("</div>", unsafe_allow_html=True)

    # ---------- right: Receiving Area
    with right:
        st.markdown("### Receiving Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        # Search + select + Add
        st.text_input("Search Client (code / name / phone)", key="client_search", placeholder="输入编码/名字/电话...")

        term = (st.session_state.client_search or "").strip().lower()
        f = clients.copy()
        if term:
            def hit(x):
                s = f'{x["code"]} {x["name"]} {x["phone"]}'.lower()
                return term in s
            f = f[f.apply(hit, axis=1)]

        if f.empty:
            options = ["(No match)"]
            code_map = {"(No match)": st.session_state.ticket_client_code}
        else:
            options = [f'{r["code"]} • {r["name"]} {r["phone"]}'.strip() for _, r in f.iterrows()]
            code_map = {lab: lab.split("•")[0].strip() for lab in options}

        current_label = None
        for lab, cc in code_map.items():
            if cc == st.session_state.ticket_client_code:
                current_label = lab
                break
        if current_label is None:
            current_label = options[0]

        r1a, r1b = st.columns([1.35, 0.65], gap="small")

        with r1a:
            sel = st.selectbox(
                "",
                options=options,
                index=options.index(current_label) if current_label in options else 0,
                key="client_selectbox",
                label_visibility="collapsed"
            )
            st.session_state.ticket_client_code = code_map.get(sel, st.session_state.ticket_client_code)

        with r1b:
            if st.button("Add", use_container_width=True):
                st.session_state._show_add_client = True

        if st.session_state._show_add_client:
            with st.expander("Add Client", expanded=True):
                nm = st.text_input("Name", key="new_client_name")
                ph = st.text_input("Phone (optional)", key="new_client_phone")

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Create", type="primary", use_container_width=True):
                        if nm.strip() == "" and ph.strip() == "":
                            st.warning("Please enter name or phone.")
                        else:
                            code = gen_code_6()
                            exec_sql("""
                                INSERT INTO clients(code,name,phone,created_at)
                                VALUES(?,?,?,?)
                            """, (code, nm.strip(), ph.strip(), datetime.now().isoformat(timespec="seconds")))
                            st.success(f"Created client code: {code}")
                            st.session_state.ticket_client_code = code
                            st.session_state._show_add_client = False
                            st.session_state.client_search = ""
                            st.rerun()
                with c2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state._show_add_client = False
                        st.rerun()

        st.write("")
        st.markdown("**Material :**")
        if st.session_state.picked_material_name:
            st.success(st.session_state.picked_material_name)
        else:
            st.info("Pick a material in the middle area.")

        allow_price_edit = (get_setting("unit_price_adjustment_permitted", "Yes") == "Yes")

        # ✅ 先处理「切到 Gross/Tare」按钮（放在最前），这样和 keypad 同一点时 delete 会作用到 Gross
        _sw_hide, _sw_main = st.columns([0.001, 99])
        with _sw_hide:
            _to_tare = st.button("→Tare", key="switch_to_tare", help="Enter from Gross 时自动触发")
            _to_gross = st.button("→Gross", key="switch_to_gross", help="点击 Gross 时自动触发")
            _to_tare_key = st.button("TareKey", key="switch_to_tare_key", help="点击 Tare 时仅更新 key_target")
        if _to_gross:
            st.session_state.key_target = "gross"
        if _to_tare:
            st.session_state.key_target = "tare"
            st.session_state.focus_request = "tare"
            st.session_state._entered_tare_for_line = True
            if (st.session_state.get("tare_input") or "") == "0":
                st.session_state.tare_input = ""
        if _to_tare_key:
            st.session_state.key_target = "tare"
            st.session_state._entered_tare_for_line = True
        # ✅ 未选产品时 Unit Price 不显示；未 Enter 到 Tare 时 Tare 不显示
        if not st.session_state.get("picked_material_id"):
            st.session_state.unit_price_input = ""

        # ✅ 不因 →Tare 而 rerun，避免未提交的表单导致 session_state 里 unit_price 丢失；focus_js 本 run 末尾会执行

        # ✅ 先保存当前值：若本 run 是 form 提交触发的，后面处理 _keypad_pending 可能覆盖，Confirm 时用此快照
        st.session_state._saved_confirm_snapshot = (
            (st.session_state.get("gross_input") or ""),
            (st.session_state.get("tare_input") or ""),
            (st.session_state.get("unit_price_input") or ""),
        )

        # ✅ 在表单创建前应用 keypad 按键；若本 run 刚点了 →Gross，delete/输入应对 Gross 生效
        if st.session_state._keypad_pending:
            act, tgt, ch = st.session_state._keypad_pending
            st.session_state._keypad_pending = None
            if _to_gross and tgt == "tare":
                tgt = "gross"
            if _to_tare_key and tgt == "gross":
                tgt = "tare"
            key_map = {"gross": "gross_input", "tare": "tare_input", "unit_price": "unit_price_input"}
            skey = key_map.get(tgt, "gross_input")
            s = (st.session_state.get(skey) or "") or ""
            if act == "append" and ch and ch in "0123456789." and (ch != "." or "." not in s):
                # Tare/Gross 若当前仅 "0"，首位输 1–9 时用替换，避免出现 "025"
                if skey in ("tare_input", "gross_input") and s.strip() == "0" and ch in "123456789":
                    st.session_state[skey] = ch
                else:
                    st.session_state[skey] = s + ch
            elif act == "backspace":
                st.session_state[skey] = s[:-1]
            st.session_state.focus_request = tgt if tgt in ("gross", "tare") else "gross"

        # ✅ 控件创建前清零（不能在 form 渲染后改 session_state）
        if st.session_state._reset_line_fields:
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._reset_line_fields = False
            st.session_state._entered_tare_for_line = False
            st.session_state._form_reset_key = st.session_state.get("_form_reset_key", 0) + 1
        if st.session_state.get("_clear_all_line_fields"):
            st.session_state.unit_price_input = ""
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._clear_all_line_fields = False
            st.session_state._form_reset_key = st.session_state.get("_form_reset_key", 0) + 1
        # ✅ Tare 在「应为空白」时与 Gross 同一步清空，避免 Confirm 后 Tare 清空有延迟
        if not st.session_state.get("_entered_tare_for_line"):
            st.session_state.tare_input = ""

        _form_key = f"line_entry_form_{st.session_state.get('_form_reset_key', 0)}"
        with st.form(_form_key, clear_on_submit=False):
            st.markdown('<div id="scrap-gross-tare-marker" style="display:none"></div>', unsafe_allow_html=True)
            cA, cB, cC = st.columns([1.0, 1.0, 1.0], gap="small")
            with cA:
                # 仅选中产品时显示 Unit Price，否则空白
                unit_price_val = (st.session_state.get("unit_price_input") or "") if st.session_state.get("picked_material_id") else ""
                st.text_input(
                    "Unit Price ($)",
                    value=unit_price_val,
                    disabled=not allow_price_edit,
                    key="unit_price_input",
                )
            with cB:
                st.text_input(
                    "Gross (LB)",
                    value=st.session_state.get("gross_input", ""),
                    key="gross_input",
                )
            with cC:
                # Tare：空白时用「随 _form_reset_key 变化的 key」强制新建控件，避免沿用旧状态造成延迟
                _fk = st.session_state.get("_form_reset_key", 0)
                if st.session_state.get("_entered_tare_for_line"):
                    st.text_input("Tare (LB)", value=st.session_state.get("tare_input", ""), key="tare_input")
                else:
                    st.text_input("Tare (LB)", value="", key=f"tare_input_blank_{_fk}")

            tare_for_calc = (st.session_state.get("tare_input") or "") if st.session_state.get("_entered_tare_for_line") else ""
            net, total = calc_line(st.session_state.unit_price_input, st.session_state.gross_input, tare_for_calc)
            st.markdown(f"**Net** :red[{net:.2f}] LB &nbsp;&nbsp; **Total Amount** :red[${total:.2f}]")

            b1, b2 = st.columns(2, gap="small")
            with b1:
                clear_click = st.form_submit_button("Clear", use_container_width=True)
            with b2:
                confirm_click = st.form_submit_button("Confirm (Enter)", use_container_width=True)

        if clear_click:
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state._clear_all_line_fields = True
            st.session_state._reset_line_fields = True
            st.session_state._entered_tare_for_line = False
            st.session_state.focus_request = "gross"
            st.session_state.key_target = "gross"
            st.session_state._keypad_pending = None
            st.rerun()

        if confirm_click:
            sg, stare, sup = st.session_state.get("_saved_confirm_snapshot", ("", "", ""))
            # 若快照全空（可能被 clear_on_submit 或竞态清掉）则用当前 session_state
            now_g = (st.session_state.get("gross_input") or "").strip()
            now_t = (st.session_state.get("tare_input") or "").strip()
            now_u = (st.session_state.get("unit_price_input") or "").strip()
            if (sg, stare, sup) == ("", "", "") or (not sg and not stare):
                sg, stare, sup = now_g, now_t, now_u
            elif not sg and now_g:
                sg = now_g
            elif not stare and now_t:
                stare = now_t
            if not sup and now_u:
                sup = now_u
            add_line_to_receipt(override_gross=sg, override_tare=stare, override_unit_price=sup)
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state._reset_line_fields = True
            st.session_state._entered_tare_for_line = False
            st.session_state.key_target = "gross"
            st.session_state._keypad_pending = None
            st.rerun()

        enter_workflow_js()

        if st.session_state.focus_request in ("gross", "tare"):
            st.session_state._focus_counter = st.session_state.get("_focus_counter", 0) + 1
            focus_js(st.session_state.focus_request, st.session_state._focus_counter)
            st.session_state.focus_request = None

        # ✅ Keypad
        st.write("")
        st.markdown("**Keypad**")

        def keypad_append(ch: str):
            tgt = st.session_state.get("key_target", "gross")
            skey = {"unit_price": "unit_price_input", "tare": "tare_input"}.get(tgt, "gross_input")
            s = (st.session_state.get(skey) or "") or ""
            if ch not in "0123456789." or (ch == "." and "." in s):
                return
            st.session_state._keypad_pending = ("append", tgt, ch)

        def keypad_backspace():
            tgt = st.session_state.get("key_target", "gross")
            st.session_state._keypad_pending = ("backspace", tgt, None)

        rA, rB, rC = st.columns(3, gap="small")
        if rA.button("1", use_container_width=True): keypad_append("1"); st.rerun()
        if rB.button("2", use_container_width=True): keypad_append("2"); st.rerun()
        if rC.button("3", use_container_width=True): keypad_append("3"); st.rerun()

        rA, rB, rC = st.columns(3, gap="small")
        if rA.button("4", use_container_width=True): keypad_append("4"); st.rerun()
        if rB.button("5", use_container_width=True): keypad_append("5"); st.rerun()
        if rC.button("6", use_container_width=True): keypad_append("6"); st.rerun()

        rA, rB, rC = st.columns(3, gap="small")
        if rA.button("7", use_container_width=True): keypad_append("7"); st.rerun()
        if rB.button("8", use_container_width=True): keypad_append("8"); st.rerun()
        if rC.button("9", use_container_width=True): keypad_append("9"); st.rerun()

        rA, rB, rC = st.columns(3, gap="small")
        if rA.button("0", use_container_width=True): keypad_append("0"); st.rerun()
        if rB.button(".", use_container_width=True): keypad_append("."); st.rerun()
        if rC.button("delete", use_container_width=True): keypad_backspace(); st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# Manage Pages
# -----------------------------
def manage_receipt_detail_inquiry():
    st.subheader("Receipt Detail Inquiry")
    df = qdf("""
        SELECT id, issue_time, issued_by, ticketing_method, withdraw_code,
               subtotal, rounding_amount,
               CASE WHEN voided=1 THEN 'Voided' ELSE 'Not Voided' END AS void_status,
               CASE WHEN withdrawn=1 THEN 'Withdrawn' ELSE 'Undrawn' END AS withdraw_status
        FROM receipts
        ORDER BY id DESC
        LIMIT 500
    """)
    if df.empty:
        st.info("No receipts yet.")
        return
    st.dataframe(df, use_container_width=True, height=520)

def manage_void_receipts():
    st.subheader("Void / Withdraw Processing")
    df = qdf("""
        SELECT id, issue_time, issued_by,
               (SELECT COUNT(*) FROM receipt_lines rl WHERE rl.receipt_id=r.id) AS material_count,
               subtotal, rounding_amount, ticketing_method,
               CASE WHEN withdrawn=1 THEN 'Withdrawn' ELSE 'Undrawn' END AS withdraw_status,
               CASE WHEN voided=1 THEN 'Voided' ELSE 'Not Voided' END AS void_status
        FROM receipts r
        ORDER BY id DESC
        LIMIT 500
    """)
    if df.empty:
        st.info("No receipts yet.")
        return
    st.dataframe(df, use_container_width=True, height=520)

def manage_daily_summary():
    st.subheader("Daily Transaction Summary")
    df = qdf("""
        SELECT substr(issue_time,1,10) AS issue_date,
               SUM((SELECT COALESCE(SUM(net),0) FROM receipt_lines rl WHERE rl.receipt_id=r.id)) AS invoiced_quantity,
               SUM(subtotal) AS subtotal,
               SUM(rounding_amount) AS rounding_amount
        FROM receipts r
        WHERE voided=0
        GROUP BY issue_date
        ORDER BY issue_date DESC
        LIMIT 1000
    """)
    st.dataframe(df, use_container_width=True, height=520)

def manage_monthly_summary():
    st.subheader("Monthly transaction summary")
    df = qdf("""
        SELECT substr(issue_time,1,7) AS issue_month,
               SUM((SELECT COALESCE(SUM(net),0) FROM receipt_lines rl WHERE rl.receipt_id=r.id)) AS invoiced_quantity,
               SUM(subtotal) AS subtotal,
               SUM(rounding_amount) AS rounding_amount
        FROM receipts r
        WHERE voided=0
        GROUP BY issue_month
        ORDER BY issue_month DESC
        LIMIT 1000
    """)
    st.dataframe(df, use_container_width=True, height=520)

def manage_annual_summary():
    st.subheader("Annual transaction summary")
    df = qdf("""
        SELECT substr(issue_time,1,4) AS issue_year,
               SUM((SELECT COALESCE(SUM(net),0) FROM receipt_lines rl WHERE rl.receipt_id=r.id)) AS invoiced_quantity,
               SUM(subtotal) AS subtotal,
               SUM(rounding_amount) AS rounding_amount
        FROM receipts r
        WHERE voided=0
        GROUP BY issue_year
        ORDER BY issue_year DESC
        LIMIT 100
    """)
    st.dataframe(df, use_container_width=True, height=520)

def manage_clients():
    st.subheader("Client Information Management")
    df = qdf("""
        SELECT code AS 编号, name AS 姓名, id_number AS 身份证号码, phone AS 手机号码, email AS 邮箱地址, deleted AS 删除标志
        FROM clients
        ORDER BY id DESC
        LIMIT 2000
    """)
    st.dataframe(df, use_container_width=True, height=520)

def manage_operators():
    st.subheader("Operator Information Management")
    df = qdf("SELECT email AS 邮箱地址, name AS 姓名, deleted AS 删除标志, created_at FROM operators ORDER BY id DESC")
    st.dataframe(df, use_container_width=True, height=520)

def manage_materials():
    st.subheader("Material Information Management")
    df = qdf("""
        SELECT m.id, c.name AS category, m.item_code, m.name, m.unit,
               m.unit_price, m.min_unit_price, m.max_unit_price, m.deleted
        FROM materials m
        JOIN material_categories c ON c.id=m.category_id
        ORDER BY c.sort_order, m.item_code
        LIMIT 2000
    """)
    st.dataframe(df, use_container_width=True, height=520)

def manage_settings():
    st.subheader("system parameter setting")
    permitted = get_setting("unit_price_adjustment_permitted", "Yes")
    yn = st.radio("Unit Price Adjustment Permitted", ["Yes", "No"], index=0 if permitted=="Yes" else 1, horizontal=True)
    if st.button("Save Settings", type="primary"):
        exec_sql("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", ("unit_price_adjustment_permitted", yn))
        st.success("Saved.")
        st.rerun()

def _manage_placeholder():
    """Manage 页右侧占位：与 ScrapGoGo 布局一致，内容暂留空。"""
    st.markdown("---")
    st.info("此区域留空，待后续开发。")
    st.markdown("")


def _monthly_summary_export_bytes() -> bytes:
    """月汇总导出为 Excel 字节流（合计行 + 月份明细，金额两位小数）。"""
    df = get_monthly_invoice_summary()
    df["合计金额"] = df["合计金额"].apply(lambda x: round(float(x), 2))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Monthly Summary", index=False)
    buf.seek(0)
    return buf.getvalue()


def manage_monthly_summary_page():
    """月票据汇总信息查询：标题、导出/刷新、三列表格（开票时间 MM/YYYY、开票数量、合计金额）+ 合计行。"""
    st.subheader("月票据汇总信息查询")
    col_btn1, col_btn2, _ = st.columns([1, 1, 4])
    with col_btn1:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        excel_bytes = _monthly_summary_export_bytes()
        st.download_button(
            "导出数据到excel",
            data=excel_bytes,
            file_name=f"monthly_invoice_summary_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_btn2:
        if st.button("刷新数据"):
            get_monthly_invoice_summary.clear()
            st.success("刷新成功")
            st.rerun()

    df = get_monthly_invoice_summary()
    n = len(df)
    st.dataframe(df, use_container_width=True, height=min(400, 35 * n + 38))
    st.caption(f"当前显示 1-{n} 条, 共 {n} 条")


def manage_page():
    """Manage 页：与 ScrapGoGo 类似的顶栏 + 左侧菜单 + 右侧内容区。未登录提示。"""
    if not st.session_state.get("ticket_operator"):
        st.warning("请先登录后再访问管理页。")
        return
    topbar("管理")
    menu = [
        ("票据明细信息查询", _manage_placeholder),
        ("日票据汇总信息查询", _manage_placeholder),
        ("月票据汇总信息查询", manage_monthly_summary_page),
        ("年票据汇总信息查询", _manage_placeholder),
        ("票据作废", _manage_placeholder),
        ("客户信息管理", _manage_placeholder),
        ("操作员信息管理", _manage_placeholder),
        ("物料信息管理", _manage_placeholder),
        ("系统参数设置", _manage_placeholder),
    ]

    left, right = st.columns([0.23, 0.77], gap="medium")
    with left:
        st.markdown("### 菜单")
        labels = [m[0] for m in menu]
        idx = labels.index(st.session_state.manage_page) if st.session_state.manage_page in labels else 2
        sel = st.radio("", labels, index=idx)
        st.session_state.manage_page = sel

    with right:
        for label, fn in menu:
            if label == st.session_state.manage_page:
                fn()
                break

# -----------------------------
# Main
# -----------------------------
def _render_preview_page(preview_token: str):
    """当 URL 带 ?preview_token=xxx 时：从 DB 取 HTML，渲染预览页，用户点 Print 触发 window.print()。"""
    html_content = get_preview_html(preview_token)
    if not html_content:
        st.error("Preview not found or expired.")
        if st.button("Close"):
            components.html("<script>window.close();</script>", height=0)
        return
    components.html(html_content, height=1200)
    if st.button("Close window"):
        components.html("<script>window.close();</script>", height=0)

def _render_preview_page_by_rid(rid: int):
    """方案1：URL 带 ?preview_rid=xxx 时，从 DB 读 receipt+lines 生成收据 HTML，仅渲染预览页（真实 URL 顶层页），Print/Close 在 HTML 内。"""
    html_content = get_receipt_preview_html(rid)
    if not html_content:
        st.error("Receipt not found or invalid id.")
        if st.button("Close"):
            components.html("<script>window.close();</script>", height=0)
        return
    # 提高高度并依赖页面内 85vh 滚动，避免只显示前几条明细
    components.html(html_content, height=1200)

def main():
    try:
        init_db()
    except Exception as e:
        st.error(f"数据库初始化失败: {e}")
        st.exception(e)
        return

    # C: 本地预览路由 — ?preview_token=xxx 时只渲染预览页
    params = getattr(st, "query_params", None)
    preview_token = None
    preview_rid = None
    if params is not None:
        preview_token = params.get("preview_token")
        if isinstance(preview_token, list):
            preview_token = preview_token[0] if preview_token else None
        preview_rid = params.get("preview_rid")
        if isinstance(preview_rid, list):
            preview_rid = preview_rid[0] if preview_rid else None
    if preview_rid:
        try:
            _render_preview_page_by_rid(int(preview_rid))
        except (ValueError, TypeError):
            st.error("Invalid preview_rid.")
        return
    if preview_token:
        _render_preview_page(preview_token)
        return

    try:
        ss_init()
    except Exception as e:
        st.error(f"会话初始化失败: {e}")
        st.exception(e)
        return
    css()

    # 最上面两个入口：开票（前台） / 管理（后台）
    st.markdown("**请选择：** 点击下方 **「开票」** 做前台收银开票，点击 **「管理」** 进入后台（月汇总、客户/操作员/物料等）。")
    tab_open, tab_manage = st.tabs(["开票（前台）", "管理（后台）"])
    with tab_open:
        ticketing_page()
    with tab_manage:
        manage_page()


if __name__ == "__main__":
    import sys
    # 若由 streamlit 启动则直接跑 main；若用 python app.py 则先启动 streamlit
    if "streamlit" in sys.modules:
        main()
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "streamlit", "run", __file__] + sys.argv[1:])
# hook test

