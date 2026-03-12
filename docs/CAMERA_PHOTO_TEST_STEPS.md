# 拍照功能 — 手工测试步骤与黑屏问题说明

## 一、修改文件列表

| 文件 | 变更说明 |
|------|----------|
| `db/schema.py` | 新增表 `receipt_line_photos`（receipt_id, line_id, cam_index, photo_path, created_at） |
| `db/repo_ticketing.py` | `finalize_ticket` 增加参数 `line_photos` 并写入照片；新增 `get_line_photos(receipt_id)` |
| `core/state.py` | 新增 session 键：`_cam_mode`, `_cam_data_saved`, `_current_line_photos`, `_receipt_line_photos`, `_saved_gross_before_tare` |
| `ui/page_ticketing.py` | Gross→Enter 触发拍照、双摄 capture/frozen、bridge 取数存 `photos/`、Confirm 时并入行照片、Print 时写入 DB；保留 Gross 显示与删除行时同步照片列表 |
| `ui/page_manage.py` | 票据明细每行增加 Photos 列：从 DB 读 `get_line_photos`，缩略图 + 点击展开大图（expander） |
| `components/cam_bridge/index.html` | 自定义组件：轮询 `parent.__posCamData` 并回传 JSON 给 Streamlit |
| `tests/smoke_test.py` | 增加表 `receipt_line_photos` 校验；新增 `test_line_photos_write_read`（finalize_ticket + get_line_photos） |

## 二、“黑屏/看不到照片”根因与修复

- **原因归纳**  
  - 之前：1）按 Enter 后未切到“拍照并冻结”模式，画面继续 live 或未取帧；2）取帧太早 `readyState` 不足导致黑图；3）照片未从 iframe 传到 Python，未落盘；4）管理端未从 DB 读，或路径非绝对导致读不到文件。  
- **修复措施**  
  1. **触发与模式**：Gross 按 Enter 时设置 `_cam_mode="capture"` 并 `st.rerun()`，摄像头 HTML 以 `doCapture=true` 重新渲染，取两路帧后写 `parent.__posCamData` 并显示静态图（不再黑屏）。  
  2. **取帧时机**：JS 中 `waitForFrame(videoEl, 2500)`，等 `readyState >= 2` 再 `grabFrame`，减少黑图。  
  3. **数据到 Python**：通过 `cam_bridge` 组件轮询 `parent.__posCamData`（约 6s），拿到 base64 后 Python 解码为 JPEG 写入 `photos/`，路径存为**绝对路径**并写入 DB。  
  4. **管理端**：仅用 DB 的 `get_line_photos(receipt_id)` 和 `photo_path`（绝对路径），用 `st.image(path)` 展示；路径无效时显示 “—” 而不崩溃。  
  5. **格式**：前端 `canvas.toDataURL('image/jpeg', 0.85)`，后端按 JPEG bytes 存盘，展示一致。

## 三、Smoke Test

在项目根目录执行：

```bash
# 语法/导入检查（不写 pycache 时可直接用）
python3 -c "
import sys; sys.dont_write_bytecode = True
import db.schema, db.repo_ticketing, core.state, ui.page_ticketing, ui.page_manage
print('OK')
"

# 完整 smoke（含 DB 照片写入/读取）
python3 tests/smoke_test.py
```

若 `test_compile_all` 因无写权限失败，可忽略或在本机非沙箱环境运行；其余用例（含 `test_line_photos_write_read`）通过即表示照片落库与读取正常。

## 四、手工测试步骤（必须严格按顺序）

### 1. 自动拍两张并显示静态图

1. 启动：`streamlit run app.py`，进入 **开票（Ticketing）** 页。  
2. 左下方选一个 **Material**，右侧出现 Unit Price / Gross / Tare。  
3. 在 **Gross (LB)** 输入数字（如 `100`），用键盘或 Keypad 按 **Enter**。  
4. **预期**：  
   - 焦点跳到 **Tare**；  
   - 下方两个摄像头区域先可能短暂 loading，随后显示**刚拍下的静态照片**（非黑屏、非继续实时预览）；  
   - 两区可显示 “CAPTURED” 角标。  
5. Gross 框内数字应**保持显示**（不因切到 Tare 而清空）。

### 2. 确认行并保存票据

6. 在 **Tare (LB)** 输入数字（如 `10`），点击 **Confirm (Enter)**。  
7. 该行加入左侧 Receipt 表格。  
8. 再选一个 Material，输入 Gross → Enter → 再拍一组两张；输入 Tare → Confirm，第二行加入表格。  
9. 点击 **Print / Save Receipt** 完成存单。  
10. **预期**：`photos/` 目录下出现 `capture_*_cam1.jpg`、`capture_*_cam2.jpg`（每个产品行各 2 张）；无报错。

### 3. 管理端查看缩略图与放大

11. 进入 **管理（Manage）** → **票据明细信息查询**。  
12. 条件筛出刚保存的票据，点击 **Open**。  
13. **预期**：  
    - 每个产品行右侧有 **Photos** 列；  
    - 该列显示 CAM1/CAM2 的**缩略图**（或 “CAM1”/“CAM2” 的 expander）；  
    - **点击 expander 可放大查看大图**，图片清晰、非黑屏。  
14. 若某行无照片或路径失效，该行 Photos 显示 “—” 或 “CAM1: —”，不报错。

### 4. 纠错：回 Gross 再拍

15. 回到 **开票** 页，选一个 Material，输入 Gross → **Enter**（拍一次）。  
16. 在 Tare 阶段**点击 Gross 标签/输入框**（或 Keypad 上切回 Gross）。  
17. **预期**：摄像头区域恢复 **live 预览**（重新拉流）。  
18. 再次在 Gross 输入数字并 **Enter**。  
19. **预期**：再次拍两张，画面更新为新的静态图；若未 Confirm，该行仍为“当前行”，新照片覆盖旧照片；Confirm 后该行带新照片入表。

### 5. 清空与删除行

20. 在 Receipt 表格勾选某行 “删”，或点击 **Clear Receipt**。  
21. **预期**：照片列表与表格同步（删除行后该行照片不再参与保存）；Clear Receipt 后无残留照片状态。

---

**禁止事项**：不删 Menu、不大改 UI 布局、不用一次性 DOM hack（如 `window.parent.document`）导致 rerun 后失效、管理端必须从 DB 读图不依赖 session_state。
