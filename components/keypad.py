"""
On-screen keypad — HTML/JS injection wrapper.
Phase 4: events are dispatched deterministically with debounce (~150 ms).
"""

import streamlit.components.v1 as components


def render_keypad():
    """Inject the on-screen numeric keypad."""
    _keypad_html = """
<style>
  .kp-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:5px; font-family:Arial,sans-serif; }
  .kp-btn {
    padding:10px 0; font-size:17px; font-weight:700; border:1px solid #d1d5db;
    border-radius:6px; background:#fff; cursor:pointer; text-align:center;
    user-select:none; -webkit-user-select:none; transition:background 0.1s;
  }
  .kp-btn:active { background:#e5e7eb; }
</style>
<div class="kp-grid">
  <div class="kp-btn" data-k="1">1</div><div class="kp-btn" data-k="2">2</div><div class="kp-btn" data-k="3">3</div>
  <div class="kp-btn" data-k="4">4</div><div class="kp-btn" data-k="5">5</div><div class="kp-btn" data-k="6">6</div>
  <div class="kp-btn" data-k="7">7</div><div class="kp-btn" data-k="8">8</div><div class="kp-btn" data-k="9">9</div>
  <div class="kp-btn" data-k="0">0</div><div class="kp-btn" data-k=".">.</div><div class="kp-btn" data-k="del">⌫</div>
</div>
<script>
(function(){
  var doc = window.parent.document;
  if (!doc.querySelectorAll('[data-testid="stTextInput"]').length && window.parent.parent && window.parent.parent.document) {
    doc = window.parent.parent.document;
  }
  var DEBOUNCE_MS = 150;

  if (doc.__kpFocusHandler) {
    doc.removeEventListener('focusin', doc.__kpFocusHandler, true);
  }
  doc.__kpFocusHandler = function(e) {
    if (!e.target || e.target.tagName !== 'INPUT') return;
    var w = e.target.closest('[data-testid="stTextInput"]');
    if (!w) return;
    var lb = w.querySelector('label');
    var txt = lb ? lb.textContent : '';
    if (txt.indexOf('Price') >= 0 || txt.indexOf('Gross') >= 0 || txt.indexOf('Tare') >= 0) {
      doc.__kpLastInput = e.target;
    }
  };
  doc.addEventListener('focusin', doc.__kpFocusHandler, true);

  var pWin = window.parent;
  var nativeSetter = (pWin && pWin.HTMLInputElement && Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, 'value'))
    ? Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, 'value').set
    : Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  function setVal(input, val) {
    if (!input || !input.setAttribute) return;
    nativeSetter.call(input, val);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function labelOfInput(input) {
    if (!input || !input.closest) return '';
    var w = input.closest('[data-testid="stTextInput"]');
    if (!w) return '';
    var lb = w.querySelector('label');
    return lb ? (lb.textContent || '').trim() : '';
  }

  function getTarget() {
    var last = doc.__kpLastInput;
    if (last && last.isConnected && !last.disabled) return last;
    var blocks = doc.querySelectorAll('[data-testid="stTextInput"]');
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      var txt = block.textContent || '';
      if (txt.indexOf('Gross') >= 0) {
        var inp = block.querySelector('input');
        if (inp && !inp.disabled) { doc.__kpLastInput = inp; return inp; }
      }
    }
    return null;
  }

  /* Phase 4: debounce — ignore duplicate events within DEBOUNCE_MS */
  if (!doc.__kpLastClickTs) doc.__kpLastClickTs = 0;

  document.querySelectorAll('.kp-btn').forEach(function(btn) {
    btn.addEventListener('mousedown', function(e) { e.preventDefault(); });
    btn.addEventListener('click', function() {
      var now = Date.now();
      if (now - doc.__kpLastClickTs < DEBOUNCE_MS) return;
      doc.__kpLastClickTs = now;

      var key = this.getAttribute('data-k');
      var ts = doc.__ts;
      if (ts && ts.active) {
        ts.buf.push(key);
        return;
      }
      var input = getTarget();
      if (!input) return;
      var val = input.value || '';
      var label = labelOfInput(input);
      var isTare = label.indexOf('Tare') >= 0;

      // 删除键
      if (key === 'del') {
        var newVal = val.slice(0, -1);
        if (isTare && (newVal.trim() === '' || newVal === '-')) {
          newVal = '0';
        }
        setVal(input, newVal);
        input.focus();
        return;
      }

      // 小数点
      if (key === '.') {
        if (val.indexOf('.') >= 0) return;  // 禁止多个小数点
        if (isTare && (val.trim() === '')) {
          setVal(input, '0.');
        } else {
          setVal(input, val + '.');
        }
        input.focus();
        return;
      }

      // 数字键：对 Tare 做“替换 0 / 替换选中”的逻辑
      var digit = key;
      if (isNaN(parseInt(digit, 10))) return;
      var selectedAll = false;
      try {
        selectedAll = (typeof input.selectionStart === 'number' &&
                       input.selectionStart === 0 &&
                       input.selectionEnd === val.length);
      } catch (e) {
        selectedAll = false;
      }

      if (isTare && (val.trim() === '' || val.trim() === '0' || selectedAll)) {
        // 当为 0 / 空 / 全选时，使用新数字直接替换
        setVal(input, digit);
      } else {
        setVal(input, val + digit);
      }
      input.focus();
    });
  });
})();
</script>
"""
    components.html(_keypad_html, height=220)


def render_enter_workflow_js():
    """
    Gross Enter→Tare; Tare Enter→Confirm.
    Phase 2 integration: transition buffer prevents digits lost during rerun.
    Phase 4: Enter frozen guard prevents duplicate characters.
    """
    html = """
    <script>
    (function(){
      function findAppDoc() {
        var d = window.parent.document;
        var hasInputs = d.querySelectorAll && d.querySelectorAll('[data-testid="stTextInput"]').length > 0;
        if (hasInputs) return d;
        try {
          var iframes = window.parent.document.querySelectorAll('iframe');
          for (var i = 0; i < iframes.length; i++) {
            var idoc = iframes[i].contentDocument;
            if (idoc && idoc.querySelectorAll('[data-testid="stTextInput"]').length > 0) return idoc;
          }
        } catch (e) {}
        if (window.parent.parent && window.parent.parent.document) {
          d = window.parent.parent.document;
          if (d.querySelectorAll('[data-testid="stTextInput"]').length > 0) return d;
        }
        return window.parent.document;
      }
      var doc = findAppDoc();
      var pWin = doc.defaultView || window.parent;

      function findByLabel(kw) {
        var blocks = doc.querySelectorAll('[data-testid="stTextInput"]');
        for (var i = 0; i < blocks.length; i++) {
          var block = blocks[i];
          if ((block.textContent || '').indexOf(kw) >= 0) {
            var inp = block.querySelector('input');
            if (inp) return inp;
          }
        }
        return null;
      }
      function findBtn(txt) {
        var btns = doc.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
          if ((btns[i].textContent || '').indexOf(txt) >= 0) return btns[i];
        }
        return null;
      }
      function labelOf(el) {
        if (!el || !el.closest) return '';
        var w = el.closest('[data-testid="stTextInput"]');
        if (!w) return '';
        var lb = w.querySelector('label');
        if (lb) return (lb.textContent || '').trim();
        return (w.textContent || '').trim().split(/[\r\n]/)[0] || '';
      }

      /* ── Phase 2: transition buffer system (persists on parent across reruns) ── */
      if (!doc.__ts) {
        doc.__ts = { active: false, target: null, buf: [], timer: null };

        pWin.__tsFlush = function() {
          var ts = doc.__ts;
          if (!ts.active || !ts.target) return false;
          var blocks = doc.querySelectorAll('[data-testid="stTextInput"]');
          var inp = null;
          for (var i = 0; i < blocks.length; i++) {
            var lb = blocks[i].querySelector('label');
            if (lb && lb.textContent.indexOf(ts.target) >= 0) {
              inp = blocks[i].querySelector('input');
              break;
            }
          }
          if (!inp || inp.disabled || !inp.isConnected) return false;

          if (ts.buf.length > 0) {
            var val = inp.value || '';
            for (var j = 0; j < ts.buf.length; j++) {
              var k = ts.buf[j];
              if (k === 'del') val = val.slice(0, -1);
              else if (k === '.' && val.indexOf('.') >= 0) continue;
              else val += k;
            }
            var setter = pWin.HTMLInputElement && Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, 'value');
            if (setter && setter.set) setter.set.call(inp, val);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
          }
          inp.focus();
          doc.__kpLastInput = inp;
          ts.active = false;
          ts.buf = [];
          ts.target = null;
          if (ts.timer) { pWin.clearInterval(ts.timer); ts.timer = null; }
          return true;
        };

        doc.addEventListener('keydown', function(e) {
          var ts = doc.__ts;
          if (!ts.active) return;
          if ((e.key >= '0' && e.key <= '9') || e.key === '.') {
            e.preventDefault(); e.stopImmediatePropagation();
            ts.buf.push(e.key);
          } else if (e.key === 'Backspace') {
            e.preventDefault(); e.stopImmediatePropagation();
            ts.buf.push('del');
          }
        }, true);
      }

      /* ── Phase 2: Enter frozen guard — prevent duplicate characters ── */
      if (!doc.__enterGuardBound) {
        doc.__enterGuardBound = true;
        doc.__enterFrozen = false;
        doc.__enterFrozenValue = '';
        doc.__enterFrozenLabel = '';
        doc.addEventListener('input', function(ev) {
          if (!doc.__enterFrozen) return;
          if (ev.target && ev.target.tagName === 'INPUT') {
            var evLabel = labelOf(ev.target);
            if (evLabel && evLabel === doc.__enterFrozenLabel) {
              var setter = pWin.HTMLInputElement && Object.getOwnPropertyDescriptor(pWin.HTMLInputElement.prototype, 'value');
              if (setter && setter.set) setter.set.call(ev.target, doc.__enterFrozenValue);
            }
          }
        }, true);
      }

      /* ── Enter keydown handler ── */
      function onKey(e) {
        if (e.key !== 'Enter') return;
        var a = doc.activeElement;
        if (!a || a.tagName !== 'INPUT') return;
        var lbl = labelOf(a);

        // Tare: do NOT intercept — let browser native st.form submit handle Enter
        if (lbl.indexOf('Tare') >= 0) return;

        var isTarget = lbl.indexOf('Gross') >= 0 || lbl.indexOf('Price') >= 0;
        if (!isTarget) return;

        e.preventDefault();
        e.stopImmediatePropagation();
        e.stopPropagation();

        doc.__enterFrozen = true;
        doc.__enterFrozenValue = a.value;
        doc.__enterFrozenLabel = lbl;
        a.blur();

        if (lbl.indexOf('Gross') >= 0) {
          var ts = doc.__ts;
          ts.active = true;
          ts.target = 'Tare';
          ts.buf = [];
          if (ts.timer) pWin.clearInterval(ts.timer);
          ts.timer = pWin.setInterval(function() { pWin.__tsFlush(); }, 50);
          pWin.setTimeout(function() {
            if (ts.active) { pWin.__tsFlush(); ts.active = false; ts.buf = []; if (ts.timer) { pWin.clearInterval(ts.timer); ts.timer = null; } }
          }, 3000);
          var b = findBtn('\\u2192Tare');
          if (b) b.click();
        } else if (lbl.indexOf('Price') >= 0) {
          var g = findByLabel('Gross');
          if (g && !g.disabled) g.focus();
        }

        pWin.setTimeout(function() { doc.__enterFrozen = false; }, 600);
      }

      function onKeyUp(e) {
        if (e.key !== 'Enter') return;
        var a = doc.activeElement || e.target;
        if (a && a.tagName === 'INPUT') {
          var lbl = labelOf(a);
          // Only intercept keyup for Gross and Price, let Tare through for form submit
          if (lbl.indexOf('Gross') >= 0 || lbl.indexOf('Price') >= 0) {
            e.preventDefault();
            e.stopImmediatePropagation();
          }
        }
      }

      if (doc.__enterHandler) doc.removeEventListener('keydown', doc.__enterHandler, true);
      if (doc.__enterUpHandler) doc.removeEventListener('keyup', doc.__enterUpHandler, true);
      doc.__enterHandler = onKey;
      doc.__enterUpHandler = onKeyUp;
      doc.addEventListener('keydown', onKey, true);
      doc.addEventListener('keyup', onKeyUp, true);

      /* flush on every rerun if transition still in progress */
      if (doc.__ts.active) pWin.__tsFlush();

      /* hide switch-button row + disable autocomplete */
      setTimeout(function(){
        var b = findBtn('\\u2192Tare');
        if (b) {
          var row = b.closest('[data-testid="stHorizontalBlock"]');
          if (row) row.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;opacity:0';
        }
        ['Price','Gross','Tare'].forEach(function(kw) {
          var inp = findByLabel(kw);
          if (inp) inp.setAttribute('autocomplete', 'off');
        });
      }, 20);
    })();
    </script>
    """
    components.html(html, height=0)


def focus_js(target: str, unique_id: int = 0):
    """Auto-focus Gross or Tare input after material selection.
    Bug 1 fix: aggressive retry schedule up to 500ms to handle slow reruns."""
    label_keyword = "Gross" if target == "gross" else "Tare"
    html = f"""
    <!-- focus_{unique_id} -->
    <script>
    (function(){{
      var doc = window.parent.document;
      if (!doc.querySelectorAll('[data-testid="stTextInput"]').length && window.parent.parent && window.parent.parent.document) {{
        doc = window.parent.parent.document;
      }}
      var done = false;
      function go() {{
        if (done) return;
        var blocks = doc.querySelectorAll('[data-testid="stTextInput"]');
        for (var i = 0; i < blocks.length; i++) {{
          var block = blocks[i];
          if ((block.textContent || '').indexOf('{label_keyword}') >= 0) {{
            var inp = block.querySelector('input');
            if (inp && !inp.disabled) {{
              inp.focus();
              if (doc) doc.__kpLastInput = inp;
              done = true;
              return;
            }}
          }}
        }}
      }}
      go();
      if (!done) setTimeout(go, 30);
      if (!done) setTimeout(go, 80);
      if (!done) setTimeout(go, 150);
      if (!done) setTimeout(go, 300);
      if (!done) setTimeout(go, 500);
    }})();
    </script>
    """
    components.html(html, height=0)
