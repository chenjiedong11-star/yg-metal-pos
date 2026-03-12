"""
Repository — all ticket / receipt DB operations.
Phase 3: finalize_ticket() is fully atomic (single transaction).
MVP: Confirm 即落库 — create_draft_receipt, insert_receipt_line, insert_line_photos.
"""

import os
import uuid
from datetime import datetime

from core.config import DB_PATH
from db.connection import get_connection, qdf, qone

def _db_path_abs():
    return os.path.abspath(DB_PATH)


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


# ---------------------------------------------------------------------------
# MVP: Confirm 即落库 — draft receipt + 每行立即写 line + photos
# ---------------------------------------------------------------------------

def create_draft_receipt():
    """创建草稿单据，返回 receipt_id。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO receipts(issue_time, issued_by, ticketing_method,
                                 withdraw_code, client_code, client_name,
                                 subtotal, rounding_amount, voided, withdrawn)
            VALUES('', '', '', '', '', '', 0, 0, 0, 0)
        """)
        return cur.lastrowid


def insert_receipt_line(receipt_id: int, material_name: str, unit_price: float,
                       gross: float, tare: float, net: float, total: float):
    """插入一条 receipt_line，返回 line_id (receipt_lines.id)。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO receipt_lines(receipt_id, material_name, unit_price,
                                      gross, tare, net, total)
            VALUES(?,?,?,?,?,?,?)
        """, (receipt_id, material_name, unit_price, gross, tare, net, total))
        return cur.lastrowid


def insert_line_photos(ticket_item_id: int, photos: list):
    """
    写入 ticket_item_photos。photos = [(cam_index, image_bytes), ...]，允许只写 cam1。
    写入后立刻 SELECT 验证，返回 {"ticket_item_id", "photo_count", "lengths"}。
    失败时打印完整异常 + ticket_item_id/cam_index/len(bytes)/DB_PATH，不吞异常。
    """
    import traceback
    db_path = _db_path_abs()
    with get_connection() as conn:
        cur = conn.cursor()
        for cam_idx, payload in photos:
            blob = payload if isinstance(payload, bytes) else b""
            try:
                cur.execute(
                    "INSERT INTO ticket_item_photos"
                    "(ticket_item_id, cam_index, image_bytes, mime) VALUES(?,?,?,?)",
                    (ticket_item_id, cam_idx, blob, "image/jpeg"),
                )
                print(
                    "[insert_line_photos] OK:",
                    "DB_PATH=", db_path,
                    "ticket_item_id=", ticket_item_id,
                    "cam_index=", cam_idx,
                    "len(image_bytes)=", len(blob),
                )
            except Exception as e:
                print(
                    "[insert_line_photos] FAILED:",
                    "ticket_item_id=", ticket_item_id,
                    "cam_index=", cam_idx,
                    "len(image_bytes)=", len(blob),
                    "DB_PATH=", db_path,
                )
                traceback.print_exc()
                raise
        # 强校验：count / lengths / sum
        cur.execute(
            "SELECT length(image_bytes) AS len FROM ticket_item_photos WHERE ticket_item_id = ?",
            (ticket_item_id,),
        )
        rows = cur.fetchall()
        lengths = [r["len"] or 0 for r in rows]
        count = len(lengths)
        total_len = sum(lengths) if lengths else 0
        if count == 0 or total_len == 0:
            raise RuntimeError(
                f"Photo write verify failed for ticket_item_id={ticket_item_id} "
                f"(count={count}, total_len={total_len})"
            )
        return {
            "ticket_item_id": ticket_item_id,
            "photo_count": count,
            "lengths": lengths,
        }


def update_receipt_on_finalize(receipt_id: int, issue_time: str, issued_by: str,
                               method: str, wcode: str, client_code: str, client_name: str,
                               subtotal: float, rounding: float):
    """将草稿 receipt 更新为正式单据（不插 line，line 已在 Confirm 时写入）。"""
    with get_connection() as conn:
        conn.execute("""
            UPDATE receipts SET issue_time=?, issued_by=?, ticketing_method=?,
                withdraw_code=?, client_code=?, client_name=?,
                subtotal=?, rounding_amount=?
            WHERE id=?
        """, (issue_time, issued_by, method, wcode, client_code, client_name,
              subtotal, rounding, receipt_id))


def delete_receipt_line(line_id: int):
    """删除一条 line 及其照片。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM ticket_item_photos WHERE ticket_item_id = ?", (line_id,))
        conn.execute("DELETE FROM receipt_lines WHERE id = ?", (line_id,))


def delete_draft_receipt(receipt_id: int):
    """删除草稿单据及其所有 lines 和 photos。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM receipt_lines WHERE receipt_id = ?", (receipt_id,))
        for row in cur.fetchall():
            lid = row["id"]
            conn.execute("DELETE FROM ticket_item_photos WHERE ticket_item_id = ?", (lid,))
        conn.execute("DELETE FROM receipt_lines WHERE receipt_id = ?", (receipt_id,))
        conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))


def get_latest_receipt_line_ids(limit: int = 5):
    """返回最近 limit 条 receipt_lines 的 id（用于 Verify DB Photos）。"""
    df = qdf(
        "SELECT id FROM receipt_lines ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [] if df.empty else df["id"].tolist()


def get_photo_verification_for_line(line_id: int):
    """返回该 line 在 ticket_item_photos 的 count 与各条 length(image_bytes)。"""
    df = qdf(
        "SELECT cam_index, length(image_bytes) AS len FROM ticket_item_photos WHERE ticket_item_id = ?",
        (line_id,),
    )
    if df.empty:
        return {"line_id": line_id, "photo_count": 0, "lengths": []}
    return {
        "line_id": line_id,
        "photo_count": len(df),
        "lengths": df["len"].tolist(),
    }


def finalize_ticket(issue_time, issued_by, method, wcode,
                    client_code, client_name, subtotal, rounding, line_rows,
                    line_photos=None):
    """
    Phase 3 — Atomic ticket creation.
    *line_rows*: list of (material_name, unit_price, gross, tare, net, total).
    *line_photos*: optional list, same length as line_rows; each element is
        None or list of (cam_index, image_bytes) for that line (BLOB 存 ticket_item_photos).
    Returns (receipt_id, verification_list). verification_list: list of
        {"ticket_item_id": int, "photo_count": int, "lengths": [int, int]}.
    """
    verification = []
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

        line_ids = []
        for row in line_rows:
            cur.execute("""
                INSERT INTO receipt_lines(receipt_id, material_name, unit_price,
                                          gross, tare, net, total)
                VALUES(?,?,?,?,?,?,?)
            """, (rid, *row))
            line_ids.append(cur.lastrowid)

        # 写入 ticket_item_photos（BLOB）
        if line_photos:
            for i, photos in enumerate(line_photos):
                if photos and i < len(line_ids):
                    ticket_item_id = line_ids[i]
                    for cam_idx, payload in photos:
                        blob = payload if isinstance(payload, bytes) else b""
                        cur.execute(
                            "INSERT INTO ticket_item_photos"
                            "(ticket_item_id, cam_index, image_bytes, mime) VALUES(?,?,?,?)",
                            (ticket_item_id, cam_idx, blob, "image/jpeg"))

        # 写入后立刻验证：每个 ticket_item_id 的照片条数 = 2，每条 bytes 长度 > 1000
        for ticket_item_id in line_ids:
            cur.execute(
                "SELECT id, length(image_bytes) AS len FROM ticket_item_photos WHERE ticket_item_id = ?",
                (ticket_item_id,),
            )
            rows = cur.fetchall()
            verification.append({
                "ticket_item_id": ticket_item_id,
                "photo_count": len(rows),
                "lengths": [r["len"] or 0 for r in rows],
            })

    return rid, verification


def get_item_photos(ticket_item_id: int):
    """
    从 DB 读取某一条 line 的两张照片（仅 ticket_item_photos，BLOB）。
    返回 [(cam_index, image_bytes), ...]，按 cam_index 排序。
    """
    df = qdf(
        "SELECT cam_index, image_bytes FROM ticket_item_photos "
        "WHERE ticket_item_id = ? ORDER BY cam_index",
        (ticket_item_id,),
    )
    if df.empty:
        return []
    return [(int(r["cam_index"]), r["image_bytes"]) for _, r in df.iterrows()]


def get_line_photos(receipt_id: int):
    """Return DataFrame: line_id, cam_index, photo_path for a receipt (旧表 receipt_line_photos)."""
    return qdf(
        "SELECT line_id, cam_index, photo_path FROM receipt_line_photos "
        "WHERE receipt_id = ? ORDER BY line_id, cam_index",
        (receipt_id,))


def void_ticket(receipt_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE receipts SET voided = 1 WHERE id = ?", (receipt_id,))


def restore_ticket(receipt_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE receipts SET voided = 0 WHERE id = ?", (receipt_id,))


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
               CASE WHEN withdrawn=1 THEN 'Withdrawn' ELSE 'Undrawn' END AS withdraw_status
        FROM receipts r
        WHERE voided = 1
        ORDER BY id DESC
        LIMIT 500
    """)
