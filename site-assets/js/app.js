/* ============================================================
   HBR 公开阅读站 — 浏览 / 搜索 / 阅读交互（无第三方库，无跟踪器）
   源文件位于 public-reader/site-assets/js/app.js，
   由 scripts/build_site.py 复制进 site/assets/js/。
   依赖：data/comics.json、data/series.json、data/rights_manifest.json
   模式由 rights_manifest.json 的 modes 决定；默认 public-index。
   ============================================================ */
(function () {
  "use strict";

  var PAGE_SIZE = 24;
  var state = { mode: "public-index", comics: [], series: [], view: [] };
  var els = {};

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtDate(d) {
    if (!d) return "日期不详";
    var p = String(d).split("-");
    return p.length === 3 ? p[0] + " 年 " + Number(p[1]) + " 月 " + Number(p[2]) + " 日" : d;
  }

  /* ---------- 数据加载（相对路径，GitHub Pages 子路径安全） ---------- */
  function loadJSON(rel, cb) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", rel, true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      if (xhr.status !== 200) { cb(new Error("HTTP " + xhr.status + " for " + rel)); return; }
      try { cb(null, JSON.parse(xhr.responseText)); }
      catch (e) { cb(e); }
    };
    xhr.send();
  }

  function bootBrowse() {
    loadJSON("./data/comics.json", function (e, comics) {
      if (e) { fail("漫画目录加载失败", e.message); return; }
      loadJSON("./data/rights_manifest.json", function (e2, rights) {
        if (!e2 && rights && rights.modes) {
          state.mode = rights.modes["licensed-reader"] && rights.modes["licensed-reader"].enabled
            ? "licensed-reader" : "public-index";
        }
        state.comics = comics;
        loadJSON("./data/series.json", function (e3, series) {
          state.series = e3 ? [] : series;
          initFilters();
          apply();
        });
      });
    });
  }

  function fail(title, detail) {
    var host = $("results");
    if (!host) return;
    host.innerHTML = '<div class="notice"><strong>' + esc(title) + "</strong>" +
      esc(detail || "") + " 请刷新重试；若持续失败，请通过仓库 Issues 反馈。</div>";
  }

  /* ---------- 筛选器 ---------- */
  function initFilters() {
    var sel = $("f-series");
    if (sel) {
      var opts = ['<option value="">全部（含独立篇）</option>'];
      state.series.forEach(function (s) {
        opts.push('<option value="' + esc(s.name) + '">' + esc(s.name) +
                  "（" + s.count + " 话）</option>");
      });
      opts.push('<option value="__standalone__">独立篇（无系列）</option>');
      sel.innerHTML = opts.join("");
    }
    ["f-series", "f-sort", "f-q"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      var ev = el.tagName === "SELECT" ? "change" : "input";
      el.addEventListener(ev, function () { state.page = 1; apply(); });
    });
  }

  function currentQuery() {
    var q = ($("f-q") && $("f-q").value || "").trim().toLowerCase();
    var series = $("f-series") ? $("f-series").value : "";
    var sort = $("f-sort") ? $("f-sort").value : "new";
    return { q: q, series: series, sort: sort };
  }

  function apply() {
    var f = currentQuery();
    var list = state.comics.filter(function (c) {
      if (f.series === "__standalone__" && c.series) return false;
      if (f.series && f.series !== "__standalone__" && c.series !== f.series) return false;
      if (f.q) {
        var hay = (c.title + " " + (c.date || "") + " " + (c.series || "") + " " +
                   c.item_id + " " +
                   (c.sources || []).map(function (s) { return s.raw_title || ""; }).join(" "))
                  .toLowerCase();
        if (hay.indexOf(f.q) === -1) return false;
      }
      return true;
    });

    list.sort(function (a, b) {
      if (f.sort === "old") return a.reading_index - b.reading_index;
      if (f.sort === "reading") return a.reading_index - b.reading_index;
      return b.reading_index - a.reading_index;   // new
    });

    state.view = list;
    renderCount(list.length, state.comics.length);
    renderPage(1);
  }

  function renderCount(shown, total) {
    var el = $("count");
    if (el) el.textContent = "共 " + total + " 话，当前显示 " + shown + " 话";
  }

  function renderPage(page) {
    state.page = page;
    var total = state.view.length;
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page > pages) page = pages;
    var start = (page - 1) * PAGE_SIZE;
    var slice = state.view.slice(start, start + PAGE_SIZE);

    var host = $("results");
    if (!host) return;

    if (!total) {
      host.innerHTML = '<div class="empty"><p><strong>没有匹配的漫画。</strong></p>' +
        "<p>试试清空筛选条件，或用更短的关键词。</p></div>";
      $("pager").innerHTML = "";
      return;
    }

    host.innerHTML = '<div class="grid">' + slice.map(cardHTML).join("") + "</div>";
    renderPager(page, pages);
  }

  function cardHTML(c) {
    var badges = [];
    if (c.series) badges.push('<span class="badge badge-series">' + esc(c.series) + "</span>");
    badges.push(c.canonical_official
      ? '<span class="badge badge-official">官方</span>'
      : '<span class="badge badge-unofficial">民间汉化</span>');
    if ((c.sources || []).some(function (s) { return s.status === "deleted"; })) {
      badges.push('<span class="badge badge-deleted">官方原帖已删除</span>');
    }
    var thumb = c.thumb
      ? '<span class="card-thumb"><img src="./assets/comics/thumbs/' + esc(c.thumb) +
        '" alt="" loading="lazy" decoding="async"></span>' : "";
    return '<a class="card" href="./comic/' + esc(c.item_id) + '/">' + thumb +
      '<span class="cid">#' + c.reading_index + " · " + esc(c.item_id) + "</span>" +
      '<span class="ct">' + esc(c.title) + "</span>" +
      '<span class="cm">' + fmtDate(c.date) + "</span>" +
      '<span class="badge">' + badges.join(" ") + "</span></a>";
  }

  function renderPager(page, pages) {
    var host = $("pager");
    if (!host) return;
    if (pages <= 1) { host.innerHTML = ""; return; }
    var html = ['<div class="pagination" role="navigation" aria-label="分页">'];
    html.push('<button type="button" data-p="' + (page - 1) + '"' +
              (page === 1 ? " disabled" : "") + ' aria-label="上一页">‹ 上一页</button>');
    var from = Math.max(1, page - 2), to = Math.min(pages, page + 2);
    if (from > 1) html.push('<button type="button" data-p="1">1</button>' +
                            (from > 2 ? '<span class="result-count">…</span>' : ""));
    for (var i = from; i <= to; i++) {
      html.push('<button type="button" data-p="' + i + '"' +
                (i === page ? ' aria-current="true"' : "") + ">" + i + "</button>");
    }
    if (to < pages) html.push((to < pages - 1 ? '<span class="result-count">…</span>' : "") +
                              '<button type="button" data-p="' + pages + '">' + pages + "</button>");
    html.push('<button type="button" data-p="' + (page + 1) + '"' +
              (page === pages ? " disabled" : "") + ' aria-label="下一页">下一页 ›</button>');
    html.push('<span class="result-count">第 ' + page + " / " + pages + " 页</span>");
    html.push("</div>");
    host.innerHTML = html.join("");
    Array.prototype.forEach.call(host.querySelectorAll("button[data-p]"), function (b) {
      b.addEventListener("click", function () {
        var p = Number(b.getAttribute("data-p"));
        if (p >= 1) { renderPage(p); window.scrollTo(0, 0); }
      });
    });
  }

  /* ---------- 搜索页 ---------- */
  function bootSearch() {
    loadJSON("./data/comics.json", function (e, comics) {
      if (e) { fail("索引加载失败", e.message); return; }
      state.comics = comics;
      var input = $("s-q");
      if (!input) return;
      var params = new URLSearchParams(window.location.search);
      if (params.get("q")) input.value = params.get("q");
      input.addEventListener("input", debounce(runSearch, 160));
      runSearch();
    });
  }

  function runSearch() {
    var q = ($("s-q").value || "").trim().toLowerCase();
    var host = $("s-results");
    if (!host) return;
    if (!q) {
      host.innerHTML = '<div class="empty"><p>输入标题关键词、日期（如 <code>2026-06</code>）'
        + "或系列名开始搜索。</p><p>共收录 " + state.comics.length + " 话。</p></div>";
      var c = $("s-count"); if (c) c.textContent = "";
      return;
    }
    var hits = state.comics.filter(function (c) {
      var hay = (c.title + " " + (c.date || "") + " " + (c.series || "") + " " + c.item_id + " " +
                 (c.sources || []).map(function (s) { return s.raw_title || ""; }).join(" "))
                .toLowerCase();
      return hay.indexOf(q) !== -1;
    }).sort(function (a, b) { return a.reading_index - b.reading_index; });

    var c = $("s-count");
    if (c) c.textContent = "命中 " + hits.length + " / " + state.comics.length + " 话";
    if (!hits.length) {
      host.innerHTML = '<div class="empty"><p><strong>没有找到「' + esc(q) + '」。</strong></p>'
        + "<p>本站只收录《炽焰天穹》官方四格漫画的正式篇名，不编造人物或剧情标签，"
        + "因此按角色名搜索可能无结果。可试试日期或系列名。</p></div>";
      return;
    }
    host.innerHTML = '<div class="grid">' + hits.slice(0, 60).map(cardHTML).join("") + "</div>" +
      (hits.length > 60 ? '<p class="result-count">仅显示前 60 条，请缩小关键词范围。</p>' : "");
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  /* ---------- 启动 ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    if ($("results")) bootBrowse();
    else if ($("s-results")) bootSearch();
  });

  // 供测试与调试
  window.HBRSite = { state: state, apply: apply, renderPage: renderPage };
})();
