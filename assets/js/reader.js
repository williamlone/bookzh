/* 阅读站点交互：目录折叠、字号/夜间模式、本地阅读进度（不渲染正文，不依赖外部库） */
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

  var root = document.documentElement;

  /* ---------------- 字号：三档，只作用于正文 ---------------- */

  var FONT_KEY = "bookzh:font";
  var FONT_LEVELS = ["s", "m", "l"];
  var font = safeGet(FONT_KEY);
  if (FONT_LEVELS.indexOf(font) === -1) font = "m";
  root.setAttribute("data-font", font);

  var fontSmaller = document.querySelector("[data-font-smaller]");
  var fontLarger = document.querySelector("[data-font-larger]");

  function stepFont(delta) {
    var next = FONT_LEVELS.indexOf(font) + delta;
    if (next < 0 || next >= FONT_LEVELS.length) return;
    font = FONT_LEVELS[next];
    root.setAttribute("data-font", font);
    safeSet(FONT_KEY, font);
  }

  if (fontSmaller) {
    fontSmaller.addEventListener("click", function () {
      stepFont(-1);
    });
  }
  if (fontLarger) {
    fontLarger.addEventListener("click", function () {
      stepFont(1);
    });
  }

  /* ---------------- 夜间模式：持久化 ---------------- */

  var NIGHT_KEY = "bookzh:night";
  var nightBtn = document.querySelector("[data-night-toggle]");
  var isNight = safeGet(NIGHT_KEY) === "1";

  function applyNight(on) {
    isNight = on;
    root.classList.toggle("night", on);
    if (nightBtn) {
      nightBtn.setAttribute("aria-pressed", on ? "true" : "false");
      nightBtn.textContent = on ? "日间" : "夜间";
    }
  }

  applyNight(isNight);

  if (nightBtn) {
    nightBtn.addEventListener("click", function () {
      applyNight(!isNight);
      safeSet(NIGHT_KEY, isNight ? "1" : "0");
    });
  }

  /* ---------------- 简介折叠（书籍页） ---------------- */

  var summary = document.querySelector("[data-summary]");
  var summaryBtn = document.querySelector("[data-summary-toggle]");

  if (summary && summaryBtn) {
    summary.classList.add("is-collapsed");
    if (summary.scrollHeight > summary.clientHeight + 4) {
      summaryBtn.hidden = false;
      summaryBtn.addEventListener("click", function () {
        var collapsed = summary.classList.toggle("is-collapsed");
        summaryBtn.textContent = collapsed ? "展开" : "收起";
      });
    } else {
      summary.classList.remove("is-collapsed");
    }
  }

  /* ---------------- 目录：展开全部 / 收起全部 ---------------- */

  var expandAll = document.querySelector("[data-toc-expand]");
  var collapseAll = document.querySelector("[data-toc-collapse]");

  function setAllVolumes(open) {
    var volumes = document.querySelectorAll("details.volume");
    for (var i = 0; i < volumes.length; i += 1) {
      volumes[i].open = open;
    }
  }

  if (expandAll) {
    expandAll.addEventListener("click", function () {
      setAllVolumes(true);
    });
  }
  if (collapseAll) {
    collapseAll.addEventListener("click", function () {
      setAllVolumes(false);
    });
  }

  /* ---------------- 目录抽屉（章节页） ---------------- */

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

  // 点目录里的任一链接（章节或书名）后自动收起
  if (toc) {
    toc.addEventListener("click", function (event) {
      var node = event.target;
      while (node && node !== toc) {
        if (node.tagName === "A") {
          closeDrawer();
          return;
        }
        node = node.parentNode;
      }
    });
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

  // 书籍页：显示上次读到的章节，高亮目录并展开所在卷
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
            var weight = links[i].getAttribute("data-weight");
            if (continueBtn && weight) {
              continueBtn.textContent = "继续阅读 · 第 " + weight + " 章";
            }
            var volume = links[i].closest("details.volume");
            if (volume) volume.open = true;
            break;
          }
        }
      }
    }
  }

  // 从章节页点“卷”跳回书籍页时，展开对应的卷
  if (window.location.hash) {
    var hash = window.location.hash.slice(1);
    try {
      hash = decodeURIComponent(hash);
    } catch (err) {
      /* 保留原值 */
    }
    var target = document.getElementById(hash);
    if (target && target.tagName === "DETAILS") target.open = true;
  }
})();
