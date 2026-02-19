"""
SCRAPGOGO POS — thin entry point.

All logic is delegated to modules:
  core/     — config, session state, utilities
  db/       — schema, connection, repositories
  services/ — business rules
  ui/       — Streamlit page renderers
  components/ — reusable HTML/JS widgets
"""

import streamlit as st
import streamlit.components.v1 as components

from core.config import PRINT_PAGE_SCRIPT
from core.state import ss_init
from components.navigation import inject_css
from db.schema import init_db
from db.repo_products import get_default_operator_email
from db.repo_ticketing import get_preview_html, get_receipt_print_html
from services.ticketing_service import get_receipt_preview_html, wrap_receipt_for_preview
from ui.page_ticketing import ticketing_page
from ui.page_manage import manage_page


# ---------------------------------------------------------------------------
# URL-based special pages (print preview, direct print)
# ---------------------------------------------------------------------------

def _render_preview_page(preview_token: str):
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
    html_content = get_receipt_preview_html(rid)
    if not html_content:
        st.error("Receipt not found or invalid id.")
        if st.button("Close"):
            components.html("<script>window.close();</script>", height=0)
        return
    components.html(html_content, height=1200)


def _render_print_page(rid: int) -> None:
    st.markdown(
        '<style>[data-testid="stSidebar"]{display:none !important;} '
        '.main .block-container{padding-top:0.5rem !important;max-width:100% !important;}'
        '</style>',
        unsafe_allow_html=True,
    )
    html_content = get_receipt_print_html(rid)
    if not html_content or len(html_content) < 100:
        st.error("Print receipt not found or expired.")
        return
    idx = html_content.rfind("</body>")
    if idx >= 0:
        html_with_script = (html_content[:idx] + PRINT_PAGE_SCRIPT
                            + "\n</body>" + html_content[idx + 7:])
    else:
        html_with_script = html_content + PRINT_PAGE_SCRIPT
    components.html(html_with_script, height=900)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="SCRAPGOGO Clone • YG Metals",
        layout="wide",
        initial_sidebar_state="auto",
    )

    try:
        init_db()
    except Exception as e:
        st.error(f"数据库初始化失败: {e}")
        st.exception(e)
        return

    # --- URL parameter routing ---
    params = getattr(st, "query_params", None) or {}

    print_rid = params.get("rid") if params else None
    if isinstance(print_rid, list):
        print_rid = print_rid[0] if print_rid else None
    print_mode = params.get("print") in ("1", 1) and print_rid

    if print_mode:
        st.info("请从开票页点击 **Print / Save Receipt** 打开打印。")
        return

    preview_token = params.get("preview_token") if params else None
    preview_rid = params.get("preview_rid") if params else None
    if isinstance(preview_token, list):
        preview_token = preview_token[0] if preview_token else None
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

    # --- Normal app ---
    try:
        default_email = get_default_operator_email()
        ss_init(default_email)
    except Exception as e:
        st.error(f"会话初始化失败: {e}")
        st.exception(e)
        return

    inject_css()

    st.markdown(
        "**请选择：** 点击下方 **「开票」** 做前台收银开票，"
        "点击 **「管理」** 进入后台（月汇总、客户/操作员/物料等）。"
    )
    tab_open, tab_manage = st.tabs(["开票（前台）", "管理（后台）"])
    with tab_open:
        ticketing_page()
    with tab_manage:
        manage_page()


if __name__ == "__main__":
    import sys
    if "streamlit" in sys.modules:
        main()
    else:
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", __file__] + sys.argv[1:])
