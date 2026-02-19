"""
Repository — all ticket / receipt DB operations.
Phase 3: finalize_ticket() is fully atomic (single transaction).
"""

import uuid
from datetime import datetime

from db.connection import get_connection, qdf, qone


# ---------------------------------------------------------------------------
# Print-preview storage
# ---------------------------------------------------------------------------

def save_preview_html(html_content: str) -> str:
    token = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO print_previews(token, html, created_at) VALUES(?,?,?)",
            (token, html_content, datetime.now().isoformat()),
        )
    return token


def get_preview_html(token: str):
    row = qone("SELECT html FROM print_previews WHERE token = ?", (token,))
    return row["html"] if row else None


def save_receipt_print_html(html_content: str) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO receipt_print(html, created_at) VALUES(?,?)",
            (html_content, datetime.now().isoformat()),
        )
        return cur.lastrowid


def get_receipt_print_html(rid: int):
    row = qone("SELECT html FROM receipt_print WHERE id = ?", (rid,))
    return row["html"] if row else None


# ---------------------------------------------------------------------------
# Ticket CRUD
# ---------------------------------------------------------------------------

def get_receipt(receipt_id: int):
    return qone("SELECT * FROM receipts WHERE id = ?", (receipt_id,))


def get_receipt_lines(receipt_id: int):
    return qdf(
        "SELECT * FROM receipt_lines WHERE receipt_id = ? ORDER BY id",
        (receipt_id,),
    )


def finalize_ticket(issue_time, issued_by, method, wcode,
                    client_code, client_name, subtotal, rounding, line_rows):
    """
    Phase 3 — Atomic ticket creation.
    *line_rows* is a list of tuples:
        (material_name, unit_price, gross, tare, net, total)
    Returns the new receipt id.
    Either everything commits or nothing does.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO receipts(issue_time, issued_by, ticketing_method,
                                 withdraw_code, client_code, client_name,
                                 subtotal, rounding_amount, voided, withdrawn)
            VALUES(?,?,?,?,?,?,?,?,0,0)
        """, (issue_time, issued_by, method, wcode,
              client_code, client_name, float(subtotal), float(rounding)))
        rid = cur.lastrowid

        cur.executemany("""
            INSERT INTO receipt_lines(receipt_id, material_name, unit_price,
                                      gross, tare, net, total)
            VALUES(?,?,?,?,?,?,?)
        """, [(rid, *row) for row in line_rows])

        return rid


def void_ticket(receipt_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE receipts SET voided = 1 WHERE id = ?", (receipt_id,))


def update_receipt_lines(edited_lines, rounding, receipt_id):
    """
    Save edited receipt lines and recalculated subtotal.
    *edited_lines*: list of (line_id, gross, tare, net, total).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        new_subtotal = 0.0
        for (line_id, g, t, n, tot) in edited_lines:
            cur.execute(
                "UPDATE receipt_lines SET gross=?, tare=?, net=?, total=? WHERE id=?",
                (g, t, n, tot, line_id),
            )
            new_subtotal += tot
        cur.execute(
            "UPDATE receipts SET subtotal=?, rounding_amount=? WHERE id=?",
            (new_subtotal, rounding, receipt_id),
        )


# ---------------------------------------------------------------------------
# Query helpers used by manage pages
# ---------------------------------------------------------------------------

def get_receipt_detail_inquiry_df(from_str, to_str):
    return qdf("""
        SELECT
            r.id                                           AS "Ticket Id",
            substr(r.issue_time, 1, 10)                    AS "Date Created",
            substr(r.issue_time, 12)                       AS "Time",
            CASE WHEN r.voided=1 THEN 'VOIDED' ELSE 'OPEN' END AS "Status",
            r.issued_by                                    AS "User",
            r.client_name                                  AS "Seller",
            r.rounding_amount                              AS "Total Amount"
        FROM receipts r
        WHERE substr(r.issue_time, 1, 10) >= ? AND substr(r.issue_time, 1, 10) <= ?
            AND r.voided = 0
        ORDER BY r.id DESC
        LIMIT 500
    """, (from_str, to_str))


def get_ticket_report_rows(from_str, to_str):
    return qdf("""
        SELECT r.* FROM receipts r
        WHERE substr(r.issue_time,1,10) >= ? AND substr(r.issue_time,1,10) <= ?
          AND r.voided=0
        ORDER BY r.id
    """, (from_str, to_str)).to_dict("records")


def get_void_receipts_df():
    return qdf("""
        SELECT id, issue_time, issued_by,
               (SELECT COUNT(*) FROM receipt_lines rl WHERE rl.receipt_id=r.id) AS material_count,
               subtotal, rounding_amount, ticketing_method,
               CASE WHEN withdrawn=1 THEN 'Withdrawn' ELSE 'Undrawn' END AS withdraw_status,
               CASE WHEN voided=1 THEN 'Voided' ELSE 'Not Voided' END AS void_status
        FROM receipts r
        ORDER BY id DESC
        LIMIT 500
    """)
