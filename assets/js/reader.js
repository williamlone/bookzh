/* 阅读站点交互：移动端目录抽屉 + 本地阅读进度（不渲染正文，不依赖外部库） */
(function () {
  "use strict";

  function safeGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (err) {
      return null;
    }
  }

  function safeSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (err) {
      /* 隐私模式等场景下忽略 */
    }
  }

  /* ---------------- 移动端目录抽屉 ---------------- */

  var toc = document.querySelector("[data-toc]");
  var toggle = document.querySelector("[data-toc-toggle]");
  var closeBtn = document.querySelector("[data-toc-close]");
  var overlay = document.querySelector("[data-toc-overlay]");

  function openDrawer() {
    if (!toc) return;
    toc.classList.add("is-open");
    if (overlay) {
      overlay.hidden = false;
      overlay.classList.add("is-open");
    }
    if (toggle) toggle.setAttribute("aria-expanded", "true");
    document.body.classList.add("drawer-open");
  }

  function closeDrawer() {
    if (!toc) return;
    toc.classList.remove("is-open");
    if (overlay) {
      overlay.classList.remove("is-open");
      overlay.hidden = true;
    }
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("drawer-open");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      if (toc.classList.contains("is-open")) closeDrawer();
      else openDrawer();
    });
  }
  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  if (overlay) overlay.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });
  if (window.matchMedia) {
    var mq = window.matchMedia("(min-width: 901px)");
    var onChange = function (event) {
      if (event.matches) closeDrawer();
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }

  /* ---------------- 阅读进度 ---------------- */

  var prefix = "bookzh:progress:";
  var reading = document.querySelector("[data-progress-key]");

  // 章节页：记录当前地址和标题
  if (reading) {
    var key = reading.getAttribute("data-progress-key");
    var title = reading.getAttribute("data-progress-title") || document.title;
    if (key) {
      safeSet(
        prefix + key,
        JSON.stringify({ href: window.location.pathname, title: title })
      );
    }
  }

  // 书籍页：显示上次读到的章节，并高亮目录
  var book = document.querySelector("[data-book-key]");
  if (book) {
    var bookKey = book.getAttribute("data-book-key");
    var note = document.querySelector("[data-progress-note]");
    var noteLink = document.querySelector("[data-progress-link]");
    var continueBtn = document.querySelector("[data-continue]");
    var raw = bookKey ? safeGet(prefix + bookKey) : null;

    if (raw) {
      var saved = null;
      try {
        saved = JSON.parse(raw);
      } catch (err) {
        saved = null;
      }
      if (saved && saved.href) {
        if (note && noteLink) {
          noteLink.href = saved.href;
          noteLink.textContent = saved.title || "上次读到的章节";
          note.hidden = false;
        }
        if (continueBtn) continueBtn.href = saved.href;

        var links = document.querySelectorAll("[data-chapter-link]");
        for (var i = 0; i < links.length; i += 1) {
          if (links[i].getAttribute("href") === saved.href) {
            links[i].classList.add("current");
            links[i].setAttribute("aria-current", "page");
            break;
          }
        }
      }
    }
  }
})();
