"""
Manage page — all sub-pages for administration.
B3: Category / Material / Client / Operator CRUD (no auto-generation).
"""

import time
import base64
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from components.navigation import topbar
from components.printer import open_print_window
from db.repo_ticketing import (
    get_receipt, get_receipt_lines, void_ticket, restore_ticket,
    update_receipt_lines,
    get_receipt_detail_inquiry_df, get_ticket_report_rows,
    get_void_receipts_df,
)
from db.repo_customers import get_all_clients_df, update_client, delete_client, save_customer
from db.repo_products import (
    get_categories, get_materials, get_all_materials_df,
    add_category, delete_category,
    add_material, update_material, delete_material, restore_material,
    get_all_operators_df, add_operator, delete_operator,
    get_setting, save_setting,
)
from services.ticketing_service import generate_print_receipt
from services.report_service import (
    get_monthly_invoice_summary, get_daily_summary_df,
    get_monthly_summary_df, get_annual_summary_df,
    build_daily_report_html,
)
from services.export_service import monthly_summary_export_bytes


# ---------------------------------------------------------------------------
# Ticket detail view
# ---------------------------------------------------------------------------

def _rdi_ticket_detail_view(rid):
    receipt = get_receipt(rid)
    if not receipt:
        st.error("Ticket not found.")
        if st.button("Back", key="rdi_detail_back_err"):
            st.session_state.pop("_rdi_open_ticket", None)
            st.rerun()
        return

    lines_df = get_receipt_lines(rid)
    status_text = "VOIDED" if receipt["voided"] else "OPEN"
    issue_time_raw = receipt["issue_time"] or ""
    try:
        dt = datetime.strptime(issue_time_raw, "%Y-%m-%d %H:%M:%S")
        created_date = dt.strftime("%m/%d/%Y")
        created_time = dt.strftime("%I:%M %p")
    except Exception:
        created_date = issue_time_raw[:10] if len(issue_time_raw) >= 10 else issue_time_raw
        created_time = issue_time_raw[11:] if len(issue_time_raw) > 11 else ""

    client_name = (receipt["client_name"] or "").strip() or "-"
    issued_by = (receipt["issued_by"] or "").strip() or "-"
    method = (receipt["ticketing_method"] or "").strip() or "-"

    st.markdown(
        f"""<div style="background:#2c3e50;color:white;padding:10px 16px;border-radius:6px;
        font-size:14px;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>Ticket Details</b>
          <span style="font-size:12px;">Home / Ticket Details</span>
        </div>
        <div style="margin-top:8px;font-size:15px;font-weight:700;">
          Ticket Id : {rid} / {status_text}
        </div>
        </div>""",
        unsafe_allow_html=True)

    hd1, hd2 = st.columns([6, 4])
    with hd2:
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("⬅ Back", key="rdi_detail_back", use_container_width=True):
                st.session_state.pop("_rdi_open_ticket", None)
                st.rerun()
        with bc2:
            confirm_change = st.button("✏ Confirm Change", key="rdi_detail_confirm",
                                       use_container_width=True, type="primary")

    ic1, ic2, ic3, ic4 = st.columns(4)
    with ic1:
        st.caption("Seller"); st.text(client_name)
    with ic2:
        st.caption("Created on"); st.text(created_date)
    with ic3:
        st.caption("Time"); st.text(created_time)
    with ic4:
        st.caption("By"); st.text(f"{issued_by} - {method}")

    st.markdown("---")
    st.markdown("##### Material Lines")
    mh = st.columns([2, 1, 1, 1, 1, 1, 1.2])
    mh[0].markdown("**Material Name**")
    mh[1].markdown("**Gross(M)**")
    mh[2].markdown("**Tare**")
    mh[3].markdown("**Net**")
    mh[4].markdown("**Price**")
    mh[5].markdown("**Amount**")
    mh[6].markdown("**Created Date**")

    edited_lines = []
    total_gross = total_tare = total_net = total_amount = 0.0
    for idx, ln in lines_df.iterrows():
        line_id = int(ln["id"])
        mc = st.columns([2, 1, 1, 1, 1, 1, 1.2])
        mc[0].text(ln["material_name"] or "")
        new_gross = mc[1].number_input("Gross", value=float(ln["gross"] or 0),
                                       min_value=0.0, step=0.01,
                                       key=f"rdi_g_{line_id}", label_visibility="collapsed")
        new_tare = mc[2].number_input("Tare", value=float(ln["tare"] or 0),
                                      min_value=0.0, step=0.01,
                                      key=f"rdi_t_{line_id}", label_visibility="collapsed")
        new_net = round(new_gross - new_tare, 4)
        price = float(ln["unit_price"] or 0)
        new_total = round(new_net * price, 2)
        mc[3].text(f"{new_net:.2f}")
        mc[4].text(f"${price:.3f}")
        mc[5].text(f"${new_total:.2f}")
        mc[6].text(created_date)
        edited_lines.append((line_id, new_gross, new_tare, new_net, new_total))
        total_gross += new_gross
        total_tare += new_tare
        total_net += new_net
        total_amount += new_total

    st.markdown("---")
    ts = st.columns([2, 1, 1, 1, 1, 1, 1.2])
    ts[0].markdown(f"**{len(lines_df)} Material(s)**")
    ts[1].text(f"{total_gross:.2f}")
    ts[2].text(f"{total_tare:.2f}")
    ts[3].text(f"{total_net:.2f}")
    ts[4].text("")
    rounding = float(receipt["rounding_amount"] or 0)
    ts[5].text(f"${total_amount:.2f}")
    ts[6].text("")

    st.markdown("---")
    sm = st.columns([1.2, 1, 1, 1, 1.2])
    sm[0].metric("Actual Amount", f"${total_amount:.3f}")
    sm[1].metric("Rounding", f"${rounding:.3f}")
    sm[2].metric("Amount", f"${total_amount + rounding:.3f}")
    sm[3].metric("Adjustment", "$0.000")
    sm[4].metric("Balance Amount", f"${total_amount + rounding:.3f}")

    st.markdown("---")
    ft1, ft2, ft3 = st.columns([5, 2, 2])
    with ft3:
        printout_click = st.button("🖨 Printout", key="rdi_detail_print",
                                   use_container_width=True, type="primary")

    if confirm_change:
        update_receipt_lines(edited_lines, rounding, rid)
        st.success("修改已保存！")
        st.rerun()

    if printout_click:
        receipt_data = generate_print_receipt(rid)
        if receipt_data and receipt_data.get("html"):
            st.session_state._pending_print_html = receipt_data["html"]
            st.rerun()


# ---------------------------------------------------------------------------
# Receipt detail inquiry
# ---------------------------------------------------------------------------

def manage_receipt_detail_inquiry():
    st.subheader("票据明细信息查询")

    if st.session_state.get("_rdi_open_ticket"):
        _rdi_ticket_detail_view(st.session_state._rdi_open_ticket)
        return

    st.markdown("""<style>
    .rdi-icons .stButton > button {
        width: 40px !important; min-width: 40px !important; max-width: 40px !important;
        height: 40px !important; min-height: 40px !important; max-height: 40px !important;
        padding: 0 !important; overflow: hidden !important;
    }
    .rdi-icons [data-testid="column"] {
        flex: 0 0 48px !important; min-width: 48px !important; max-width: 48px !important;
    }
    .rdi-icons [data-testid="stHorizontalBlock"] {
        gap: 4px !important; flex-wrap: nowrap !important;
    }
    </style>""", unsafe_allow_html=True)

    col_from, col_to, col_btns, _ = st.columns([1.2, 1.2, 1.5, 2.5])
    today = datetime.now().date()
    with col_from:
        from_date = st.date_input("From Date", value=today, key="rdi_from")
    with col_to:
        to_date = st.date_input("To Date", value=today, key="rdi_to")
    with col_btns:
        st.markdown("<label style='visibility:hidden;font-size:14px;'>.</label>",
                    unsafe_allow_html=True)
        st.markdown('<div class="rdi-icons">', unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        with b1:
            search_click = st.button("🔍", key="rdi_search", type="primary")
        with b2:
            refresh_click = st.button("🔄", key="rdi_refresh")
        with b3:
            report_click = st.button("📋", key="rdi_report")
        st.markdown('</div>', unsafe_allow_html=True)

    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")
    df = get_receipt_detail_inquiry_df(from_str, to_str)

    if report_click:
        rows = get_ticket_report_rows(from_str, to_str)
        report_html = build_daily_report_html(from_str, to_str, rows)
        b64 = base64.b64encode(report_html.encode("utf-8")).decode("ascii")
        ts_val = int(time.time() * 1000)
        js = f"""<!-- ts={ts_val} --><script>
(function() {{
  try {{
    var w = window.open('', '_blank');
    if (w) {{ w.document.write(atob("{b64}")); w.document.close(); }}
    else {{
      var a = document.createElement('a');
      a.href = 'data:text/html;base64,{b64}'; a.target = '_blank'; a.click();
    }}
  }} catch(e) {{ console.error(e); }}
}})();
</script>"""
        components.html(js, height=0)

    if df.empty:
        st.info("所选日期范围内没有票据。")
        return

    total_rows = len(df)
    page_size = 10
    total_pages = max(1, (total_rows + page_size - 1) // page_size)

    if "_rdi_page" not in st.session_state:
        st.session_state._rdi_page = 1
    cur_page = st.session_state._rdi_page
    if cur_page > total_pages:
        cur_page = total_pages
        st.session_state._rdi_page = cur_page

    start_idx = (cur_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_rows)
    page_df = df.iloc[start_idx:end_idx]

    for _, row in page_df.iterrows():
        rid = int(row["Ticket Id"])
        status = row["Status"]
        status_html = (
            '<span style="background:#28a745;color:#fff;padding:1px 6px;border-radius:8px;font-size:11px;">OPEN</span>'
            if status == "OPEN" else
            '<span style="background:#dc3545;color:#fff;padding:1px 6px;border-radius:8px;font-size:11px;">VOIDED</span>'
        )
        amt = float(row["Total Amount"])
        c1, c2, c3, c4, c5, c6 = st.columns([0.6, 1.2, 0.6, 1.0, 0.5, 0.6])
        with c1:
            st.markdown(f"<span>#{rid}</span>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<span>{row['Date Created']} {row.get('Time','')}</span>",
                        unsafe_allow_html=True)
        with c3:
            st.markdown(status_html, unsafe_allow_html=True)
        with c4:
            st.markdown(f"<span>${amt:,.2f}</span>", unsafe_allow_html=True)
        with c5:
            if st.button("🗑", key=f"rdi_void_{rid}", use_container_width=True):
                void_ticket(rid)
                st.rerun()
        with c6:
            if st.button("Open", key=f"rdi_open_{rid}", use_container_width=True):
                st.session_state._rdi_open_ticket = rid
                st.rerun()

    # Pagination
    st.markdown(f"<span style='font-size:12px;color:#888;'>"
                f"Showing {start_idx+1}-{end_idx} of {total_rows}</span>",
                unsafe_allow_html=True)
    if total_pages > 1:
        nav = st.columns(min(total_pages, 7))
        for i, pn in enumerate(range(1, min(total_pages, 7) + 1)):
            with nav[i]:
                btn_type = "primary" if pn == cur_page else "secondary"
                if st.button(str(pn), key=f"rdi_pg_{pn}", use_container_width=True,
                             type=btn_type):
                    st.session_state._rdi_page = pn
                    st.rerun()


# ---------------------------------------------------------------------------
# B3: Category CRUD
# ---------------------------------------------------------------------------

def manage_categories_crud():
    st.subheader("Category Management")

    cats = get_categories()
    st.markdown("**Current Categories:**")
    if cats.empty:
        st.info("No categories. Add one below.")
    else:
        for _, row in cats.iterrows():
            cid = int(row["id"])
            cc1, cc2 = st.columns([4, 1])
            with cc1:
                st.text(row["name"])
            with cc2:
                if st.button("Delete", key=f"del_cat_{cid}", use_container_width=True):
                    ok = delete_category(cid)
                    if ok:
                        st.success(f"Deleted: {row['name']}")
                    else:
                        st.error("Cannot delete — has active materials. Remove materials first.")
                    st.rerun()

    st.markdown("---")
    st.markdown("**Add New Category:**")
    ac1, ac2 = st.columns([3, 1])
    with ac1:
        new_cat = st.text_input("Category Name", key="new_cat_name",
                                placeholder="e.g. Copper, Aluminum...")
    with ac2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Add", key="add_cat_btn", type="primary", use_container_width=True):
            if (new_cat or "").strip():
                add_category(new_cat.strip())
                st.success(f"Added: {new_cat.strip()}")
                st.rerun()
            else:
                st.warning("Enter a name.")


# ---------------------------------------------------------------------------
# B3: Material CRUD
# ---------------------------------------------------------------------------

def manage_materials_crud():
    st.subheader("Material / Item Management")

    cats = get_categories()
    if cats.empty:
        st.warning("No categories exist. Create categories first in Category Management.")
        return

    cat_names = cats["name"].tolist()
    selected_cat = st.selectbox("Select Category", cat_names, key="mat_crud_cat")
    cat_row = cats[cats["name"] == selected_cat].iloc[0]
    cat_id = int(cat_row["id"])

    mats = get_all_materials_df()
    cat_mats = mats[mats["category"] == selected_cat].copy()

    if cat_mats.empty:
        st.info(f"No materials in '{selected_cat}'. Add one below.")
    else:
        st.markdown("**Materials:**")
        for _, row in cat_mats.iterrows():
            mid = int(row["id"])
            is_deleted = bool(row["deleted"])
            mc1, mc2, mc3, mc4 = st.columns([2.5, 1, 1, 1])
            with mc1:
                label = f"{'~~' + row['name'] + '~~' if is_deleted else row['name']}"
                st.markdown(f"{label} `{row['item_code']}`")
            with mc2:
                new_price = st.number_input(
                    "Price", value=float(row["unit_price"] or 0), step=0.001,
                    format="%.3f", key=f"mp_{mid}", label_visibility="collapsed")
            with mc3:
                if st.button("Save", key=f"msv_{mid}", use_container_width=True):
                    update_material(mid, new_price,
                                    float(row.get("min_unit_price") or 0),
                                    float(row.get("max_unit_price") or 0))
                    st.success("Saved")
                    st.rerun()
            with mc4:
                if is_deleted:
                    if st.button("Restore", key=f"mre_{mid}", use_container_width=True):
                        restore_material(mid)
                        st.rerun()
                else:
                    if st.button("Delete", key=f"mdl_{mid}", use_container_width=True):
                        delete_material(mid)
                        st.rerun()

    st.markdown("---")
    st.markdown("**Add New Material:**")
    a1, a2, a3, a4 = st.columns([1.5, 1, 1, 1])
    with a1:
        new_name = st.text_input("Name", key="new_mat_name", placeholder="e.g. Cu#1")
    with a2:
        new_code = st.text_input("Code", key="new_mat_code", placeholder="e.g. CU001")
    with a3:
        new_price = st.number_input("Unit Price", value=0.0, step=0.001,
                                    format="%.3f", key="new_mat_price")
    with a4:
        new_unit = st.text_input("Unit", value="LB", key="new_mat_unit")

    if st.button("Add Material", key="add_mat_btn", type="primary"):
        if (new_name or "").strip() and (new_code or "").strip():
            add_material(cat_id, new_code.strip(), new_name.strip(),
                         new_unit.strip(), new_price, 0.0, 0.0)
            st.success(f"Added: {new_name.strip()}")
            st.rerun()
        else:
            st.warning("Name and Code are required.")


# ---------------------------------------------------------------------------
# B3: Client CRUD
# ---------------------------------------------------------------------------

def manage_clients_crud():
    st.subheader("Client Information Management")
    df = get_all_clients_df()
    if df.empty:
        st.info("No clients.")
    else:
        st.dataframe(df, use_container_width=True, height=400)

    st.markdown("---")
    st.markdown("**Add New Client:**")
    nc1, nc2 = st.columns(2)
    with nc1:
        cn = st.text_input("Name", key="mgr_new_client_name")
    with nc2:
        cp = st.text_input("Phone", key="mgr_new_client_phone")
    if st.button("Add Client", key="mgr_add_client", type="primary"):
        if (cn or "").strip():
            code = save_customer(cn, cp)
            st.success(f"Created client: {code}")
            st.rerun()
        else:
            st.warning("Name is required.")


# ---------------------------------------------------------------------------
# B3: Operator CRUD
# ---------------------------------------------------------------------------

def manage_operators_crud():
    st.subheader("Operator Information Management")
    df = get_all_operators_df()
    if df.empty:
        st.info("No operators.")
    else:
        st.dataframe(df, use_container_width=True, height=400)

    st.markdown("---")
    st.markdown("**Add New Operator:**")
    oc1, oc2 = st.columns(2)
    with oc1:
        oe = st.text_input("Email", key="mgr_new_op_email")
    with oc2:
        on = st.text_input("Name", key="mgr_new_op_name")
    if st.button("Add Operator", key="mgr_add_op", type="primary"):
        if (oe or "").strip() and (on or "").strip():
            add_operator(oe, on)
            st.success("Added.")
            st.rerun()
        else:
            st.warning("Email and Name required.")


# ---------------------------------------------------------------------------
# Summary pages
# ---------------------------------------------------------------------------

def manage_void_receipts():
    st.subheader("票据作废")
    df = get_void_receipts_df()
    if df.empty:
        st.info("目前没有已作废的单据。")
        return

    st.caption(f"共 {len(df)} 条已作废单据")

    hdr = st.columns([0.5, 1.2, 0.8, 0.6, 0.8, 0.8, 0.8, 0.7])
    hdr[0].markdown("**#ID**")
    hdr[1].markdown("**开票时间**")
    hdr[2].markdown("**开票人**")
    hdr[3].markdown("**品项数**")
    hdr[4].markdown("**小计**")
    hdr[5].markdown("**舍入**")
    hdr[6].markdown("**方式**")
    hdr[7].markdown("**操作**")

    for _, row in df.iterrows():
        rid = int(row["id"])
        c = st.columns([0.5, 1.2, 0.8, 0.6, 0.8, 0.8, 0.8, 0.7])
        c[0].text(str(rid))
        c[1].text(str(row["issue_time"] or ""))
        c[2].text(str(row["issued_by"] or ""))
        c[3].text(str(row["material_count"]))
        c[4].text(f"${float(row['subtotal'] or 0):,.2f}")
        c[5].text(f"${float(row['rounding_amount'] or 0):,.2f}")
        c[6].text(str(row["ticketing_method"] or ""))
        with c[7]:
            if st.button("恢复", key=f"void_restore_{rid}", use_container_width=True):
                restore_ticket(rid)
                st.success(f"单据 #{rid} 已恢复")
                st.rerun()


def manage_daily_summary():
    st.subheader("Daily Transaction Summary")

    # ── Toolbar: Export to Excel | Refresh | Search ──
    tb1, tb2, tb_spacer, tb3 = st.columns([1, 1, 3, 1])
    with tb1:
        export_click = st.button("Export to Excel", type="primary",
                                 use_container_width=True, key="dts_export")
    with tb2:
        refresh_click = st.button("Refresh", use_container_width=True, key="dts_refresh")
    with tb3:
        search_click = st.button("Search", use_container_width=True, key="dts_search")

    if search_click:
        st.session_state._dts_search_open = True
    if refresh_click:
        for k in ("_dts_start", "_dts_end", "_dts_method", "_dts_void", "_dts_withdrawn"):
            st.session_state.pop(k, None)
        st.session_state.pop("_dts_search_open", None)
        st.session_state.pop("_dts_page", None)
        st.rerun()

    # ── Search conditions dialog ──
    if st.session_state.get("_dts_search_open"):
        with st.expander("Enter Conditions", expanded=True):
            sc1, sc2 = st.columns(2)
            with sc1:
                s_start = st.date_input("Receipting Start Date",
                                        value=st.session_state.get("_dts_start"),
                                        key="dts_sd")
            with sc2:
                s_end = st.date_input("Receipting End Date",
                                      value=st.session_state.get("_dts_end"),
                                      key="dts_ed")

            s_method = st.radio("Ticketing method",
                                ["All", "Print", "Email"],
                                index=0, horizontal=True, key="dts_method_r")
            s_void = st.radio("Void Mark",
                              ["All", "Not Voided", "Voided"],
                              index=0, horizontal=True, key="dts_void_r")
            s_withdrawn = st.radio("Customer service representative",
                                   ["All", "Undrawn", "Withdrawn"],
                                   index=0, horizontal=True, key="dts_withdrawn_r")

            dc1, dc2 = st.columns(2)
            with dc1:
                if st.button("Confirm", type="primary", use_container_width=True,
                             key="dts_confirm"):
                    st.session_state._dts_start = s_start
                    st.session_state._dts_end = s_end
                    st.session_state._dts_method = s_method
                    st.session_state._dts_void = s_void
                    st.session_state._dts_withdrawn = s_withdrawn
                    st.session_state._dts_search_open = False
                    st.session_state._dts_page = 1
                    st.rerun()
            with dc2:
                if st.button("Cancel", use_container_width=True, key="dts_cancel"):
                    st.session_state._dts_search_open = False
                    st.rerun()

    # ── Query with current filters ──
    f_start = st.session_state.get("_dts_start")
    f_end = st.session_state.get("_dts_end")
    f_method = st.session_state.get("_dts_method", "All")
    f_void = st.session_state.get("_dts_void", "All")
    f_withdrawn = st.session_state.get("_dts_withdrawn", "All")

    start_str = f_start.strftime("%Y-%m-%d") if f_start else None
    end_str = f_end.strftime("%Y-%m-%d") if f_end else None

    df = get_daily_summary_df(start_date=start_str, end_date=end_str,
                              method_filter=f_method, void_filter=f_void,
                              withdrawn_filter=f_withdrawn)

    # ── Export handler ──
    if export_click and not df.empty:
        import io
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        ts_str = datetime.now().strftime("%Y%m%d_%H%M")
        st.download_button("Download Excel", data=buf.getvalue(),
                           file_name=f"daily_transaction_summary_{ts_str}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dts_dl")

    if df.empty:
        st.info("No data for current filters.")
        return

    # ── Rename columns to match ScrapGoGo ──
    display = df.rename(columns={
        "issue_date": "Issue Time",
        "invoiced_quantity": "Invoiced quantity",
        "subtotal": "Subtotal",
        "rounding_amount": "Rounding Amount",
    })

    # ── Subtotal row at top ──
    subtotal_row = pd.DataFrame([{
        "Issue Time": "Subtotal",
        "Invoiced quantity": display["Invoiced quantity"].sum(),
        "Subtotal": round(display["Subtotal"].sum(), 2),
        "Rounding Amount": round(display["Rounding Amount"].sum(), 2),
    }])
    full_df = pd.concat([subtotal_row, display], ignore_index=True)

    # ── Pagination (100 rows per page) ──
    page_size = 100
    total_rows = len(full_df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    if "_dts_page" not in st.session_state:
        st.session_state._dts_page = 1
    cur_page = min(st.session_state._dts_page, total_pages)

    start_idx = (cur_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_rows)
    page_df = full_df.iloc[start_idx:end_idx]

    # ── Render table ──
    st.dataframe(page_df, use_container_width=True,
                 height=min(600, 35 * len(page_df) + 40), hide_index=True)

    # ── Pagination bar ──
    st.markdown(
        f"<span style='font-size:12px;color:#888;'>"
        f"showing {start_idx + 1}–{end_idx} of {total_rows} rows</span>",
        unsafe_allow_html=True)
    if total_pages > 1:
        max_btns = min(total_pages, 7)
        cols = st.columns(max_btns + 2)
        with cols[0]:
            if st.button("«", key="dts_pg_prev", disabled=(cur_page <= 1)):
                st.session_state._dts_page = cur_page - 1
                st.rerun()
        for i in range(max_btns):
            pn = i + 1
            with cols[i + 1]:
                btn_t = "primary" if pn == cur_page else "secondary"
                if st.button(str(pn), key=f"dts_pg_{pn}", type=btn_t,
                             use_container_width=True):
                    st.session_state._dts_page = pn
                    st.rerun()
        with cols[max_btns + 1]:
            if st.button("»", key="dts_pg_next", disabled=(cur_page >= total_pages)):
                st.session_state._dts_page = cur_page + 1
                st.rerun()


def manage_monthly_summary():
    st.subheader("Monthly Transaction Summary")
    df = get_monthly_summary_df()
    st.dataframe(df, use_container_width=True, height=520)


def manage_annual_summary():
    st.subheader("Annual Transaction Summary")
    df = get_annual_summary_df()
    st.dataframe(df, use_container_width=True, height=520)


def manage_settings():
    st.subheader("System Settings")
    permitted = get_setting("unit_price_adjustment_permitted", "Yes")
    yn = st.radio("Unit Price Adjustment Permitted", ["Yes", "No"],
                  index=0 if permitted == "Yes" else 1, horizontal=True,
                  key="mgr_price_adj_radio")
    if st.button("Save Settings", type="primary", key="mgr_save_settings"):
        save_setting("unit_price_adjustment_permitted", yn)
        st.success("Saved.")
        st.rerun()


def manage_monthly_summary_page():
    st.subheader("月票据汇总信息查询")
    col_btn1, col_btn2, _ = st.columns([1, 1, 4])
    with col_btn1:
        ts_str = datetime.now().strftime("%Y%m%d_%H%M")
        excel_bytes = monthly_summary_export_bytes()
        st.download_button(
            "导出数据到excel", data=excel_bytes,
            file_name=f"monthly_invoice_summary_{ts_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="msp_export")
    with col_btn2:
        if st.button("刷新数据", key="msp_refresh"):
            get_monthly_invoice_summary.clear()
            st.success("刷新成功")
            st.rerun()

    df = get_monthly_invoice_summary()
    n = len(df)
    st.dataframe(df, use_container_width=True, height=min(400, 35 * n + 38))
    st.caption(f"当前显示 1-{n} 条, 共 {n} 条")


# ---------------------------------------------------------------------------
# Main manage page
# ---------------------------------------------------------------------------

_MANAGE_MENU_CSS = """
<style>
/* ── Nav menu radio → bordered button boxes ──
   Target: the FIRST stColumn's radio (= the 22% left menu column).
   Streamlit renders st.markdown and st.radio as siblings, NOT nested,
   so we must use the column data-testid as the anchor.               */

[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] {
    gap: 0 !important;
}
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    box-sizing: border-box !important;
    background: #fff !important;
    color: #333 !important;
    border: 1px solid #d1d5db !important;
    border-radius: 6px !important;
    margin: 0 0 -1px 0 !important;
    padding: 14px 14px !important;
    cursor: pointer !important;
    min-height: 48px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    transition: background 0.15s, color 0.15s !important;
}
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label:hover {
    background: #f3f4f6 !important;
}
/* Selected item → red */
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label[data-checked="true"],
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked) {
    background: #ef4444 !important;
    color: #fff !important;
    font-weight: 600 !important;
    border-color: #ef4444 !important;
    z-index: 1;
    position: relative;
}
/* Inner text inherits color */
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label p,
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label span {
    color: inherit !important;
    font-size: inherit !important;
}
/* Hide radio circle/dot */
[data-testid="stColumn"]:first-child [data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child {
    display: none !important;
}
</style>
"""


def manage_page():
    if not st.session_state.get("ticket_operator"):
        st.warning("请先登录后再访问管理页。")
        return
    topbar("管理")

    menu = [
        ("票据明细信息查询", manage_receipt_detail_inquiry),
        ("日票据汇总信息查询", manage_daily_summary),
        ("月票据汇总信息查询", manage_monthly_summary_page),
        ("年票据汇总信息查询", manage_annual_summary),
        ("票据作废", manage_void_receipts),
        ("客户信息管理", manage_clients_crud),
        ("操作员信息管理", manage_operators_crud),
        ("类别管理 (Category CRUD)", manage_categories_crud),
        ("物料管理 (Material CRUD)", manage_materials_crud),
        ("系统参数设置", manage_settings),
    ]

    labels = [m[0] for m in menu]
    if st.session_state.get("manage_page") not in labels:
        st.session_state.manage_page = labels[0]

    def _on_nav_change():
        st.session_state.manage_page = st.session_state._mnav_radio

    left, right = st.columns([0.22, 0.78], gap="small")

    with left:
        st.markdown(_MANAGE_MENU_CSS, unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:1.15rem;font-weight:700;padding:10px 4px 8px;">Menu</div>',
            unsafe_allow_html=True)
        cur_idx = labels.index(st.session_state.manage_page)
        st.radio("菜单", labels, index=cur_idx, key="_mnav_radio",
                 on_change=_on_nav_change, label_visibility="collapsed")

    with right:
        for label, fn in menu:
            if label == st.session_state.manage_page:
                fn()
                break
