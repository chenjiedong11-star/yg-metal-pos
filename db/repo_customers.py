"""
Repository — client / customer DB operations (with B3 CRUD).
"""

import random
from datetime import datetime

from db.connection import get_connection, qdf, qone, exec_sql


def get_clients():
    return qdf("SELECT code, name, phone FROM clients WHERE deleted=0 ORDER BY id DESC")


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
               phone AS 手机号码, email AS 邮箱地址, deleted AS 删除标志
        FROM clients ORDER BY id DESC LIMIT 2000
    """)


def update_client(client_id: int, name: str, phone: str, email: str = "", id_number: str = ""):
    exec_sql(
        "UPDATE clients SET name=?, phone=?, email=?, id_number=? WHERE id=?",
        (name.strip(), phone.strip(), email.strip(), id_number.strip(), client_id),
    )


def delete_client(client_id: int):
    exec_sql("UPDATE clients SET deleted=1 WHERE id=?", (client_id,))
