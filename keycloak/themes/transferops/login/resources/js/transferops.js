(function () {
  "use strict";

  var STORAGE_KEY = "transferops-theme";

  function preferredTheme() {
    try {
      var stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "dark" || stored === "light") return stored;
    } catch (_error) {
      // Storage may be unavailable in private mode; the OS preference still works.
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme, button) {
    var dark = theme === "dark";
    document.documentElement.classList.toggle("pf-v5-theme-dark", dark);
    if (button) {
      button.textContent = dark ? "☀" : "☾";
      button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      button.setAttribute("title", dark ? "Switch to light theme" : "Switch to dark theme");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var header = document.getElementById("kc-header");
    if (header) {
      var toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "transferops-theme-toggle";
      var theme = preferredTheme();
      applyTheme(theme, toggle);
      toggle.addEventListener("click", function () {
        theme = document.documentElement.classList.contains("pf-v5-theme-dark")
          ? "light"
          : "dark";
        try {
          localStorage.setItem(STORAGE_KEY, theme);
        } catch (_error) {
          // The selection lasts for this page even when storage is unavailable.
        }
        applyTheme(theme, toggle);
      });
      header.appendChild(toggle);
    }

    var main = document.querySelector(".pf-v5-c-login__main");
    if (main) {
      var brand = document.createElement("div");
      brand.className = "transferops-form-brand";

      var mark = document.createElement("span");
      mark.className = "transferops-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "⌁";

      var name = document.createElement("strong");
      name.textContent = "Transfer & Conversion Intelligence Platform";

      var section = document.createElement("span");
      section.className = "transferops-section";
      section.textContent = "ANALYTICS & REPORTING";

      brand.appendChild(mark);
      brand.appendChild(name);
      brand.appendChild(section);
      main.prepend(brand);
    }

    var title = document.getElementById("kc-page-title");
    if (title && title.parentElement) {
      var subtitles = {
        "Sign in": "Access is restricted to authorised transfer-programme users.",
        "Create account": "Create your identity, then verify your work email to continue.",
        "Reset your password": "We will send a time-limited recovery link to your work email.",
        "Verify your email": "Open the message we sent to confirm that this address belongs to you.",
        "Choose a password": "Use a strong, unique password for your platform account."
      };
      var subtitle = document.createElement("p");
      subtitle.className = "transferops-subtitle";
      subtitle.textContent = subtitles[title.textContent.trim()] || "Secure account access.";
      title.insertAdjacentElement("afterend", subtitle);
    }
  });
})();
