"""
Global configuration constants.
No imports from other project modules — this is the leaf of the dependency tree.
"""

DB_PATH = "scrap_pos.db"

RECEIPT_HEADER_LINES = ["YG METAL", "RC 4449276", "test@ygmetal.com"]
RECEIPT_WIDTH = 48
LEGAL_TEXT = (
    "I, the seller, testifies that these items are not stolen, and I have full ownership, "
    "and I convey the ownership of, and interest in these items in this sale to YG Eco Metal Inc."
)

# Phase 4: Debounce threshold in milliseconds for keypad/JS events
DEBOUNCE_MS = 150

# JS injected into print-page tabs: auto-print on load, auto-close after print.
PRINT_PAGE_SCRIPT = """
<script>
(function() {
  window.onload = function() { setTimeout(function() { window.print(); }, 150); };
  window.onafterprint = function() { try { window.close(); } catch(e) {} };
  setTimeout(function() {
    try { window.close(); } catch(e) {}
    var tip = document.createElement("p");
    tip.textContent = "如果页面未自动关闭，请手动关闭此标签页。";
    tip.style.cssText = "margin:1rem;font-size:14px;color:#666;";
    if (document.body) document.body.appendChild(tip);
  }, 4000);
})();
</script>
"""
