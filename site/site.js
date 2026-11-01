// Progressive enhancement only: the page is fully readable without JavaScript.
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.remove("nojs"); root.classList.add("js");

  // Persona tabs (keyboard accessible: arrow keys, Home, End)
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function select(tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (focus) tab.focus();
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { select(t, false); });
    t.addEventListener("keydown", function (e) {
      var j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); select(tabs[j], true); }
    });
  });
  if (tabs.length) select(tabs[0], false);

  // "Copy" buttons on command blocks
  document.querySelectorAll("pre.term").forEach(function (pre) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "copy"; b.textContent = "Copy";
    b.setAttribute("aria-label", "Copy these commands");
    b.addEventListener("click", function () {
      var text = pre.cloneNode(true);
      var btn = text.querySelector(".copy"); if (btn) btn.remove();
      var lines = text.textContent.split("\n").filter(function (l) { return /^\$ /.test(l.trim()) || /^\s+--/.test(l); })
        .map(function (l) { return l.replace(/^\s*\$ /, ""); });
      var out = lines.length ? lines.join("\n") : text.textContent;
      (navigator.clipboard ? navigator.clipboard.writeText(out) : Promise.reject()).then(function () {
        b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1600);
      }, function () { b.textContent = "Press Ctrl+C"; setTimeout(function () { b.textContent = "Copy"; }, 2000); });
    });
    pre.appendChild(b);
  });
})();
