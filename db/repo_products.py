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


# ---------------------------------------------------------------------------
# Tier pricing
# ---------------------------------------------------------------------------

def get_material_tiers(material_id: int) -> dict:
    """Return {tier_level: pct_adjustment} for a material (levels 1-5)."""
    rows = qdf(
        "SELECT tier_level, pct_adjustment FROM material_tier_prices WHERE material_id=?",
        (material_id,),
    )
    result = {i: 0.0 for i in range(1, 6)}
    for _, r in rows.iterrows():
        result[int(r["tier_level"])] = float(r["pct_adjustment"])
    return result


def save_material_tiers(material_id: int, tiers: dict):
    """Save tier percentages for a material. tiers = {1: 10.0, 2: 15.0, ...}"""
    with get_connection() as conn:
        for level, pct in tiers.items():
            conn.execute(
                "INSERT INTO material_tier_prices(material_id, tier_level, pct_adjustment) "
                "VALUES(?,?,?) ON CONFLICT(material_id, tier_level) DO UPDATE SET pct_adjustment=?",
                (material_id, int(level), float(pct), float(pct)),
            )


def get_client_material_prices(client_id: int):
    """Return all custom price adjustments for a client as a list of dicts."""
    return qdf("""
        SELECT cmp.id, cmp.material_id, m.name AS material_name,
               c.name AS category_name, cmp.adjust_type, cmp.adjust_value
        FROM client_material_prices cmp
        JOIN materials m ON m.id = cmp.material_id
        JOIN material_categories c ON c.id = m.category_id
        WHERE cmp.client_id = ?
        ORDER BY c.sort_order, m.item_code
    """, (client_id,))


def save_client_material_price(client_id: int, material_id: int,
                               adjust_type: str, adjust_value: float):
    """Save or update a client-specific material price adjustment."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO client_material_prices(client_id, material_id, adjust_type, adjust_value) "
            "VALUES(?,?,?,?) ON CONFLICT(client_id, material_id) DO UPDATE "
            "SET adjust_type=?, adjust_value=?",
            (client_id, material_id, adjust_type, float(adjust_value),
             adjust_type, float(adjust_value)),
        )


def delete_client_material_price(record_id: int):
    exec_sql("DELETE FROM client_material_prices WHERE id=?", (record_id,))


def get_client_adjusted_price(client_id: int, material_id: int, base_price: float):
    """Return the client-specific adjusted price, or None if no custom price set."""
    row = qone(
        "SELECT adjust_type, adjust_value FROM client_material_prices "
        "WHERE client_id=? AND material_id=?",
        (client_id, material_id),
    )
    if not row:
        return None
    if row["adjust_type"] == "pct":
        return round(base_price * (1 + float(row["adjust_value"]) / 100.0), 3)
    else:
        return round(base_price + float(row["adjust_value"]), 3)


def get_tier_adjusted_price(material_id: int, tier_level: int):
    """Return the tier-adjusted unit price, or None if no tier / tier=0."""
    if not tier_level or tier_level < 1 or tier_level > 5:
        return None
    row = qone(
        "SELECT m.unit_price, COALESCE(t.pct_adjustment, 0) AS pct "
        "FROM materials m LEFT JOIN material_tier_prices t "
        "ON t.material_id=m.id AND t.tier_level=? "
        "WHERE m.id=?",
        (tier_level, material_id),
    )
    if not row:
        return None
    base = float(row["unit_price"] or 0)
    pct = float(row["pct"] or 0)
    return round(base * (1 + pct / 100.0), 3)
