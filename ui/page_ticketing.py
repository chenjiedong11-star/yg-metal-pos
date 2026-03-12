"""
Ticketing page — original ScrapGoGo three-column layout restored.
  Left : Receipt Preview Area (client, subtotal, receipt table, print)
  Mid  : Material List Area (categories + product grid + cameras)
  Right: Receiving Area (client search, material, inputs, keypad)
"""

import os
import time
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from core.utils import calc_line, recompute_receipt_df, current_subtotal

_CAM_BRIDGE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "components", "cam_bridge")
_cam_bridge_fn = components.declare_component("pos_cam_bridge", path=_CAM_BRIDGE_DIR)
from core.state import (
    record_action, bump_receipt_ver,
    is_transition_locked, transition_step, unlock_transition,
    STEP_SELECT_ITEM, STEP_GROSS_INPUT, STEP_TARE_INPUT, STEP_CONFIRM, STEP_DONE,
)
from db.repo_customers import get_clients, save_customer, get_client_tier
from db.repo_products import (
    get_categories, get_materials, get_operators,
    get_setting, gen_withdraw_code,
    get_tier_adjusted_price,
)
from services.ticketing_service import (
    add_line_to_receipt, build_receipt_html_for_print,
)
from db.repo_ticketing import (
    finalize_ticket,
    create_draft_receipt,
    insert_receipt_line,
    insert_line_photos,
    update_receipt_on_finalize,
    delete_receipt_line,
    delete_draft_receipt,
    get_latest_receipt_line_ids,
    get_photo_verification_for_line,
)
from core.config import DB_PATH
from components.navigation import topbar
from components.printer import open_print_window
from components.keypad import render_keypad, render_enter_workflow_js, focus_js


SAFE_TEST_NO_CAMERA = False  # Set True to bypass camera/photo pipeline for testing


def ticketing_page():
    topbar("开票")

    clients = get_clients()
    operators = get_operators()
    cats = get_categories()
    mats = get_materials()

    # ===================== THREE-COLUMN LAYOUT (original) =====================
    left, mid, right = st.columns([1.25, 2.1, 1.25], gap="medium")

    # ================================================================
    # LEFT COLUMN: Receipt Preview Area
    # ================================================================
    with left:
        st.markdown("### Receipt Preview Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        if st.session_state.get("_pending_print_html"):
            open_print_window(st.session_state._pending_print_html)
            _wcode = st.session_state.get("_pending_print_wcode", "")
            st.success(f"Saved. Withdraw code: {_wcode}")
            del st.session_state["_pending_print_html"]
            if "_pending_print_wcode" in st.session_state:
                del st.session_state["_pending_print_wcode"]

        csel = clients[clients["code"] == st.session_state.ticket_client_code]
        clabel = "(未选择)"
        tier_badge = ""
        if len(csel) > 0:
            clabel = f'{csel.iloc[0]["name"]}'.strip()
            ct = int(csel.iloc[0].get("tier_level", 0) or 0)
            if ct > 0:
                tier_badge = f" <span style='background:#f59e0b;color:#fff;padding:1px 6px;border-radius:8px;font-size:0.7em;'>Tier {ct}</span>"

        st.markdown(
            f"<div style='line-height:1.4;margin-bottom:8px;'>"
            f"<span style='color:#6b7280;font-size:0.8em;'>Client:</span><br>"
            f"<span style='font-weight:900;'>{clabel}{tier_badge}</span><br>"
            f"<span style='color:#6b7280;font-size:0.8em;'>Subtotal:</span><br>"
            f"<span style='font-size:1.3rem;font-weight:950;'>${current_subtotal():.2f}</span>"
            f"</div>",
            unsafe_allow_html=True)

        df = recompute_receipt_df(st.session_state.receipt_df)
        if "Del" not in df.columns:
            df.insert(0, "Del", False)
            st.session_state.receipt_df = df

        if df.empty:
            st.info("No items yet.")
        else:
            ver = st.session_state.get("_receipt_edit_ver", 0)
            edited = st.data_editor(
                df, use_container_width=True, height=180, hide_index=True,
                key=f"receipt_data_editor_{ver}",
                column_config={
                    "Del": st.column_config.CheckboxColumn("删", help="勾选即删除此行"),
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
                line_ids = st.session_state.get("_receipt_line_ids") or []
                for i in range(len(edited)):
                    if edited.iloc[i]["Del"] and i < len(line_ids):
                        delete_receipt_line(line_ids[i])
                kept_idx = [i for i in range(len(edited)) if not edited.iloc[i]["Del"]]
                st.session_state._receipt_line_ids = [line_ids[i] for i in kept_idx if i < len(line_ids)]
                st.session_state.receipt_df = recompute_receipt_df(keep)
                rlp = st.session_state.get("_receipt_line_photos") or []
                st.session_state._receipt_line_photos = [rlp[i] for i in kept_idx if i < len(rlp)]
                bump_receipt_ver()
                st.rerun()
            st.session_state.receipt_df = edited
            if not edited[["unit_price", "gross", "tare"]].equals(
                    df[["unit_price", "gross", "tare"]]):
                st.rerun()

        colA, colB = st.columns(2)
        with colA:
            if st.button("Clear Receipt", use_container_width=True):
                draft_id = st.session_state.get("_draft_receipt_id")
                if draft_id is not None:
                    delete_draft_receipt(draft_id)
                    st.session_state._draft_receipt_id = None
                    st.session_state._receipt_line_ids = []
                st.session_state.receipt_df = pd.DataFrame(
                    columns=["Del", "material", "unit_price", "gross", "tare", "net", "total"])
                st.session_state._receipt_line_photos = []
                st.session_state["pending_line_photos"] = {}
                st.session_state["pending_photo_ts"] = None
                bump_receipt_ver()
                for k in ("_pending_preview_b64", "_pending_preview_token", "_print_diag"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
        with colB:
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

                draft_id = st.session_state.get("_draft_receipt_id")
                if draft_id is not None:
                    update_receipt_on_finalize(
                        draft_id, issue_time, operator_name or operator_email,
                        "Print", wcode, client_code, client_name,
                        float(subtotal), float(rounding),
                    )
                    rid = draft_id
                    st.session_state._draft_receipt_id = None
                    st.session_state._receipt_line_ids = []
                else:
                    line_rows = []
                    for r in df2.itertuples(index=False):
                        line_rows.append((
                            r.material, float(r.unit_price), float(r.gross),
                            float(r.tare), float(r.net), float(r.total)))
                    lp_per_line = st.session_state.get("_receipt_line_photos") or []
                    line_photos = []
                    for i in range(len(line_rows)):
                        line_photos.append(lp_per_line[i] if i < len(lp_per_line) else None)
                    rid, verification = finalize_ticket(
                        issue_time, operator_name or operator_email, "Print", wcode,
                        client_code, client_name, float(subtotal), float(rounding),
                        line_rows, line_photos=line_photos)
                    st.session_state["_photo_diagnostic_saved"] = {
                        "receipt_id": rid,
                        "verification": verification,
                    }
                st.session_state._receipt_line_photos = []
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

        st.caption(f"print_debug_ts={st.session_state.get('_print_debug_ts')}")
        with st.expander("照片诊断", expanded=True):
            st.write("**DB_PATH** (写入/读取须一致):")
            st.code(os.path.abspath(DB_PATH), language=None)
            ppt = st.session_state.get("pending_photos_by_token") or {}
            tpt = st.session_state.get("pending_photo_ts_by_token") or {}
            cur_token = st.session_state.get("current_line_token")
            entry = ppt.get(cur_token) or {}
            cam1_b = entry.get(1) or b""
            cam2_b = entry.get(2) or b""
            pts = tpt.get(cur_token)
            meta = entry.get("meta") or {}
            st.write("**A. Gross Enter 拍照（按 token 绑定）**")
            st.write(f"token = {cur_token}")
            st.write(f"pending_photo_ts = {pts}")
            st.write(f"cam1: type={type(cam1_b).__name__}, len(cam1_bytes)={len(cam1_b)} (须>1000), brightness={(meta.get('cam1') or {}).get('brightness')}")
            st.write(f"cam2: type={type(cam2_b).__name__}, len(cam2_bytes)={len(cam2_b)}, brightness={(meta.get('cam2') or {}).get('brightness')}")
            cap = st.session_state.get("_photo_diagnostic_capture")
            if cap:
                st.caption(f"待提交 item 序号 = {cap.get('pending_item_index', '—')}")
            if st.button("Show Pending Photo Lens", key="show_pending_lens_btn"):
                plp2 = ppt.get(cur_token) or {}
                pts2 = tpt.get(cur_token)
                c1 = plp2.get(1) or b""
                c2 = plp2.get(2) or b""
                st.write(f"token = {cur_token}, pending_photo_ts = {pts2}")
                st.write(f"cam1_len = {len(c1)}, cam2_len = {len(c2)}")
                st.write(f"cam1 前10字节(hex) = {c1[:10].hex() if len(c1) >= 10 else c1.hex()}")
                st.write(f"cam2 前10字节(hex) = {c2[:10].hex() if len(c2) >= 10 else (c2.hex() if c2 else 'N/A')}")
            if st.button("Force Write Pending Photos to Latest Line (Debug)", key="force_write_pending_btn"):
                line_ids = get_latest_receipt_line_ids(1)
                plp3 = ppt.get(cur_token) or {}
                if not line_ids:
                    st.warning("无 receipt_lines。")
                elif not plp3:
                    st.warning("当前 token 无 pending 照片。")
                else:
                    photos_to_write = [(k, v) for k, v in plp3.items() if isinstance(v, bytes) and len(v) > 1000]
                    if not photos_to_write:
                        st.warning("无 len>1000 的 bytes。")
                    else:
                        try:
                            ver = insert_line_photos(line_ids[0], photos_to_write)
                            st.success(f"已写入 line_id={line_ids[0]}, photo_count={ver['photo_count']}, lengths={ver['lengths']}")
                        except Exception as e:
                            st.error(str(e))
            saved = st.session_state.get("_photo_diagnostic_saved")
            if saved:
                st.write("**B. Confirm 落库后**")
                st.write(f"receipt_id = {saved.get('receipt_id')}")
                if "confirm_line_id" in saved:
                    st.write(f"Confirm created line_id = {saved.get('confirm_line_id')}")
                if "photos_to_write_keys" in saved:
                    st.write(
                        f"Confirm photos_to_write keys = {saved.get('photos_to_write_keys')}, "
                        f"lens = {saved.get('photos_to_write_lens')}"
                    )
                gv = saved.get("gross_val")
                tv = saved.get("tare_val")
                nv = saved.get("net_val")
                if gv is not None and nv is not None:
                    st.write(f"Gross={gv}, Tare={tv}, Net={nv}")
                for v in saved.get("verification", []):
                    st.write(
                        f"Verify DB for line_id={v['ticket_item_id']}: "
                        f"count={v['photo_count']} lengths={v['lengths']}"
                    )
            if st.button("Verify DB Photos for Latest Lines", key="verify_db_photos_btn"):
                line_ids = get_latest_receipt_line_ids(5)
                rows = [get_photo_verification_for_line(lid) for lid in line_ids]
                if rows:
                    vdf = pd.DataFrame(rows)
                    vdf = vdf.rename(columns={"line_id": "id", "photo_count": "count", "lengths": "lengths"})
                    st.dataframe(vdf, use_container_width=True, hide_index=True)
                else:
                    st.caption("无最近 5 条 receipt_lines。")
            if not ppt and not saved:
                st.caption("Gross→Enter 拍照后此处显示 A；Confirm 后显示 B。")
        st.markdown("</div>", unsafe_allow_html=True)

    # ================================================================
    # MIDDLE COLUMN: Material List Area
    # ================================================================
    with mid:
        st.markdown("### Material List Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        catcol, prodcol = st.columns([0.35, 1.65], gap="medium")

        with catcol:
            for cname in cats["name"].tolist():
                is_active = (st.session_state.active_cat == cname)
                btn_type = "primary" if is_active else "secondary"
                if st.button(cname, type=btn_type, use_container_width=True,
                             key=f"cat_{cname}"):
                    st.session_state.active_cat = cname
                    st.session_state["confirm_request"] = False
                    st.session_state["_confirm_from_tare"] = False
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
                            # 换 material 不算 confirm，清掉所有 confirm 相关 flag 再 rerun
                            st.session_state["confirm_request"] = False
                            st.session_state["_confirm_from_tare"] = False
                            st.session_state["_confirm_from_gross"] = False
                            st.session_state["_capture_pending"] = False
                            import uuid
                            token = uuid.uuid4().hex
                            st.session_state["current_line_token"] = token
                            ss_p = st.session_state.get("pending_photos_by_token", {})
                            ss_ts = st.session_state.get("pending_photo_ts_by_token", {})
                            ss_p[token] = ss_p.get(token, {"meta": {}})
                            ss_ts[token] = ss_ts.get(token, None)
                            st.session_state["pending_photos_by_token"] = ss_p
                            st.session_state["pending_photo_ts_by_token"] = ss_ts
                            st.session_state.picked_material_id = int(row.id)
                            st.session_state.picked_material_name = row.name
                            # Tier pricing: adjust unit price based on client's tier
                            client_tier = st.session_state.get("_client_tier_level", 0)
                            tier_price = get_tier_adjusted_price(int(row.id), client_tier) if client_tier else None
                            effective_price = tier_price if tier_price is not None else (row.unit_price if row.unit_price is not None else "")
                            st.session_state.unit_price_input = str(effective_price)
                            st.session_state._reset_line_fields = True
                            st.session_state.focus_request = "gross"
                            st.session_state.key_target = "gross"
                            transition_step(STEP_GROSS_INPUT)
                            unlock_transition()
                            st.rerun()

        st.markdown("<hr style='margin:0.3rem 0;border:none;border-top:1px solid #e5e7eb;'>",
                    unsafe_allow_html=True)
        st.markdown("<div style='height:200px;'></div>", unsafe_allow_html=True)
        st.caption("摄像头")
        # 稳定 key，不放在条件分支内；通过 capture_token 触发截帧，组件内保持直播不中断
        capture_token = st.session_state.get("capture_token", 0)
        cam_bridge_val = ""
        try:
            cam_bridge_val = _cam_bridge_fn(key="cam_bridge_main", capture_token=capture_token, default="")
        except Exception:
            cam_bridge_val = ""
        if cam_bridge_val and isinstance(cam_bridge_val, str) and cam_bridge_val.strip():
            import json
            import base64 as b64mod
            try:
                jdata = json.loads(cam_bridge_val)
                if jdata.get("ok"):
                    cam1 = jdata.get("cam1") or {}
                    cam2 = jdata.get("cam2") or {}
                    photo_ts = cam1.get("ts") or cam2.get("ts") or 0
                    last_ts = st.session_state.get("_last_processed_photo_ts", 0)
                    if photo_ts and photo_ts > last_ts:
                        st.session_state["_last_processed_photo_ts"] = photo_ts
                        pending = {}
                        meta = {}
                        if isinstance(cam1, dict):
                            b64str1 = cam1.get("data", "")
                            if b64str1 and b64str1.startswith("data:image"):
                                raw1 = b64str1.split(",", 1)[1]
                                img1_bytes = b64mod.b64decode(raw1)
                                if isinstance(img1_bytes, bytes) and len(img1_bytes) > 500:
                                    pending[1] = img1_bytes
                                    meta["cam1"] = {k: cam1.get(k) for k in ("brightness", "w", "h", "ts")}
                        if isinstance(cam2, dict):
                            b64str2 = cam2.get("data", "")
                            if b64str2 and b64str2.startswith("data:image"):
                                raw2 = b64str2.split(",", 1)[1]
                                img2_bytes = b64mod.b64decode(raw2)
                                if isinstance(img2_bytes, bytes) and len(img2_bytes) > 500:
                                    pending[2] = img2_bytes
                                    meta["cam2"] = {k: cam2.get(k) for k in ("brightness", "w", "h", "ts")}
                        if pending:
                            token = st.session_state.get("current_line_token")
                            if not token:
                                import uuid
                                token = uuid.uuid4().hex
                                st.session_state["current_line_token"] = token
                            ss_p = st.session_state.get("pending_photos_by_token", {})
                            ss_ts = st.session_state.get("pending_photo_ts_by_token", {})
                            ss_p[token] = {**pending, "meta": meta}
                            ss_ts[token] = time.time()
                            st.session_state["pending_photos_by_token"] = ss_p
                            st.session_state["pending_photo_ts_by_token"] = ss_ts
                            st.session_state._current_line_photos = [(k, v) for k, v in sorted(pending.items()) if isinstance(k, int)]
                            st.session_state.pending_item_photos = st.session_state._current_line_photos
                            st.session_state._cam_data_saved = True
                            deferred_lid = st.session_state.get("_deferred_line_id_for_photo")
                            if deferred_lid:
                                deferred_photos = [(k, v) for k, v in sorted(pending.items()) if isinstance(k, int)]
                                if deferred_photos:
                                    insert_line_photos(deferred_lid, deferred_photos)
                                st.session_state["_deferred_line_id_for_photo"] = None
                            if st.session_state.get("confirm_after_capture"):
                                st.session_state["confirm_after_capture"] = False
                                st.session_state["confirm_request"] = True
            except Exception:
                pass
        st.markdown("</div>", unsafe_allow_html=True)

    # ================================================================
    # RIGHT COLUMN: Receiving Area
    # ================================================================
    with right:
        st.markdown("### Receiving Area")
        st.markdown('<div class="box">', unsafe_allow_html=True)

        st.text_input("Search Client (code / name / phone)",
                      key="client_search", placeholder="输入编码/名字/电话...")

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

        r1a, r1b = st.columns([1.35, 0.65], gap="small")
        with r1a:
            sel = st.selectbox(
                "", options=options,
                index=options.index(current_label) if current_label in options else 0,
                key="client_selectbox", label_visibility="collapsed")
            new_code = code_map.get(sel, st.session_state.ticket_client_code)
            if new_code != st.session_state.ticket_client_code:
                st.session_state.ticket_client_code = new_code
                st.session_state["_client_tier_level"] = get_client_tier(new_code)
            elif "_client_tier_level" not in st.session_state:
                st.session_state["_client_tier_level"] = get_client_tier(st.session_state.ticket_client_code)
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
                            code = save_customer(nm, ph)
                            st.success(f"Created client code: {code}")
                            st.session_state.ticket_client_code = code
                            st.session_state._show_add_client = False
                            st.session_state.client_search = ""
                            st.rerun()
                with c2:
                    if st.button("Cancel", use_container_width=True):
                        st.session_state._show_add_client = False
                        st.rerun()

        st.markdown("**Material :**")
        if st.session_state.picked_material_name:
            st.success(st.session_state.picked_material_name)
        else:
            st.info("Pick a material in the middle area.")

        _ct = st.session_state.get("_client_tier_level", 0)
        if _ct and _ct > 0:
            st.caption(f"当前客户 Tier 级别: **Tier {_ct}** (价格已自动调整)")

        allow_price_edit = (get_setting("unit_price_adjustment_permitted", "Yes") == "Yes")

        # Hidden switch buttons (clicked by JS enter_workflow)
        _sw_hide, _sw_main = st.columns([0.001, 99])
        with _sw_hide:
            st.markdown('<div id="switch-btns-marker"></div>', unsafe_allow_html=True)
            _to_tare = st.button("→Tare", key="switch_to_tare", help="Enter from Gross 时自动触发")
            _to_gross = st.button("→Gross", key="switch_to_gross", help="点击 Gross 时自动触发")
            _to_tare_key = st.button("TareKey", key="switch_to_tare_key",
                                     help="点击 Tare 时仅更新 key_target")
            _to_uprice = st.button("UPriceKey", key="switch_to_uprice",
                                   help="点击 Unit Price 时更新 key_target")
        if _to_uprice:
            st.session_state.key_target = "unit_price"
        if _to_gross:
            st.session_state.key_target = "gross"
            st.session_state._current_line_photos = None
            st.session_state.pending_item_photos = None
        if _to_tare:
            st.session_state._saved_gross_before_tare = st.session_state.get("gross_input", "") or ""
            st.session_state.key_target = "tare"
            st.session_state.focus_request = "tare"
            st.session_state._entered_tare_for_line = True
            if not SAFE_TEST_NO_CAMERA:
                st.session_state["capture_token"] = st.session_state.get("capture_token", 0) + 1
                st.session_state._cam_data_saved = False
                st.session_state["_capture_pending"] = True
            if (st.session_state.get("tare_input") or "") == "0":
                st.session_state.tare_input = ""
            transition_step(STEP_TARE_INPUT)
            unlock_transition()
            st.rerun()
        if _to_tare_key:
            st.session_state.key_target = "tare"
            st.session_state._entered_tare_for_line = True

        # 无 material 时默认清空 unit price，但点击 Clear 时保留不清（见下方 _keep_unit_price_after_clear）
        if not st.session_state.get("picked_material_id") and not st.session_state.get("_keep_unit_price_after_clear"):
            st.session_state.unit_price_input = ""
        if st.session_state.get("_keep_unit_price_after_clear"):
            st.session_state["_keep_unit_price_after_clear"] = False

        # Pre-widget field reset
        _saved_gross = st.session_state.get("_saved_gross_before_tare", "")
        if st.session_state._reset_line_fields:
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._reset_line_fields = False
            st.session_state._entered_tare_for_line = False
            st.session_state["_line_confirmed_once"] = False
            st.session_state["_capture_pending"] = False
            st.session_state.pop("_saved_gross_before_tare", None)
        if st.session_state.get("_clear_all_line_fields"):
            # 只清 Gross/Tare 等，保留 Unit Price 不清 0
            st.session_state.gross_input = ""
            st.session_state.tare_input = ""
            st.session_state._clear_all_line_fields = False
            st.session_state.pop("_saved_gross_before_tare", None)
        if not st.session_state.get("_entered_tare_for_line"):
            st.session_state.tare_input = ""
        if st.session_state.get("_entered_tare_for_line") and _saved_gross and not (st.session_state.get("gross_input") or "").strip():
            st.session_state.gross_input = _saved_gross
        # 显示上优先用已保存的毛重，避免 Enter 过快时临时多出的数字干扰
        _display_gross = (_saved_gross or st.session_state.get("gross_input") or "").strip()

        # ════════════════════════════════════════════════════════
        # SAFE TEST MODE indicator
        # ════════════════════════════════════════════════════════
        if SAFE_TEST_NO_CAMERA:
            st.info("🔧 SAFE_TEST_NO_CAMERA = True (camera/photo bypassed)")

        # ── confirm_current_line ──
        def confirm_current_line(source):
            st.session_state["last_confirm_source"] = source
            gross_raw = (st.session_state.get("gross_input") or "").strip()
            tare_raw  = (st.session_state.get("tare_input") or "").strip()
            saved_gross = (st.session_state.get("_saved_gross_before_tare") or "").strip()
            sg = gross_raw or saved_gross
            if not sg:
                st.warning("Gross is required.")
                return
            sup        = (st.session_state.get("unit_price_input") or "").strip()
            mat_name   = st.session_state.get("picked_material_name") or ""
            unit_price = float(sup or 0)
            gross      = float(sg or 0)
            tare       = float(tare_raw) if tare_raw not in (None, "", " ") else 0.0
            net        = gross - tare
            total      = float(round(net * unit_price, 2))
            if not st.session_state.get("_draft_receipt_id"):
                rid = create_draft_receipt()
                st.session_state._draft_receipt_id = rid
                st.session_state._receipt_line_ids = []
            receipt_id = st.session_state._draft_receipt_id
            line_id = insert_receipt_line(receipt_id, mat_name, unit_price, gross, tare, net, total)
            print(f"[CONFIRM] source={source} receipt_id={receipt_id} line_id={line_id}")

            if not SAFE_TEST_NO_CAMERA:
                ppt   = st.session_state.get("pending_photos_by_token") or {}
                tpt   = st.session_state.get("pending_photo_ts_by_token") or {}
                token = st.session_state.get("current_line_token")
                entry = ppt.get(token) or {}
                photos = [(k, v) for k, v in entry.items()
                          if isinstance(k, int) and isinstance(v, bytes) and len(v) > 1000]
                if not photos:
                    st.session_state["capture_token"] = st.session_state.get("capture_token", 0) + 1
                    st.session_state["_deferred_line_id_for_photo"] = line_id
                else:
                    insert_line_photos(line_id, photos)
                if token and token in ppt: del ppt[token]
                if token and token in tpt: del tpt[token]
                st.session_state["pending_photos_by_token"] = ppt
                st.session_state["pending_photo_ts_by_token"] = tpt
                st.session_state["current_line_token"] = None

            st.session_state._receipt_line_ids = st.session_state.get("_receipt_line_ids", []) + [line_id]
            add_line_to_receipt(override_gross=sg, override_tare=tare_raw, override_unit_price=sup)
            st.session_state._current_line_photos = None
            st.session_state.pending_item_photos = None
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state["gross_input"] = ""
            st.session_state["tare_input"] = ""
            st.session_state._reset_line_fields = True
            st.session_state._entered_tare_for_line = False
            st.session_state.pop("_saved_gross_before_tare", None)
            st.session_state.key_target = "gross"
            st.session_state.focus_request = "gross"
            st.session_state._keypad_pending = None
            st.session_state["_line_confirmed_once"] = True
            st.session_state["_capture_pending"] = False
            record_action()

        # ── st.form: Enter in ANY input = submit = confirm ──
        st.markdown('<div id="scrap-gross-tare-marker" style="display:none"></div>',
                    unsafe_allow_html=True)

        with st.form("line_form", clear_on_submit=False):
            cA, cB, cC = st.columns([1.0, 1.0, 1.0], gap="small")
            with cA:
                unit_price_val = st.session_state.get("unit_price_input") or ""
                st.text_input("Unit Price ($)", value=unit_price_val,
                              disabled=not allow_price_edit, key="unit_price_input")
            with cB:
                st.text_input("Gross (LB)", value=_display_gross, key="gross_input")
            with cC:
                tare_val = st.session_state.get("tare_input", "") or ""
                st.text_input("Tare (LB)", value=tare_val, key="tare_input", placeholder="0")

            _gfc = (st.session_state.get("_saved_gross_before_tare")
                    or st.session_state.get("gross_input") or "").strip()
            _tfc = st.session_state.get("tare_input", "")
            net, total = calc_line(st.session_state.get("unit_price_input", ""), _gfc, _tfc)
            st.markdown(f"**Net** :red[{net:.2f}] LB &nbsp;&nbsp; **Total Amount** :red[${total:.2f}]")

            confirm_submit = st.form_submit_button(
                "Confirm Line (Enter)", type="primary", use_container_width=True)

        # Clear button OUTSIDE form (does not trigger confirm)
        clear_click = st.button("Clear", use_container_width=True)

        # Debug
        st.caption(f"SAFE_TEST_NO_CAMERA={SAFE_TEST_NO_CAMERA}")
        st.caption(f"last_confirm_source={st.session_state.get('last_confirm_source')}")
        st.caption(f"gross_raw='{(st.session_state.get('gross_input') or '')}' "
                   f"tare_raw='{(st.session_state.get('tare_input') or '')}'")

        # ── Handle form confirm ──
        if confirm_submit:
            confirm_current_line("form_submit")
            st.rerun()

        # ── Handle Clear ──
        if clear_click:
            st.session_state["confirm_request"] = False
            st.session_state["_confirm_from_tare"] = False
            st.session_state["_capture_pending"] = False
            st.session_state["_line_confirmed_once"] = False
            st.session_state.picked_material_id = None
            st.session_state.picked_material_name = ""
            st.session_state._clear_all_line_fields = True
            st.session_state._reset_line_fields = True
            st.session_state["_keep_unit_price_after_clear"] = True
            st.session_state._entered_tare_for_line = False
            st.session_state._current_line_photos = None
            st.session_state.pending_item_photos = None
            st.session_state.focus_request = "gross"
            st.session_state.key_target = "gross"
            st.session_state._keypad_pending = None
            st.session_state.active_step = STEP_SELECT_ITEM
            st.session_state.pop("_saved_gross_before_tare", None)
            st.rerun()

        # Focus helper
        if st.session_state.get("focus_request") == "tare" and st.session_state.get("_select_tare_on_focus"):
            st.session_state["_select_tare_on_focus"] = False
            components.html("""<script>(function(){try{
              var labels=Array.from(parent.document.querySelectorAll('label'));
              var t=labels.find(function(l){return(l.innerText||'').trim()==='Tare (LB)';});
              if(!t)return;var r=t.closest('div');if(!r)return;
              var inp=r.querySelector('input');if(!inp)return;
              setTimeout(function(){inp.focus();inp.select();},50);
            }catch(e){}})();</script>""", height=0)


        # Keypad
        st.markdown("**Keypad**")
        render_keypad()
        render_enter_workflow_js()

        # 安装一次全局监听：当 Tare 值是 "0" 且获得焦点时，自动全选，方便用户直接覆盖
        components.html("""
        <script>
        (function(){
          try {
            if (window.__tareSelectInstalled) return;
            window.__tareSelectInstalled = true;
            parent.document.addEventListener('focusin', (e) => {
              const el = e.target;
              if (!el || el.tagName !== 'INPUT') return;
              const wrap = el.closest('div');
              if (!wrap) return;
              const label = wrap.querySelector('label');
              if (!label) return;
              if ((label.innerText || '').trim() !== 'Tare (LB)') return;
              if ((el.value || '').trim() === '0') {
                setTimeout(() => el.select(), 0);
              }
            }, true);
          } catch (e) {
            console.warn('tare-focus-listener error', e);
          }
        })();
        </script>
        """, height=0)

        if st.session_state.focus_request in ("gross", "tare"):
            st.session_state._focus_counter = st.session_state.get("_focus_counter", 0) + 1
            focus_js(st.session_state.focus_request, st.session_state._focus_counter)
            st.session_state.focus_request = None

        st.markdown("</div>", unsafe_allow_html=True)
