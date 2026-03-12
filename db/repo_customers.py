"""
Repository — client / customer DB operations (with B3 CRUD).
"""

import random
from datetime import datetime

from db.connection import get_connection, qdf, qone, exec_sql


def get_clients():
    return qdf("SELECT code, name, phone, COALESCE(tier_level, 0) AS tier_level FROM clients WHERE deleted=0 ORDER BY id DESC")


def gen_code_6() -> str:
    for _ in range(200):
        code = f"{random.randint(0, 999999):06d}"
        if not qone("SELECT 1 FROM clients WHERE code=?", (code,)):
            return code
    mx = qone("SELECT MAX(CAST(code as INTEGER)) AS m FROM clients")
    m = int(mx["m"] or 0)
    return f"{(m + 1) % 1000000:06d}"


def save_customer(name: str, phone: str) -> str:
    code = gen_code_6()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO clients(code,name,phone,created_at) VALUES(?,?,?,?)",
            (code, name.strip(), phone.strip(),
             datetime.now().isoformat(timespec="seconds")),
        )
    return code


def get_all_clients_df():
    return qdf("""
        SELECT id, code AS 编号, name AS 姓名, id_number AS 身份证号码,
               phone AS 手机号码, email AS 邮箱地址,
               COALESCE(tier_level, 0) AS Tier级别, deleted AS 删除标志
        FROM clients ORDER BY id DESC LIMIT 2000
    """)


def update_client(client_id: int, name: str, phone: str, email: str = "",
                   id_number: str = "", tier_level: int = 0):
    exec_sql(
        "UPDATE clients SET name=?, phone=?, email=?, id_number=?, tier_level=? WHERE id=?",
        (name.strip(), phone.strip(), email.strip(), id_number.strip(), int(tier_level), client_id),
    )


def get_client_tier(client_code: str) -> int:
    """Return tier_level for a client by code (0 = base price)."""
    row = qone("SELECT COALESCE(tier_level, 0) AS tier_level FROM clients WHERE code=? AND deleted=0", (client_code,))
    return int(row["tier_level"]) if row else 0


def delete_client(client_id: int):
    exec_sql("UPDATE clients SET deleted=1 WHERE id=?", (client_id,))
