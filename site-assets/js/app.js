/* ============================================================
   HBR 公开阅读站 — 搜索交互（无第三方库，无跟踪器）
   源文件位于 public-reader/site-assets/js/app.js，
   由 scripts/build_site.py 复制进 site/assets/js/。
   依赖：data/comics.json
   模式由 rights_manifest.json 的 modes 决定；默认 public-index。

   v011 变化（Brief v011）：
   - **browse 客户端渲染整体删除**：browse.html 已改为重定向到首页
     （首页即全量缩略图墙，静态预渲染），不再需要 results/pager/筛选 UI；
   - **修复缩略图双重拼接 bug（v010 遗留）**：comics.json 的 thumb 字段值
     已带目录前缀（assets/comics/thumbs/CM_XXXX.jpg），旧代码又拼了一次
     './assets/comics/thumbs/' → 请求 404，browse/search 页缩略图全裂。
     现在统一取 basename 后再拼（与 Python 端 Path(...).name 口径一致）；
   - 搜索结果按 gallery_order（系列优先归组）排序，与首页一致；
   - 卡片视觉与首页 card_html 对齐：缩略图 + 标题 + 日期 + 系列轻标签。
   ============================================================ */
(function () {
  "use strict";

  var state = { mode: "public-index", comics: [] };

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
  /* thumb 字段值形如 assets/comics/thumbs/CM_0001.jpg（带目录前缀）。
     统一取 basename 后再拼路径——**不要再直接拼前缀**（v010 踩过的坑）。 */
  function thumbSrc(c) {
    if (!c.thumb) return "";
    return "./assets/comics/thumbs/" + String(c.thumb).split("/").pop();
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

  function fail(title, detail) {
    var host = $("s-results");
    if (!host) return;
    host.innerHTML = '<div class="notice"><strong>' + esc(title) + "</strong>" +
      esc(detail || "") + " 请刷新重试；若持续失败，请通过仓库 Issues 反馈。</div>";
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
      var c0 = $("s-count"); if (c0) c0.textContent = "";
      return;
    }
    var hits = state.comics.filter(function (c) {
      var hay = (c.title + " " + (c.date || "") + " " + (c.series || "") + " " + c.item_id + " " +
                 (c.sources || []).map(function (s) { return s.raw_title || ""; }).join(" "))
                .toLowerCase();
      return hay.indexOf(q) !== -1;
    }).sort(function (a, b) { return a.gallery_order - b.gallery_order; });

    var c = $("s-count");
    if (c) c.textContent = "命中 " + hits.length + " / " + state.comics.length + " 话";
    if (!hits.length) {
      host.innerHTML = '<div class="empty"><p><strong>没有找到「' + esc(q) + '」。</strong></p>'
        + "<p>本站只收录《炽焰天穹》官方四格漫画的正式篇名，不编造人物或剧情标签，"
        + "因此按角色名搜索可能无结果。可试试日期或系列名。</p></div>";
      return;
    }
    host.innerHTML = '<div class="grid gallery-grid">' + hits.slice(0, 60).map(cardHTML).join("") + "</div>" +
      (hits.length > 60 ? '<p class="result-count">仅显示前 60 条，请缩小关键词范围。</p>' : "");
  }

  function cardHTML(c) {
    var thumb = thumbSrc(c)
      ? '<span class="card-thumb"><img src="' + esc(thumbSrc(c)) +
        '" alt="' + esc("《" + c.title + "》（" + (c.date || "") + "）漫画缩略图") +
        '" width="' + (c.thumb_width || 480) + '" height="' + (c.thumb_height || 673) +
        '" loading="lazy" decoding="async"></span>' : "";
    var meta = [];
    if (c.series) meta.push('<span class="cseries">' + esc(c.series) + "</span>");
    if (!c.canonical_official) meta.push('<span class="cflag">民间汉化</span>');
    meta.push('<span class="cdate">' + esc(c.date) + "</span>");
    return '<a class="card" href="./comic/' + esc(c.item_id) + '/">' + thumb +
      '<span class="ct">' + esc(c.title) + "</span>" + meta.join("") + "</a>";
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
    if ($("s-q")) bootSearch();
  });

  // 供测试与调试
  window.HBRSite = { state: state, runSearch: runSearch };
})();
