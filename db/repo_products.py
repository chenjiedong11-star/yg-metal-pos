"""
Repository — materials, categories, operators, and settings.
Includes B3 CRUD operations for categories and materials.
"""

import random
from datetime import datetime

from db.connection import get_connection, qdf, qone, exec_sql


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def get_categories():
    return qdf("SELECT id,name FROM material_categories ORDER BY sort_order, name")


def add_category(name: str, sort_order: int = 0) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO material_categories(name, sort_order) VALUES(?,?)",
            (name.strip(), sort_order),
        )
        return cur.lastrowid


def delete_category(cat_id: int) -> bool:
    """Delete category only if no active materials reference it."""
    row = qone(
        "SELECT COUNT(*) as c FROM materials WHERE category_id=? AND deleted=0",
        (cat_id,),
    )
    if row and row["c"] > 0:
        return False
    exec_sql("DELETE FROM material_categories WHERE id=?", (cat_id,))
    return True


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def get_materials():
    return qdf("""
        SELECT m.id, c.name AS category, m.item_code, m.name, m.unit, m.unit_price
        FROM materials m
        JOIN material_categories c ON c.id=m.category_id
        WHERE m.deleted=0
        ORDER BY c.sort_order, m.item_code
    """)


def get_all_materials_df():
    return qdf("""
        SELECT m.id, c.name AS category, m.item_code, m.name, m.unit,
               m.unit_price, m.min_unit_price, m.max_unit_price, m.deleted
        FROM materials m
        JOIN material_categories c ON c.id=m.category_id
        ORDER BY c.sort_order, m.item_code
        LIMIT 2000
    """)


def add_material(category_id: int, item_code: str, name: str, unit: str,
                 unit_price: float, min_price: float, max_price: float) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO materials(category_id, item_code, name, unit,
                                  unit_price, min_unit_price, max_unit_price,
                                  deleted, created_at)
            VALUES(?,?,?,?,?,?,?,0,?)
        """, (category_id, item_code.strip(), name.strip(), unit.strip(),
              unit_price, min_price, max_price,
              datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid


def update_material(mat_id: int, unit_price: float, min_price: float, max_price: float):
    exec_sql(
        "UPDATE materials SET unit_price=?, min_unit_price=?, max_unit_price=? WHERE id=?",
        (unit_price, min_price, max_price, mat_id),
    )


def delete_material(mat_id: int):
    exec_sql("UPDATE materials SET deleted=1 WHERE id=?", (mat_id,))


def restore_material(mat_id: int):
    exec_sql("UPDATE materials SET deleted=0 WHERE id=?", (mat_id,))


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def get_operators():
    return qdf("SELECT email, name FROM operators WHERE deleted=0 ORDER BY id DESC")


def get_all_operators_df():
    return qdf(
        "SELECT id, email AS 邮箱地址, name AS 姓名, deleted AS 删除标志, created_at "
        "FROM operators ORDER BY id DESC"
    )


def add_operator(email: str, name: str) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO operators(email,name,deleted,created_at) VALUES(?,?,0,?)",
            (email.strip(), name.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def delete_operator(op_id: int):
    exec_sql("UPDATE operators SET deleted=1 WHERE id=?", (op_id,))


def get_default_operator_email() -> str:
    op = qone("SELECT email FROM operators WHERE deleted=0 ORDER BY id LIMIT 1")
    return op["email"] if op else "admin@youli-trade.com"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default: str = "") -> str:
    r = qone("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def save_setting(key: str, value: str):
    exec_sql("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))


def gen_withdraw_code() -> str:
    return str(random.randint(100000, 999999))
