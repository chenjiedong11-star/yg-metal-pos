"""
Session-state initialisation and Phase-2 ticketing state machine.
Single source of truth for ALL session_state keys.
"""

import time
import streamlit as st
import pandas as pd

from core.config import DEBOUNCE_MS

# ---------------------------------------------------------------------------
# Phase 2 — Ticketing step definitions
# ---------------------------------------------------------------------------
STEP_SELECT_ITEM = "SELECT_ITEM"
STEP_GROSS_INPUT = "GROSS_INPUT"
STEP_TARE_INPUT = "TARE_INPUT"
STEP_CONFIRM = "CONFIRM"
STEP_DONE = "DONE"


def ss_init(default_operator_email: str = "admin@youli-trade.com"):
    """Idempotent: only writes keys that do not yet exist."""
    defaults = {
        "top_nav": "开票",
        "manage_page": "月票据汇总信息查询",
        "ticket_client_code": "000001",
        "ticket_operator": default_operator_email,
        "active_cat": "Copper",
        "picked_material_id": None,
        "picked_material_name": "",
        "unit_price": "",
        "client_search": "",
        "_show_add_client": False,
        "receipt_df": pd.DataFrame(columns=[
            "Del", "material", "unit_price", "gross", "tare", "net", "total"
        ]),
        "focus_request": None,
        "_keypad_pending": None,
        "key_target": "gross",
        "_reset_line_fields": False,
        "_form_reset_key": 0,
        "_entered_tare_for_line": False,
        "gross_input": "",
        "tare_input": "",
        "unit_price_input": "",
        # Bug 3 fix: version counter so data_editor key changes on every add/delete
        "_receipt_edit_ver": 0,
        # Phase 2: ticketing state machine
        "active_step": STEP_SELECT_ITEM,
        "active_field": "gross",
        "input_buffer": "",
        "transition_lock": False,
        "last_action_ts": 0.0,
        "current_item_id": None,
        "gross_value": "",
        "tare_value": "",
        # Phase 5: stable navigation
        "current_page": "ticketing",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def bump_receipt_ver():
    """Increment receipt edit version so data_editor key changes → forces fresh render."""
    st.session_state._receipt_edit_ver = st.session_state.get("_receipt_edit_ver", 0) + 1


# ---------------------------------------------------------------------------
# Phase 2 — State-machine helpers
# ---------------------------------------------------------------------------

def transition_step(next_step: str):
    st.session_state.transition_lock = True
    st.session_state.active_step = next_step
    st.session_state.input_buffer = ""
    st.session_state.last_action_ts = time.time()


def unlock_transition():
    st.session_state.transition_lock = False


def is_transition_locked() -> bool:
    if not st.session_state.get("transition_lock", False):
        return False
    elapsed = time.time() - st.session_state.get("last_action_ts", 0)
    if elapsed > 2.0:
        st.session_state.transition_lock = False
        return False
    return True


# ---------------------------------------------------------------------------
# Phase 4 — Debounce helpers
# ---------------------------------------------------------------------------

def should_debounce() -> bool:
    elapsed_ms = (time.time() - st.session_state.get("last_action_ts", 0)) * 1000
    return elapsed_ms < DEBOUNCE_MS


def record_action():
    st.session_state.last_action_ts = time.time()


# ---------------------------------------------------------------------------
# Phase 5 — Navigation helpers
# ---------------------------------------------------------------------------

def navigate_to(page: str):
    st.session_state.current_page = "__switching__"
    st.session_state.current_page = page
