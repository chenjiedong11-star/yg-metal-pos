"""
Navigation chrome: CSS, top bar, page switching.
Phase 5: deterministic page transitions via current_page state.
B4: top menu does not overlap Ticketing/Manage content.
"""

import streamlit as st


def inject_css():
    """Global CSS — called once per render cycle."""
    st.markdown("""
    <style>
      html { font-size: 100%; }
      [data-testid="stAppViewContainer"],
      [data-testid="stAppViewContainer"] main {
        font-size: clamp(0.875rem, 1.5vw + 0.75rem, 1.25rem) !important;
      }
      div.block-container {
        padding-top: 0.3rem !important;
        padding-bottom: 0 !important;
        max-width: 100% !important;
      }

      /* B4: ensure Streamlit hamburger menu doesn't overlap page content */
      [data-testid="stHeader"] {
        height: auto !important;
        z-index: 999 !important;
      }
      [data-testid="stToolbar"] {
        position: relative !important;
      }

      .topbar{
        height: 2.2rem;
        background:#2f2f2f;
        color:#fff;
        display:flex;
        align-items:center;
        justify-content:space-between;
        padding:0 0.875rem;
        border-radius:0.375rem;
        margin-bottom:0.2rem;
        font-weight:800;
        font-size: 1em;
      }
      .box{
        border: none !important;
        border-radius: 0;
        padding: 0.25rem 0;
        background: transparent !important;
        font-size: 1em;
      }
      .subtle{ color:#6b7280; font-size: 0.875em; }

      h3 { font-size: 1rem !important; margin: 0 0 0.2rem 0 !important; }

      [data-testid="stDataFrame"] td,
      [data-testid="stDataFrame"] th {
        white-space: nowrap !important;
        font-size: inherit !important;
      }
      [data-testid="stDataFrame"] { font-size: 1em !important; }

      [data-testid="stVerticalBlock"] { gap: 0.3rem !important; }

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

      [data-testid="stButton"] button,
      [data-testid="stTextInput"] input,
      [data-testid="stSelectbox"] div,
      label, p, .stMarkdown {
        font-size: inherit !important;
      }
      [data-testid="column"] { font-size: inherit !important; }

      [data-testid="stButton"] button {
        border-radius: 0.25rem !important;
        box-shadow: none !important;
      }

      /* Hide switch buttons row via CSS (immediate, no JS delay) */
      [data-testid="stHorizontalBlock"]:not(:has([data-testid="stHorizontalBlock"])):has(#switch-btns-marker) {
        position: absolute !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        left: -9999px !important;
      }

      /* height=0 iframes should not produce spacing */
      [data-testid="stCustomComponentV1"] iframe[height="0"],
      [data-testid="stHtml"] iframe[height="0"] {
        display: block !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
      }
    </style>
    """, unsafe_allow_html=True)


def topbar(active: str):
    user = st.session_state.ticket_operator
    st.markdown(
        f"""
        <div class="topbar">
          <div>SCRAPGOGO • 开票端 • [Y&G METALS INC.]</div>
          <div>{active} &nbsp;&nbsp; {user}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def switch_page(page: str):
    """Phase 5 — force page switch even for same page."""
    st.session_state.current_page = "__switching__"
    st.session_state.current_page = page
    st.rerun()
