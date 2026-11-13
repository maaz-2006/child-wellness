/* Kito — progressive enhancement only.
   Every page must work with this file absent. Nothing here is load-bearing. */

(function () {
  "use strict";

  // Confirm destructive actions: <button data-confirm="Delete this record?">
  document.addEventListener("click", function (event) {
    var target = event.target.closest("[data-confirm]");
    if (!target) return;
    if (!window.confirm(target.getAttribute("data-confirm"))) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });

  // Auto-dismiss flash messages after a respectful delay.
  document.querySelectorAll(".flash").forEach(function (el) {
    window.setTimeout(function () {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      window.setTimeout(function () { el.remove(); }, 450);
    }, 6000);
  });

  // Mark the current time on any element that wants it (used by check-in forms).
  document.querySelectorAll("[data-now]").forEach(function (el) {
    var now = new Date();
    el.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  });
})();
