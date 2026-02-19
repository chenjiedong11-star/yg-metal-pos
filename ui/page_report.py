"""
Report page — currently a thin wrapper.
Report pages are rendered inside manage_page via the menu system.
This module exists as an extension point for future standalone report pages.
"""

import streamlit as st

from services.report_service import (
    get_daily_summary_df, get_monthly_summary_df, get_annual_summary_df,
)


def report_overview():
    """Quick summary view (placeholder for future standalone report page)."""
    st.subheader("Report Overview")
    st.info("Reports are available in the 管理 (Manage) tab.")
