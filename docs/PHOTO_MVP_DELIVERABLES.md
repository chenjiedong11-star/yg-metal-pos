# 拍照 MVP 交付说明（测试阶段）

## E. 交付清单

### 1. 修改的文件列表

| 路径 | 变更说明 |
|------|----------|
| `db/schema.py` | 新增表 `ticket_item_photos`（BLOB 存图） |
| `db/repo_ticketing.py` | `finalize_ticket` 写入 `ticket_item_photos` 并返回验证信息；新增 `get_item_photos(ticket_item_id)` |
| `core/state.py` | 新增 session 键 `pending_item_photos` |
| `ui/page_ticketing.py` | 拍照存 bytes、`pending_item_photos` 同步、传 bytes 给 finalize、左侧「照片诊断」展示 |
| `ui/page_manage.py` | 票据明细按 `line_id` 用 `get_item_photos` 从 DB 读 BLOB，缩略图 + 点击展开 |
| `tests/smoke_test.py` | 必选表加 `ticket_item_photos`；`test_line_photos_write_read` 改为 BLOB 写读 |

---

### 2. 是否改了 DB schema？建表/迁移片段

**是。** 新增表 `ticket_item_photos`，未改现有票据/产品/客户表。

建表代码（已在 `db/schema.py` 的 `init_db()` 中执行）：

```sql
CREATE TABLE IF NOT EXISTS ticket_item_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_item_id INTEGER NOT NULL,
    cam_index INTEGER NOT NULL,
    image_bytes BLOB NOT NULL,
    mime TEXT DEFAULT 'image/jpeg',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (ticket_item_id) REFERENCES receipt_lines(id)
);
```

无需单独迁移脚本，启动应用时 `init_db()` 会自动建表。

---

### 3. 照片存在哪里？（DB 表/字段 + 关联 key）

- **表名**：`ticket_item_photos`
- **字段**：`id`, `ticket_item_id`, `cam_index`, `image_bytes` (BLOB), `mime`, `created_at`
- **关联**：`ticket_item_id` = `receipt_lines.id`（即本系统中的 line 主键，一条 line 两张照片 cam_index=1/2）
- **说明**：照片**只存 SQLite**，以 BLOB 写入 `ticket_item_photos`；不依赖 `session_state` 做持久化，管理端只从 DB 读。

---

### 4. 管理端如何读到？查询 SQL / repo 函数名

- **Repo 函数**：`get_item_photos(ticket_item_id: int)`（`db/repo_ticketing.py`）
- **SQL**：  
  `SELECT cam_index, image_bytes FROM ticket_item_photos WHERE ticket_item_id = ? ORDER BY cam_index`
- **返回**：`[(cam_index, image_bytes), ...]`，管理端用 `st.image(image_bytes, width=120)` 与 expander 内大图展示。

---

### 5. 本地最小测试步骤（3 步）

1. **编译与 smoke**  
   `python3 tests/smoke_test.py`  
   确认包含 `ticket_item_photos BLOB write/read` 通过。

2. **开票端：拍 2 张并落库**  
   - 开票页选一个 Material → Gross 输入数字 → 按 Enter（触发双摄拍照）。  
   - 左侧展开「照片诊断」：应看到 **A. Gross Enter 拍照** 的 `len(cam1_bytes)` / `len(cam2_bytes)` / `pending_item_index`。  
   - 输入 Tare → Confirm → 再可选加一行或直接 **Print / Save Receipt**。  
   - 诊断中应出现 **B. 写入 DB 后**：`receipt_id`、每个 `ticket_item_id` 的 `photo_count=2`、`lengths` 两条均 > 1000。

3. **管理端：从 DB 看图**  
   - 管理 → 票据明细信息查询 → 找到刚保存的单据 → Open。  
   - 该单据的每个 product line 在 **Photos** 列应出现两张缩略图（CAM1/CAM2），点击 expander 可放大；**不依赖 session_state，仅从 SQLite 读**。

---

## 诊断输出说明（你关心的三个阶段）

- **A. Gross Enter 触发拍照时**  
  - `len(cam1_bytes)` / `len(cam2_bytes)`：本次抓到的两张图字节长度。  
  - `pending_item_index`：当前“待提交 item”的序号（即将成为第几条 line）。

- **B. 该 item 写入票据明细（保存到 DB）时**  
  - 在 **Print / Save Receipt** 后，诊断区显示：  
    - `receipt_id`（= ticket_id）；  
    - 每个 `ticket_item_id` 及对应的 `photo_count`、`lengths`（两条 bytes 长度）。

- **C. 写入后立刻验证**  
  - 在 `finalize_ticket()` 内，插入 `ticket_item_photos` 后立即执行：  
    - 对每个 `ticket_item_id`：`SELECT id, length(image_bytes) FROM ticket_item_photos WHERE ticket_item_id = ?`  
  - 验证结果通过返回值传给前端，在「照片诊断」的 **B. 写入 DB 后** 展示：`photo_count` 应为 2，`lengths` 每条应 > 1000。

**结论**：照片**已写入 SQLite**（表 `ticket_item_photos`，字段 `image_bytes`），不是只存在 `session_state`；管理端只通过 `get_item_photos(ticket_item_id)` 从 DB 读取并展示。
