"""
Pure-Python helper functions — no DB, no Streamlit widgets.
Only streamlit.session_state is accessed (read-only) for current_subtotal().
"""

import pandas as pd


def calc_line(unit_price, gross, tare):
    p = float(unit_price or 0)
    g = float(gross or 0)
    t = float(tare or 0)
    net = max(0.0, g - t)
    total = net * p
    return net, total


def recompute_receipt_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ["unit_price", "gross", "tare"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["net"] = (out["gross"] - out["tare"]).clip(lower=0.0)
    out["total"] = (out["net"] * out["unit_price"]).round(2)
    if "Del" in out.columns:
        out["Del"] = out["Del"].fillna(False).astype(bool)
    out["material"] = out["material"].fillna("").astype(str)
    return out


def current_subtotal() -> float:
    import streamlit as st
    df = st.session_state.receipt_df
    if df.empty:
        return 0.0
    df = recompute_receipt_df(df)
    return float(df["total"].sum())


def rpad(s, w):
    return str(s)[:w].ljust(w)


def rjust(s, w):
    return str(s).rjust(w)


def sanitize_style_block(style_content: str) -> str:
    """Remove stray Chinese comments outside CSS comment syntax."""
    lines = []
    for line in style_content.splitlines():
        s = line.rstrip()
        if ";" in s:
            idx = s.rfind(";")
            after = s[idx + 1:].strip()
            if after:
                has_chinese = any("\u4e00" <= c <= "\u9fff" for c in after)
                only_braces_space = all(c in "} \t" for c in after)
                is_comment = after.strip().startswith("*/") or after.strip().startswith("/*")
                if has_chinese or (not only_braces_space and not is_comment):
                    s = s[:idx + 1]
        lines.append(s)
    return "\n".join(lines)
