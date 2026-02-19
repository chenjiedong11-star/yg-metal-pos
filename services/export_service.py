"""
Excel / file export helpers.
"""

import io
import pandas as pd

from services.report_service import get_monthly_invoice_summary


def monthly_summary_export_bytes() -> bytes:
    df = get_monthly_invoice_summary()
    df["合计金额"] = df["合计金额"].apply(lambda x: round(float(x), 2))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Monthly Summary", index=False)
    buf.seek(0)
    return buf.getvalue()
