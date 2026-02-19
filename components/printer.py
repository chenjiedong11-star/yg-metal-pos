"""
All print-related JS injection functions — centralised in one place.
"""

import json
import base64
import uuid
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

from db.repo_ticketing import save_preview_html


def render_and_print_receipt(receipt_html: str) -> None:
    """Hidden-iframe approach: write receipt into iframe, trigger print."""
    payload = json.dumps(receipt_html)
    js = f"""
<script>
(function() {{
  const html = {payload};
  const old = document.getElementById("receipt-print-frame");
  if (old) old.remove();
  const iframe = document.createElement("iframe");
  iframe.id = "receipt-print-frame";
  iframe.style.position = "fixed";
  iframe.style.right = "0"; iframe.style.bottom = "0";
  iframe.style.width = "0"; iframe.style.height = "0";
  iframe.style.border = "0"; iframe.style.opacity = "0";
  iframe.style.pointerEvents = "none";
  document.body.appendChild(iframe);
  const doc = iframe.contentWindow.document;
  doc.open(); doc.write(html); doc.close();
  const doPrint = () => {{
    try {{
      iframe.contentWindow.focus();
      iframe.contentWindow.print();
      setTimeout(() => {{ try {{ iframe.remove(); }} catch(e) {{}} }}, 1200);
    }} catch(e) {{
      console.error("iframe print failed", e);
      try {{
        const w = window.open("", "_blank", "width=1,height=1");
        if (w) {{ w.document.write(html); w.document.close(); w.focus(); w.print();
          setTimeout(() => {{ try {{ w.close(); }} catch(x) {{}} }}, 800);
        }} else {{
          document.body.innerHTML = '<div style="color:#b00;padding:8px;">打印失败：请尝试 Ctrl+P 或允许弹窗。</div>';
        }}
      }} catch(x) {{}}
    }}
  }};
  iframe.onload = () => {{ setTimeout(doPrint, 200); }};
  setTimeout(doPrint, 600);
}})();
</script>
"""
    components.html(js, height=0, scrolling=False)


def open_print_window(receipt_html: str) -> None:
    """Stable popup approach: opener script handles print/close lifecycle."""
    payload = json.dumps(receipt_html)
    script = f"""
<script>
(function() {{
  const html = {payload};
  const w = window.open('', '_blank');
  if (!w) {{ alert('浏览器拦截了打印窗口，请允许弹窗后重试。'); return; }}
  w.document.open(); w.document.write(html); w.document.close();
  let closed = false;
  function tryClose() {{ if (closed) return; closed = true; try {{ w.close(); }} catch(e) {{}} }}
  let printed = false;
  function doPrint() {{
    if (printed) return; printed = true;
    try {{ w.focus(); w.print(); }} catch(e) {{ console.warn('auto print blocked', e); }}
  }}
  const start = Date.now();
  const timer = setInterval(() => {{
    try {{
      if (w.document && w.document.readyState === 'complete') {{
        clearInterval(timer); setTimeout(doPrint, 150);
      }} else if (Date.now() - start > 2000) {{
        clearInterval(timer); setTimeout(doPrint, 150);
      }}
    }} catch(e) {{ clearInterval(timer); setTimeout(doPrint, 150); }}
  }}, 50);
  w.addEventListener('afterprint', tryClose);
  const mql = w.matchMedia ? w.matchMedia('print') : null;
  if (mql) {{
    const onChange = (e) => {{ if (!e.matches) tryClose(); }};
    if (mql.addEventListener) mql.addEventListener('change', onChange);
    else if (mql.addListener) mql.addListener(onChange);
  }}
  setTimeout(() => {{
    tryClose();
    try {{
      const tip = w.document.createElement('div');
      tip.textContent = '如果页面未自动关闭，请手动关闭此标签页。';
      tip.style.cssText = 'margin:16px;font-size:14px;color:#666;text-align:center;';
      w.document.body && w.document.body.appendChild(tip);
    }} catch(e) {{}}
  }}, 4000);
}})();
</script>
"""
    components.html(script, height=0, width=0)


def open_print_preview_window(receipt_html: str):
    """Server-side preview: store HTML, open via ?preview_token= URL."""
    from services.ticketing_service import wrap_receipt_for_preview
    preview_html = wrap_receipt_for_preview(receipt_html)
    token = save_preview_html(preview_html)
    b64 = base64.b64encode(preview_html.encode("utf-8")).decode("ascii")

    st.session_state._print_diag = {
        "html_len": len(preview_html),
        "b64_len": len(b64),
        "first200": preview_html[:200],
    }
    st.session_state._pending_preview_token = token
    st.session_state._pending_preview_b64 = b64

    script = f"""<script>
(function() {{
  try {{
    var token = "{token}";
    var url = window.location.origin + window.location.pathname + "?preview_token=" + token;
    console.log("Print preview URL:", url);
    var w = window.open(url, "_blank");
    if (w) {{
      alert("Preview opened. In the new tab click Print to print.");
    }} else {{
      alert("Popup blocked. Use the link below to open Print Preview.");
    }}
  }} catch(e) {{
    console.error("Print preview error:", e);
    alert("Error: " + e.message);
  }}
}})();
</script>"""
    components.html(script, height=0)


def print_receipt_in_place(receipt_html: str):
    """Trigger print via hidden iframe attached to Streamlit parent document."""
    safe_html_js = json.dumps(receipt_html)
    js = f"""
    <script>
    (function() {{
      try {{
        const parentDoc = window.parent.document;
        let iframe = parentDoc.getElementById("yg_print_iframe");
        if (!iframe) {{
          iframe = parentDoc.createElement("iframe");
          iframe.id = "yg_print_iframe";
          iframe.style.position = "fixed";
          iframe.style.right = "0"; iframe.style.bottom = "0";
          iframe.style.width = "0"; iframe.style.height = "0";
          iframe.style.border = "0"; iframe.style.opacity = "0";
          iframe.style.pointerEvents = "none";
          parentDoc.body.appendChild(iframe);
        }}
        const doc = iframe.contentWindow.document;
        const htmlStr = {safe_html_js};
        doc.open(); doc.write(htmlStr); doc.close();
        setTimeout(() => {{
          iframe.contentWindow.focus();
          iframe.contentWindow.print();
        }}, 120);
      }} catch(e) {{
        console.error("Print failed:", e);
        alert("Print failed: " + e);
      }}
    }})();
    </script>
    """
    components.html(js, height=0)


def inject_blob_preview_open(b64: str):
    """Blob URL fallback for print preview."""
    script = f"""<script>
(function() {{
  try {{
    var b64 = "{b64}";
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var html = new TextDecoder("utf-8").decode(bytes);
    var blob = new Blob([html], {{ type: "text/html;charset=utf-8" }});
    var url = URL.createObjectURL(blob);
    window.open(url, "_blank");
  }} catch(e) {{
    alert("Blob open failed: " + e.message);
  }}
}})();
</script>"""
    components.html(script, height=0)


def inject_print_via_hidden_iframe(receipt_html: str) -> str:
    """Return an HTML document that auto-prints receipt_html in a hidden iframe."""
    b64 = base64.b64encode(receipt_html.encode("utf-8")).decode("ascii")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<script>
(function() {{
  var html = atob("{b64}");
  var iframe = document.createElement("iframe");
  iframe.style.cssText = "position:absolute;width:0;height:0;border:none;left:-9999px;top:0;";
  document.body.appendChild(iframe);
  iframe.contentWindow.document.open();
  iframe.contentWindow.document.write(html);
  iframe.contentWindow.document.close();
  iframe.contentWindow.focus();
  setTimeout(function() {{
    iframe.contentWindow.print();
    setTimeout(function() {{ if (iframe.parentNode) iframe.parentNode.removeChild(iframe); }}, 1000);
  }}, 200);
}})();
</script>
</body></html>"""
