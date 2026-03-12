"""
Database schema creation and seed data.
Called once at app startup via init_db().
"""

from datetime import datetime

from db.connection import get_connection


def init_db():
    """Create all tables if they don't exist, seed default rows, enable WAL."""
    with get_connection() as conn:
        cur = conn.cursor()

        # WAL mode — persistent per DB file, safe to set once
        cur.execute("PRAGMA journal_mode=WAL")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            phone TEXT,
            email TEXT,
            id_number TEXT,
            tier_level INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            created_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT,
            deleted INTEGER DEFAULT 0,
            created_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS material_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            sort_order INTEGER DEFAULT 0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER,
            item_code TEXT,
            name TEXT,
            unit TEXT DEFAULT 'LB',
            unit_price REAL DEFAULT 0,
            min_unit_price REAL DEFAULT 0,
            max_unit_price REAL DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            created_at TEXT,
            FOREIGN KEY(category_id) REFERENCES material_categories(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_time TEXT,
            issued_by TEXT,
            ticketing_method TEXT DEFAULT 'Print',
            withdraw_code TEXT,
            client_code TEXT,
            client_name TEXT,
            subtotal REAL DEFAULT 0,
            rounding_amount REAL DEFAULT 0,
            voided INTEGER DEFAULT 0,
            withdrawn INTEGER DEFAULT 0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipt_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER,
            material_name TEXT,
            unit_price REAL,
            gross REAL,
            tare REAL,
            net REAL,
            total REAL,
            FOREIGN KEY(receipt_id) REFERENCES receipts(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS print_previews (
            token TEXT PRIMARY KEY,
            html TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipt_print (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            html TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        # 每个 line item 两张照片（cam1 + cam2），存路径便于管理端读取（旧）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipt_line_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            line_id INTEGER NOT NULL,
            cam_index INTEGER NOT NULL,
            photo_path TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (receipt_id) REFERENCES receipts(id),
            FOREIGN KEY (line_id) REFERENCES receipt_lines(id)
        )
        """)

        # MVP 测试阶段：照片存 BLOB，管理端只从 DB 读（ticket_item_id = receipt_lines.id）
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ticket_item_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_item_id INTEGER NOT NULL,
            cam_index INTEGER NOT NULL,
            image_bytes BLOB NOT NULL,
            mime TEXT DEFAULT 'image/jpeg',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (ticket_item_id) REFERENCES receipt_lines(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS material_tier_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER NOT NULL,
            tier_level INTEGER NOT NULL CHECK(tier_level BETWEEN 1 AND 5),
            pct_adjustment REAL DEFAULT 0,
            UNIQUE(material_id, tier_level),
            FOREIGN KEY(material_id) REFERENCES materials(id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS client_material_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            material_id INTEGER NOT NULL,
            adjust_type TEXT NOT NULL DEFAULT 'pct',
            adjust_value REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(client_id, material_id),
            FOREIGN KEY(client_id) REFERENCES clients(id),
            FOREIGN KEY(material_id) REFERENCES materials(id)
        )
        """)

        # Migrate: add tier_level to clients if missing
        cur.execute("PRAGMA table_info(clients)")
        col_names = [r[1] for r in cur.fetchall()]
        if "tier_level" not in col_names:
            cur.execute("ALTER TABLE clients ADD COLUMN tier_level INTEGER DEFAULT 0")

        # ------------------------------------------------------------------
        # Seed defaults (idempotent)
        # ------------------------------------------------------------------
        cur.execute("SELECT COUNT(*) c FROM operators")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT INTO operators(email,name,created_at) VALUES(?,?,?)",
                ("admin@youli-trade.com", "Andy Chen",
                 datetime.now().isoformat(timespec="seconds")),
            )

        cur.execute("SELECT COUNT(*) c FROM material_categories")
        if cur.fetchone()["c"] == 0:
            cats = [("Copper", 1), ("Alum", 2), ("Wire", 3),
                    ("Others", 4), ("Metal", 5)]
            cur.executemany(
                "INSERT INTO material_categories(name, sort_order) VALUES(?,?)", cats)

        cur.execute("SELECT COUNT(*) c FROM materials")
        if cur.fetchone()["c"] == 0:
            cur.execute("SELECT id,name FROM material_categories")
            cmap = {r["name"]: r["id"] for r in cur.fetchall()}
            now = datetime.now().isoformat(timespec="seconds")
            seed = [
                (cmap["Copper"], "1001", "Bare Bright 光亮铜", "LB", 4.70, 2.70, 5.00),
                (cmap["Copper"], "1002", "Cu#1 一号铜", "LB", 4.45, 2.50, 4.60),
                (cmap["Copper"], "1003", "Cu#2 二号铜", "LB", 4.00, 2.20, 4.30),
                (cmap["Wire"],   "2001", "Romex 电线", "LB", 2.50, 1.50, 3.50),
                (cmap["Metal"],  "3001", "H/G 高铁", "LB", 0.18, 0.10, 0.30),
                (cmap["Alum"],   "4001", "Alum Clean 干净铝", "LB", 0.75, 0.40, 1.20),
                (cmap["Others"], "5001", "E-Motor 马达", "LB", 0.20, 0.10, 0.40),
            ]
            cur.executemany("""
                INSERT INTO materials(category_id,item_code,name,unit,unit_price,
                                      min_unit_price,max_unit_price,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, [(a, b, c, d, e, f, g, now) for (a, b, c, d, e, f, g) in seed])

        cur.execute("SELECT COUNT(*) c FROM clients")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT INTO clients(code,name,phone,created_at) VALUES(?,?,?,?)",
                ("000001", "Walk-in", "",
                 datetime.now().isoformat(timespec="seconds")),
            )

        cur.execute("SELECT COUNT(*) c FROM settings")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                ("unit_price_adjustment_permitted", "Yes"),
            )
