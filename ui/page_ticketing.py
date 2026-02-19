"""
Ticketing page — ScrapGoGo two-column layout.
  Left : category tabs + product grid
  Right: client + input area + keypad + receipt

Bug fixes applied:
  Bug 1: focus_js retry schedule extended to 500ms for reliable auto-focus
  Bug 2: tare uses a SINGLE widget key (no key swap) to prevent stale cache
  Bug 3: data_editor key includes _receipt_edit_ver counter → fresh on every change
"""

import time
from datetime import datetime

import streamlit as st
import pandas as pd

from core.utils import calc_line, recompute_receipt_df, current_subtotal
from core.state import (
    record_action, bump_receipt_ver,
    is_transition_locked, transition_step, unlock_transition,
    STEP_SELECT_ITEM, STEP_GROSS_INPUT, STEP_TARE_INPUT, STEP_CONFIRM, STEP_DONE,
)
from db.repo_customers import get_clients, save_customer
from db.repo_products import (
    get_categories, get_materials, get_operators,
    get_setting, gen_withdraw_code,
)
from services.ticketing_service import (
    add_line_to_receipt, build_receipt_html_for_print,
)
from db.repo_ticketing import finalize_ticket
from components.navigation import topbar
from components.printer import open_print_window
from components.keypad import render_keypad, render_enter_workflow_js, focus_js


def ticketing_page():
    topbar("开票")

    clients = get_clients()
    operators = get_operators()
    cats = get_categories()
    mats = get_materials()

    # ===================== TWO-COLUMN LAYOUT (B2) =====================
    col_left, col_right = st.columns([1.3, 1.0], gap="medium")

    # ================================================================
    # LEFT COLUMN: Categories + Products
    # ================================================================
    with col_left:
        st.markdown("### Material List")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        catcol, prodcol = st.columns([0.3, 1.7], gap="small")

        with catcol:
            for cname in cats["name"].tolist():
                is_active = (st.session_state.active_cat == cname)
                btn_type = "primary" if is_active else "secondary"
                if st.button(cname, type=btn_type, use_container_width=True,
                             key=f"cat_{cname}"):
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
                        if st.button(row.name, use_container_width=True,
                                     key=f"mat_{row.id}"):
                            st.session_state.picked_material_id = int(row.id)
                            st.session_state.picked_material_name = row.name
                            st.session_state.unit_price_input = str(
                                row.unit_price if row.unit_price is not None else "")
                            st.session_state._reset_line_fields = True
                            st.session_state.focus_request = "gross"
                            st.session_state.key_target = "gross"
                            transition_step(STEP_GROSS_INPUT)
                            unlock_transition()
                            st.rerun()

        st.markdown("<hr style='margin:0.5rem 0;border:none;border-top:1px solid #e5e7eb;'>",
                    unsafe_allow_html=True)
        cam1, cam2 = st.columns(2, gap="small")
        with cam1:
            st.markdown(
                '<div style="height:100px;width:100%;border:1px dashed #9ca3af;border-radius:0.25rem;'
                'display:flex;align-items:center;justify-content:center;color:#6b7280;font-size:0.875em;">'
                '📷 摄像头 1</div>',
                unsafe_allow_html=True)
        with cam2:
            st.markdown(
                '<div style="height:100px;width:100%;border:1px dashed #9ca3af;border-radius:0.25rem;'
                'display:flex;align-items:center;justify-content:center;color:#6b7280;font-size:0.875em;">'
                '📷 摄像头 2</div>',
                unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # ================================================================
    # RIGHT COLUMN: Receipt + Inputs + Keypad
    # ================================================================
    with col_right:
        # ---------- Client selector (compact) ----------
        st.text_input("Search Client", key="client_search",
                      placeholder="输入编码/名字/电话...")
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
            options = [f'{r["code"]} • {r["name"]} {r["phone"]}'.strip()
                       for _, r in f.iterrows()]
            code_map = {lab: lab.split("•")[0].strip() for lab in options}

        current_label = None
        for lab, cc in code_map.items():
            if cc == st.session_state.ticket_client_code:
                current_label = lab
                break
        if current_label is None:
            current_label = options[0]

        r1a, r1b = st.columns([1.4, 0.6], gap="small")
        with r1a:
            sel = st.selectbox(
                "", options=options,
                index=options.index(current_label) if current_label in options else 0,
                key="client_selectbox", label_visibility="collapsed")
            st.session_state.ticket_client_code = code_map.get(
                sel, st.session_state.ticket_client_code)
        with r1b:
            if st.button("Add Client", use_container_width=True):
                st.session_state._show_add_client = True

        if st.session_state._show_add_client:
            with st.expander("Add Client", expanded=True):
                nm = st.text_input("Name", key="new_client_name")
                ph = st.text_input("Phone (optional)", key="new_client_phone")
                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button("Create", type="primary", use_container_width=True):
                        if nm.strip() == "" and ph.strip() == "":
                            st.warning("Please enter name or phone.")
                        else:
                            code = save_customer(nm, ph)
                            st.success(f"Created: {code}")
                            st.session_state.ticket_client_code = code
                            st.session_state._show_add_client = False
                            st.session_state.client_search = ""
                            st.rerun()
                with ac2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state._show_add_client = False
                        st.rerun()

        # ---------- Receipt table ----------
        st.markdown(
            f"<div style='line-height:1.3;margin:4px 0;'>"
            f"<span style='color:#6b7280;font-size:0.8em;'>Subtotal:</span> "
            f"<span style='font-size:1.2rem;font-weight:950;'>${current_subtotal():.2f}</span>"
            f"</div>",
            unsafe_allow_html=True)

        df = recompute_receipt_df(st.session_state.receipt_df)
        if "Del" not in df.columns:
            df.insert(0, "Del", False)
            st.session_state.receipt_df = df

        if df.empty:
            st.info("No items yet.")
        else:
            # Bug 3 fix: version counter in key forces fresh widget on data change
            ver = st.session_state.get("_receipt_edit_ver", 0)
            edited = st.data_editor(
                df, use_container_width=True, height=160, hide_index=True,
                key=f"receipt_data_editor_{ver}",
                column_config={
                    "Del": st.column_config.CheckboxColumn("删", help="勾选删除"),
                    "material": st.column_config.TextColumn("material", disabled=True),
                    "unit_price": st.column_config.NumberColumn("price", step=0.01, format="%.2f"),
                    "gross": st.column_config.NumberColumn("gross", step=1.0, format="%.0f"),
                    "tare": st.column_config.NumberColumn("tare", step=1.0, format="%.0f"),
                    "net": st.column_config.NumberColumn("net", disabled=True, format="%.0f"),
                    "total": st.column_config.NumberColumn("total", disabled=True, format="%.2f"),
                })
            edited = recompute_receipt_df(edited)
            if edited["Del"].any():
                keep = edited[edited["Del"] == False].drop(columns=["Del"])
                keep.insert(0, "Del", False)
                st.session_state.receipt_df = recompute_receipt_df(keep)
                bump_receipt_ver()
                st.rerun()
            st.session_state.receipt_df = edited
            if not edited[["unit_price", "gross", "tare"]].equals(
                    df[["unit_price", "gross", "tare"]]):
                st.rerun()

        rcA, rcB = st.columns(2)
        with rcA:
            if st.button("Clear Receipt", use_container_width=True):
                st.session_state.receipt_df = pd.DataFrame(
                    columns=["Del", "material", "unit_price", "gross", "tare", "net", "total"])
                bump_receipt_ver()
                for k in ("_pending_preview_b64", "_pending_preview_token", "_print_diag"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
        with rcB:
            if st.button("Print / Save Receipt", type="primary", use_container_width=True):
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

                line_rows = []
                for r in df2.itertuples(index=False):
                    line_rows.append((
                        r.material, float(r.unit_price), float(r.gross),
                        float(r.tare), float(r.net), float(r.total)))
                finalize_ticket(
                    issue_time, operator_name or operator_email, "Print", wcode,
                    client_code, client_name, float(subtotal), float(rounding),
                    line_rows)

                receipt_html = build_receipt_html_for_print(
                    company_name="YGMETAL", ticket_number=str(wcode),
                    email="test@ygmetal.com", issue_time=issue_time,
                    cashier=(operator_name or operator_email),
                    client_name=client_name, lines_df=df2,
                    total_amount=float(rounding),
                    rounding_amount=float(rounding - subtotal),
                    balance_amount=float(rounding))
                if not receipt_html or len(receipt_html) < 200:
                    st.error("receipt_html empty/too short")
                    st.stop()

                st.session_state._pending_print_html = receipt_html
                st.session_state._pending_print_wcode = wcode
                st.session_state.receipt_df = pd.DataFrame(
                    columns=["Del", "material", "unit_price", "gross", "tare", "net", "total"])
                bump_receipt_ver()
                st.rerun()

        # Pending print handler
        if st.session_state.get("_pending_print_html"):
            open_print_window(st.session_state._pending_print_html)
            _wcode = st.session_state.get("_pending_print_wcode", "")
            st.success(f"Saved. Withdraw code: {_wcode}")
            del st.session_state["_pending_print_html"]
            if "_pending_print_wcode" in st.session_state:
                del st.session_state["_pending_print_wcode"]

        st.markdown("---")

        # ---------- Material + Input area ----------
        st.markdown("**Material :**")
        if st.session_state.picked_material_name:
            st.success(st.session_state.picked_material_name)
        else:
            st.info("Pick a material on the left.")

        allow_price_edit = (get_setting("unit_price_adjustment_permitted", "Yes") == "Yes")

        # Hidden switch buttons (for JS enter_workflow)
        _sw_hide, _sw_main = st.columns([0.001, 99])
        with _sw_hide:
            st.markdown('<div id="switch-btns-marker"></div>', unsafe_allow_html=True)
            _to_tare = st.button("→Tare", key="switch_to_tare")
            _to_gross = st.button("→Gross", key="switch_to_gross")
            _to_tare_key = st.button("TareKey", key="switch_to_tare_key")
            _to_uprice = st.button("UPriceKey", key="switch_to_uprice")
        if _to_uprice:
            st.session_state.key_target = "unit_price"
        if _to_gross:
            st.session_state.key_target = "gross"
        if _to_tare:
            st.session_state.key_target = "tare"
            st.session_state.focus_request = "tare"
            st.session_state._entered_tare_for_line = True
            if (st.session_state.get("tare_input") or "") == "0":
                st.session_state.tare_input = ""
            transition_step(STEP_TARE_INPUT)
            unlock_transition()
        if _to_tare_key:
            st.session_state.key_target = "tare"
            st.session_state._entered_tare_for_line = True

        if not st.session_state.get("picked_material_id"):
            st.session_state.unit_price_input = ""

        # Pre-widget field reset (BEFORE widgets render)
        if st.session_state._reset_line_fields:
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._reset_line_fields = False
            st.session_state._entered_tare_for_line = False
        if st.session_state.get("_clear_all_line_fields"):
            st.session_state.unit_price_input = ""
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._clear_all_line_fields = False
        if not st.session_state.get("_entered_tare_for_line"):
            st.session_state.tare_input = ""

        # Input widgets
        cA, cB, cC = st.columns([1.0, 1.0, 1.0], gap="small")
        with cA:
            unit_price_val = ((st.session_state.get("unit_price_input") or "")
                              if st.session_state.get("picked_material_id") else "")
            st.text_input("Unit Price ($)", value=unit_price_val,
                          disabled=not allow_price_edit, key="unit_price_input")
        with cB:
            st.text_input("Gross (LB)",
                          value=st.session_state.get("gross_input", ""),
                          key="gross_input")
        with cC:
            # Bug 2 fix: SINGLE key "tare_input" always — just toggle disabled.
            # This prevents Streamlit from restoring stale cached values on key swap.
            tare_enabled = bool(st.session_state.get("_entered_tare_for_line"))
            st.text_input("Tare (LB)",
                          value=st.session_state.get("tare_input", ""),
                          disabled=not tare_enabled,
                          key="tare_input")

        tare_for_calc = st.session_state.get("tare_input", "") if tare_enabled else ""
        net, total = calc_line(
            st.session_state.get("unit_price_input", ""),
            st.session_state.get("gross_input", ""),
            tare_for_calc)
        st.markdown(
            f"**Net** :red[{net:.2f}] LB &nbsp;&nbsp; **Total Amount** :red[${total:.2f}]")

        b1, b2 = st.columns(2, gap="small")
        with b1:
            clear_click = st.button("Clear", use_container_width=True)
        with b2:
            confirm_click = st.button("Confirm (Enter)", use_container_width=True,
                                      type="primary")

        if clear_click:
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state._clear_all_line_fields = True
            st.session_state._reset_line_fields = True
            st.session_state._entered_tare_for_line = False
            st.session_state.focus_request = "gross"
            st.session_state.key_target = "gross"
            st.session_state._keypad_pending = None
            st.session_state.active_step = STEP_SELECT_ITEM
            st.rerun()

        if confirm_click:
            sg = (st.session_state.get("gross_input") or "").strip()
            stare = (st.session_state.get("tare_input") or "").strip()
            sup = (st.session_state.get("unit_price_input") or "").strip()
            add_line_to_receipt(override_gross=sg, override_tare=stare,
                                override_unit_price=sup)
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state._reset_line_fields = True
            st.session_state._entered_tare_for_line = False
            st.session_state.key_target = "gross"
            st.session_state._keypad_pending = None
            record_action()
            st.rerun()

        # Keypad
        st.markdown("**Keypad**")
        render_keypad()
        render_enter_workflow_js()

        if st.session_state.focus_request in ("gross", "tare"):
            st.session_state._focus_counter = st.session_state.get("_focus_counter", 0) + 1
            focus_js(st.session_state.focus_request, st.session_state._focus_counter)
            st.session_state.focus_request = None
