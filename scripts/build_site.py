#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v012 build_site.py — 由 data/*.json + media/ 生成可发布的静态站点（site/）。

v012 变化（Brief v012「三导航 / 关于页 / 去系列块级标题」）：

- **去掉跨网格系列分组标题**（SD-12.1）：v011 在每组首张上方插入的
  `group-lead`（横跨整网格 + 底边线）会被读成「章节标题」，使后续独立篇
  看起来从属于上一个系列。首页/搜索卡片不再生成该结构，也不再带
  `cseries` 系列轻标签（默认优先不加标签，网格保持干净）；
  系列连续性由 gallery_order 的相邻性表达，语义零变化；
- **主导航只剩 漫画 / 搜索 / 关于**（SD-12.2）：品牌名单独显示，不算导航项；
  新增 `about.html`（SD-12.3）；不恢复 rights.html；
- **新增关于页 `build_about()`**：这个网站是什么 / 当前收录（统计由数据生成，
  不手写数字）/ 首页排列规则（与 gallery_order 算法一致）/ 系列情况
  （名称+话数+第一话轻量链接）/ 图片来源与署名；
- **旧 series 页面保留为不出导航的兼容页**（SD-12.2）：series.html 与
  series/<slug>/ 仍可访问（0 个 404），页首加兼容说明；
- 阅读页 / 署名 / 上下话 / 完整图 / gallery_order 不退化（SD-12.4）。

生成：
    site/index.html                 首页（连续缩略图墙，无系列块级标题）
    site/about.html                 关于这个漫画库（数据自动统计）
    site/browse.html                旧入口重定向到首页
    site/search.html                搜索（客户端）
    site/series.html                系列列表（兼容保留，不在导航）
    site/series/<slug>/index.html   系列详情（6 页，兼容保留，不在导航）
    site/comic/<id>/index.html      单话页（213 页，静态预渲染）
    site/404.html
    site/data/*.json                紧凑版目录数据（构建时从 data/ 复制）
    site/assets/comics/<id>.<ext>   完整阅读图（由 build_media.py 导出后复制）
    site/assets/comics/thumbs/<id>.jpg  缩略图
    site/.nojekyll

设计口径：
- **全部相对路径**，GitHub Pages 任意子路径可用；
- 首页/单话页/系列页/关于页静态预渲染 → 固定 URL + 无 JS 也可读核心内容；
- 搜索客户端渲染 → 213 条轻量 JSON，避免重复构建；
- 所有来源文字与 HTML 属性一律经 esc() 转义。
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PUBLIC = SCRIPT_DIR.parent                      # public-reader/
DATA = PUBLIC / "data"
SITE = PUBLIC / "site"
ASSETS_SRC = PUBLIC / "site-assets"             # 自制素材源码（不进构建产物目录）
MEDIA_SRC = PUBLIC / "media" / "comics"         # build_media.py 导出的公开媒体

SITE_TITLE = "炽焰天穹 · 四格漫画"
SITE_DESC = "《炽焰天穹》(Heaven Burns Red) 官方四格漫画阅读站，" \
            "全部话数完整图片，每话附来源与署名。"
REPO_HINT = "https://github.com/DeepWaterrrrr/hbr-comic-reader"

# v011：首页缩略图墙前 N 张 eager 加载（首屏），其余 lazy（SD-11.3）
EAGER_CARDS = 10

# ── 每个 item 的公开再分发授权状态 ─────────────────────────────────────────
# 来源：public-reader/data/rights_manifest.json + media_manifest.json。
# v010：用户在 Brief 中明确声明已取得公开发布授权（民间汉化亦可分享），
# rights_manifest 记为 user_declared；build_media.py 只为授权范围内的条目
# 生成媒体文件。本脚本以「media_manifest 是否有该 item 的记录」为最终判据：
# 有记录 → 渲染 <img>；无记录 → 占位图 + 官方原帖入口。
RIGHTS_FILE = DATA / "rights_manifest.json"
MEDIA_FILE = DATA / "media_manifest.json"


def die(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def load(name: str):
    p = DATA / name
    if not p.is_file():
        die(f"缺少 {p.name}，请先运行 scripts/build_catalog.py")
    return json.loads(p.read_text(encoding="utf-8"))


def rights_index() -> dict[str, dict]:
    """返回 {item_id: media_record}；仅有授权范围内且已导出媒体的条目有条目级记录。

    v010 判据以 build_media.py 产出的 media_manifest.json 为准：
    该文件只为 rights_manifest 中 user_declared / approved 类别覆盖的条目生成记录。
    """
    try:
        mm = json.loads(MEDIA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {r["item_id"]: r for r in mm.get("records", [])}


# ══════════════════════════════════════════════════════════════════════════
#  HTML 骨架
# ══════════════════════════════════════════════════════════════════════════

# v012 SD-12.2：主导航只剩 漫画 / 搜索 / 关于 三项（品牌名单独显示，不算导航项）
NAV = [
    ("index.html", "漫画"),
    ("search.html", "搜索"),
    ("about.html", "关于"),
]

FOOTER = """<footer class="site-footer">
  <div class="wrap">
    <p>《炽焰天穹》(Heaven Burns Red) 官方四格漫画原作权利归 WFS / Key 及官方运营方所有。
       本站为非官方爱好者整理站，图片经收藏者授权声明公开（状态 user_declared，
       无书面许可材料，不虚称已核验）；每一话图片下方均标注来源与署名。
       若您认为内容不当，请通过<a href="{repo}/issues">仓库 Issues</a> 联系，将立即处理。</p>
    <p>数据由项目 manifest 自动生成，最后构建：{built}。
       站点无跟踪器、无 Cookie、无第三方请求。
       <a href="{prefix}about.html">关于这个漫画库</a></p>
  </div>
</footer>"""


def page(title: str, prefix: str, body: str, current: str = "",
         desc: str = SITE_DESC, built: str = "", extra_head: str = "") -> str:
    nav = "".join(
        f'<a href="{prefix}{href}"'
        + (' aria-current="page"' if href == current else "") + f">{label}</a>"
        for href, label in NAV
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<link rel="icon" href="{prefix}assets/img/placeholder.svg" type="image/svg+xml">
<link rel="stylesheet" href="{prefix}assets/css/style.css">
{extra_head}</head>
<body>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{prefix}index.html">炽焰天穹 <small>四格漫画</small></a>
    <nav class="nav" aria-label="主导航">{nav}</nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
{FOOTER.replace("{built}", esc(built))
        .replace("{repo}", REPO_HINT)
        .replace("{prefix}", prefix)}
<script src="{prefix}assets/js/app.js" defer></script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════
#  阅读组件（授权开关）
# ══════════════════════════════════════════════════════════════════════════

def render_reader(c: dict, rights: dict, prefix: str) -> str:
    """单话页的图像区（位于「来源与署名」区正上方）。

    - media_manifest 有该 item 记录（授权范围内已导出媒体）→ 输出完整图片
      `<img loading="lazy" decoding="async">`，保留原始宽高属性；
    - 其余（未授权 / 未导出）→ 自制中性占位图 + 官方原帖入口。
    """
    rec = rights.get(c["item_id"])
    if rec and c.get("image"):
        src = f"{prefix}assets/comics/{Path(c['image']).name}"
        return f"""<figure class="reader">
  <img src="{src}" alt="{esc(c['title'])}（第 {c['reading_index']} 话）完整漫画"
       width="{c['image_width']}" height="{c['image_height']}"
       loading="lazy" decoding="async">
  <figcaption class="result-count">{esc(c['title'])} · {esc(c['date'])} ·
    存档画质 {c['image_width']}×{c['image_height']}</figcaption>
</figure>"""

    official_src = next((s for s in c["sources"] if s["official"]), None)
    link = official_src["url"] if official_src else (
        c["sources"][0]["url"] if c["sources"] else "https://www.bilibili.com")
    reason = ("本站未取得该话完整图像的公开发布授权，因此不提供站内整图。"
              if rec is None and not c.get("image") else
              "该话的公开媒体尚未导出，暂时不提供站内整图。")
    return f"""<div class="reader">
  <div class="placeholder">
    <img src="{prefix}assets/img/placeholder.svg" alt="" width="72" height="72"
         loading="lazy" decoding="async">
    <span class="ph-title">完整图像暂不提供在线查看</span>
    <span class="ph-note">{esc(reason)}请前往官方原帖阅读：</span>
    <a class="btn btn-primary" href="{esc(link)}" rel="noopener noreferrer"
       target="_blank">前往官方原帖 ↗</a>
  </div>
</div>"""


# ══════════════════════════════════════════════════════════════════════════
#  来源与署名（Brief v010 §3A：完整漫画图片正下方，必须可见）
# ══════════════════════════════════════════════════════════════════════════

def sources_block(c: dict) -> str:
    """来源链接清单：类型（动态/专栏）+ 原始链接 + 日期 + 状态徽标；一话多来源全保留。"""
    items = []
    for s in c["sources"]:
        badge = ['<span class="badge badge-official">官方</span>'
                 if s["official"] else
                 '<span class="badge badge-unofficial">非官方</span>']
        if s["status"] == "deleted":
            badge.append('<span class="badge badge-deleted">原帖已删除</span>')
        elif s["status"] == "unverified":
            badge.append('<span class="badge">可达性未验证</span>')
        detail = s.get("status_detail") or ""
        date_txt = f'发布于 {esc(s["date"])}' if s.get("date") else ""
        items.append(
            f'<li><span class="sl-head">'
            f'<span class="badge badge-type">{esc(s["type_label"])}</span>'
            f'<a href="{esc(s["url"])}" rel="noopener noreferrer" target="_blank">'
            f'{esc(s["url"])}</a> ' + " ".join(badge) + "</span>"
            + (f'<div class="sl-detail">{date_txt}</div>' if date_txt else "")
            + (f'<div class="sl-detail">{esc(detail)}</div>' if detail else "")
            + (f'<div class="sl-detail">原始标题：{esc(s["raw_title"])}</div>'
               if s.get("raw_title") else "")
            + (f'<div class="sl-detail">{esc(s["note"])}</div>'
               if s.get("note") else "")
            + "</li>")
    return ('<h3>来源链接</h3><ul class="source-list">' + "".join(items) + "</ul>")


def attribution_block(c: dict) -> str:
    """「来源与署名」区：位于完整漫画图片正下方（Brief §3A）。"""
    a = c.get("attribution") or {}
    work = a.get("work") or {}
    acct = a.get("official_account") or {}
    artist = a.get("artist") or {}
    tr = a.get("translator")

    def row(label: str, value_html: str) -> str:
        return f'<div class="attr-row"><dt>{label}</dt><dd>{value_html}</dd></div>'

    # 作品 / 原作
    work_html = (f'《{esc(work.get("title"))}》{esc(work.get("type"))}；'
                 f'权利方：{esc(work.get("rights_holders"))}。'
                 f'<span class="attr-dim">{esc(work.get("rights_note"))}</span>')

    # 官方发布账号 + 本话官方发布
    if acct.get("name"):
        acct_html = (f'<a href="{esc(acct["url"])}" rel="noopener noreferrer" '
                     f'target="_blank">{esc(acct["name"])}</a>'
                     f'<span class="badge badge-official">已认证官方账号</span>'
                     f'<span class="attr-dim">（{esc(acct.get("evidence"))}）</span>'
                     f'<div class="attr-dim">本话的官方动态 / 专栏见下方「来源链接」。</div>')
    else:
        acct_html = '<span class="attr-dim">未标注/待核实</span>'

    # 漫画作者 / 绘者（仅有证据时填写）
    if artist.get("name"):
        artist_html = (f'{esc(artist["name"])}'
                       f'<span class="attr-dim">（{esc(artist.get("evidence"))}）</span>')
    else:
        artist_html = '<span class="attr-dim">未标注/待核实</span>'

    # 翻译 / 汉化（适用时）
    if tr:
        tr_html = (f'汉化组：<strong>{esc(tr.get("group"))}</strong>'
                   f'<span class="attr-dim">（{esc(tr.get("evidence"))}）</span><br>'
                   f'发布者：<a href="{esc(tr.get("uploader_url"))}" '
                   f'rel="noopener noreferrer" target="_blank">'
                   f'{esc(tr.get("uploader"))}</a>'
                   f'<span class="attr-dim">（B站用户，mid {esc(tr.get("uploader_mid"))}；'
                   f'原帖：<a href="{esc(tr.get("source_url"))}" '
                   f'rel="noopener noreferrer" target="_blank">'
                   f'{esc(tr.get("source_url"))}</a>）</span>')
    else:
        tr_html = '<span class="attr-dim">不适用（官方简体原版）</span>'

    # 版本说明
    version_label = {"official": "官方版", "fan_translation": "民间汉化版"}.get(
        a.get("version"), a.get("version") or "—")
    ver_html = (f'<strong>{esc(version_label)}</strong>'
                f'<span class="attr-dim">{esc(a.get("version_note"))}</span>')

    return f"""<section class="attribution" aria-label="来源与署名">
  <h2>来源与署名</h2>
  <dl class="attr-list">
    {row("作品 / 原作", work_html)}
    {row("官方发布账号", acct_html)}
    {row("漫画作者 / 绘者", artist_html)}
    {row("翻译 / 汉化", tr_html)}
    {row("版本说明", ver_html)}
  </dl>
  {sources_block(c)}
</section>"""


def exception_block(c: dict) -> str:
    ex = c.get("exception")
    if not ex:
        return ""
    hist = "".join(
        f'<li>{esc(h.get("flagged_at"))} 标记待复核：{esc(h.get("reason"))}'
        f'（{esc(h.get("resolved_at"))} 解决：{esc(h.get("resolution"))}）</li>'
        for h in ex.get("history") or [])
    return f"""<div class="notice">
  <strong>⚠️ 本话采用民间汉化版本，非官方内容</strong>
  本话的官方原帖已被官方删除、完整原图不可再生，因此本项目经收藏者裁定，
  采用民间汉化组译制的完整竖版作为存档图像（<code>official_source=false</code>，
  非官方简体原图）。按 Brief v010 的用户授权声明，该民间汉化版本在本站公开分享，
  页面已完整标注汉化来源与署名；若官方恢复原帖，将换回官方完整原图。
  <ul>{hist}</ul>
</div>"""


def pager_block(c: dict, by_id: dict, prefix: str) -> str:
    prev_c = by_id.get(c["prev_id"])
    next_c = by_id.get(c["next_id"])

    def cell(target: dict, cls: str, label: str) -> str:
        if not target:
            return (f'<span class="{cls} disabled"><span class="pl">{label}</span>'
                    '<span class="pt">没有了</span></span>')
        return (f'<a class="{cls}" href="{prefix}comic/{esc(target["item_id"])}/">'
                f'<span class="pl">{label}</span>'
                f'<span class="pt">{esc(target["title"])}</span></a>')

    return ('<nav class="pager" aria-label="上一话 / 下一话">'
            + cell(prev_c, "prev", "‹ 上一话")
            + cell(next_c, "next", "下一话 ›")
            + "</nav>")


def card_html(c: dict, prefix: str, series_pos: tuple[int, int] | None = None,
              eager: bool = False) -> str:
    """漫画卡片（v012 SD-12.1：真实缩略图、contain 不裁切）。

    series_pos = (k, n)：该话在系列内的序号与系列话数。**仅系列详情页
    （兼容保留页）传入**；首页与搜索卡片不传（默认优先不加系列标签，
    避免任何把后续独立篇误认作系列成员的视觉结构）。
    eager：首屏卡片（前 EAGER_CARDS 张）立即加载，其余惰性。
    """
    thumb_src = f"{prefix}assets/comics/thumbs/{esc(Path(c['thumb']).name)}"
    loading = "eager" if eager else "lazy"
    fetch = ' fetchpriority="high"' if eager else ""
    alt = f"《{c['title']}》（{c['date']}）漫画缩略图"
    img = (f'<img src="{thumb_src}" alt="{esc(alt)}" '
           f'width="{c.get("thumb_width") or 480}" '
           f'height="{c.get("thumb_height") or 673}" '
           f'loading="{loading}" decoding="async"{fetch}>')
    meta = []
    if series_pos:
        k, n = series_pos
        meta.append(f'<span class="cseries">{esc(c["series"])} · {k}/{n}</span>')
    if not c["canonical_official"]:
        meta.append('<span class="cflag">民间汉化</span>')
    meta.append(f'<span class="cdate">{esc(c["date"])}</span>')
    return (f'<a class="card" href="{prefix}comic/{esc(c["item_id"])}/">'
            f'<span class="card-thumb">{img}</span>'
            f'<span class="ct">{esc(c["title"])}</span>'
            + "".join(meta) + "</a>")


def fmt_date(d: str) -> str:
    if not d:
        return "日期不详"
    p = d.split("-")
    return f"{p[0]} 年 {int(p[1])} 月 {int(p[2])} 日" if len(p) == 3 else d


# ══════════════════════════════════════════════════════════════════════════
#  页面构建
# ══════════════════════════════════════════════════════════════════════════

def build_index(comics, series, rights, built) -> str:
    """首页 = 连续漫画缩略图墙（v012 SD-12.1：无跨网格系列块级标题）。

    排序仍用 gallery_order（系列连续组 + 组内官方顺序），同系列的话依旧挨着；
    但**不再插入任何横跨网格的系列标题/分组横条**——v011 的 group-lead 会被
    读成「章节标题」，使紧随其后的独立篇看起来从属于上一个系列（Brief §1）。
    卡片也不再带系列轻标签（SD-12.1 默认优先不加标签）；系列信息见关于页。
    """
    ordered = sorted(comics, key=lambda c: c["gallery_order"])
    cards = [card_html(c, "./", series_pos=None, eager=i < EAGER_CARDS)
             for i, c in enumerate(ordered)]

    body = f"""<div class="gallery-head">
  <h1>全部 {len(comics)} 话</h1>
  <p class="gh-count">同系列的话挨着排列，整体按发布时间从旧到新 ·
     <a href="./about.html">关于</a> · <a href="./search.html">搜索</a></p>
</div>
<div class="grid gallery-grid">
{"".join(cards)}
</div>"""
    return page(SITE_TITLE, "./", body, current="index.html", built=built)


def build_browse(built) -> str:
    """旧「浏览全部」入口（SD-11.1）：重定向到新版首页的完整浏览体验。

    保留 HTML 页（不 404）：meta refresh 即时跳转 + JS 兜底 + 可见说明链接，
    兼容已被分享出去的旧链接与旧书签。
    """
    body = """<section class="hero">
  <h1>浏览全部漫画</h1>
  <p class="lead">「浏览全部」已并入首页——全部漫画的缩略图墙现在就在首页，
     按系列与发布时间排列。正在带你过去……</p>
  <p><a class="btn btn-primary" href="./index.html">进入漫画缩略图墙 →</a></p>
</section>"""
    head = ('<meta http-equiv="refresh" content="0; url=./index.html">'
            '<link rel="canonical" href="./index.html">'
            "<script>location.replace('./index.html')</script>")
    return page("浏览全部 · " + SITE_TITLE, "./", body, built=built, extra_head=head)


def build_search(built) -> str:
    body = """<section class="hero">
  <h1>搜索</h1>
  <p class="lead">支持正式标题、发布日期（如 <code>2026-06</code>）、系列名与编号。</p>
  <p class="gh-count">本站只收录官方正式篇名，不编造人物、剧情或标签，
     因此按角色名搜索可能没有结果。</p>
</section>

<div class="toolbar">
  <div class="field" style="flex:1 1 260px">
    <label for="s-q">关键词</label>
    <input id="s-q" type="search" placeholder="例如：乐队的危机 / 2026-06 / 第31A部队"
           autocomplete="off" style="min-width:100%">
  </div>
  <span class="result-count" id="s-count"></span>
</div>

<div id="s-results"><div class="empty"><p>输入关键词开始搜索。</p></div></div>"""
    return page("搜索 · " + SITE_TITLE, "./", body, current="search.html", built=built)


def build_about(comics, series, built) -> str:
    """关于页（v012 SD-12.3「关于这个漫画库」）。

    自然中文小标题 + 段落；不用巨大 Hero、统计卡片排或营销文案。
    **所有统计与系列清单由 comics.json / series.json 现算**——Brief 明确要求
    数据更新后关于页数字不得过期，因此本函数不接受任何手写话数。
    """
    n = len(comics)
    ns = len(series)
    n_members = sum(s["count"] for s in series)
    n_standalone = n - n_members
    dates = sorted(c["date"] for c in comics if c.get("date"))
    first_d, last_d = (dates[0], dates[-1]) if dates else ("日期不详", "日期不详")
    n_readable = sum(1 for c in comics if c.get("image"))
    by_id = {c["item_id"]: c for c in comics}

    # 系列清单：名称 + 话数 + 日期范围 + 第一话轻量链接（不重建大卡片导航）
    series_rows = []
    for s in series:
        members = sorted((by_id[i] for i in s["item_ids"] if i in by_id),
                         key=lambda m: m["series_order"])
        first = members[0] if members else None
        if first:
            t = first["title"]
            short = t if len(t) <= 12 else t[:12] + "…"
            link = (f' — <a href="./comic/{esc(first["item_id"])}/">'
                    f'从「{esc(short)}」开始读</a>')
        else:
            link = ""
        series_rows.append(
            f'<li><strong>{esc(s["name"])}</strong>'
            f'（{s["count"]} 话，{esc(s["first_date"])} → {esc(s["last_date"])}）'
            f'{link}</li>')

    # CM_0111 特例说明（唯一非官方 canonical，R25 破例转正）
    c111 = by_id.get("CM_0111")
    c111_txt = (f'<code>CM_0111</code>「{esc(c111["title"])}」' if c111
                else "唯一一话民间汉化")

    body = f"""<section class="hero">
  <h1>关于这个漫画库</h1>
  <p class="lead">这是一个由爱好者整理、面向玩家的《炽焰天穹》四格漫画阅读站。
     这里说明它是什么、收了什么、首页怎么排、图片从哪来。</p>
</section>

<div class="prose">
  <h2>这个网站是什么</h2>
  <p>这是一个<strong>非官方</strong>的漫画整理与阅读站，与 WFS / Key 及官方运营方
     无从属关系，也不冒充官方。《炽焰天穹》(Heaven Burns Red) 四格漫画的图像、
     原作与相关权利归原权利人所有。本站公开完整图片的依据是收藏者的授权声明
     （状态记为 <code>user_declared</code>）——本项目<strong>未持有书面许可材料</strong>，
     因此不声称已核验书面授权；每一话图片下方都标注了来源与署名。若您认为内容不当，
     请通过仓库 Issues 联系，将立即处理。</p>

  <h2>当前收录</h2>
  <p>共收录 <strong>{n} 话</strong>四格漫画，全部可以在站内阅读完整图片
     （当前 {n_readable} 话已启用）。其中已确认的系列 <strong>{ns} 个</strong>、
     共 {n_members} 话；其余 <strong>{n_standalone} 话</strong>为独立篇，
     未发现官方系列体例证据。收录时间覆盖 {esc(first_d)} 至 {esc(last_d)}
     （按官方发布时间）。</p>

  <h2>首页排列规则</h2>
  <p>漫画大体按发布时间从旧到新排列。如果几话明确属于同一个系列，就把它们放在一起，
     方便连续阅读。整个系列的位置取决于它最早一话的发布日期；系列内部按已经确认的
     官方顺序排列。因此偶尔会看到日期不完全连续的情况，这是为了保证系列不被拆开。
     同一系列的话在首页是挨着的，但首页<strong>不用系列标题把网格分区</strong>——
     系列只影响排列顺序，不影响页面结构。</p>

  <h2>系列情况</h2>
  <p>目前确认 {ns} 个系列（顺序与话数由分类数据自动生成）：</p>
  <ul class="about-series">
    {''.join(series_rows)}
  </ul>

  <h2>图片来源与署名</h2>
  <p>每一话的完整图片下方都有「来源与署名」区：可点击的官方动态 / 专栏原帖链接、
     官方发布账号、漫画作者、翻译 / 汉化信息与版本说明。官方文本没有署名的，
     一律显示「未标注 / 待核实」，<strong>不猜作者</strong>。</p>
  <p>{c111_txt}是唯一使用民间汉化完整版的话：官方原动态已被删除、完整原图不可再生，
     经收藏者裁定采用汉化工房九九组译制的版本（发布者 StuartRiki_鍵視），
     页面已明确标注 <code>official_source=false</code>，不冒充官方；
     将来官方若恢复原帖，会换回官方完整原图。</p>
  <p>本站不跟踪访客：无 Cookie、无分析脚本、无第三方请求。</p>
</div>"""
    return page("关于这个漫画库 · " + SITE_TITLE, "./", body,
                current="about.html", built=built)


def build_series_page(series, comics, built) -> str:
    by_id = {c["item_id"]: c for c in comics}
    cards = "".join(
        f'<a class="card" href="./series/{esc(s["slug"])}/">'
        f'<span class="cid">{s["count"]} 话</span>'
        f'<span class="ct">{esc(s["name"])}</span>'
        f'<span class="cm">{esc(s["first_date"])} → {esc(s["last_date"])}</span></a>'
        for s in series)
    body = f"""<section class="hero">
  <h1>系列</h1>
  <p class="lead">共 {len(series)} 个系列、{sum(s["count"] for s in series)} 话。
     系列内顺序依据官方合辑展示体例与连载体例确定，不猜测官方话数。</p>
  <p class="gh-count">此页为旧链接兼容保留，未在导航中展示；
     首页漫画墙中同一系列的话仍然挨着排列，见<a href="./about.html">关于页</a>的排列规则说明。</p>
</section>

<div class="notice">
  <strong>其余 {len(comics) - sum(s["count"] for s in series)} 话为独立篇</strong>，
  未发现官方系列体例证据，在<a href="./index.html">漫画缩略图墙</a>中按发布时间排列。
</div>

<div class="grid">{cards}</div>

<section class="section">
  <h2>系列判定依据</h2>
  <div class="table-scroll"><table class="data">
    <tr><th>系列</th><th>话数</th><th>阅读顺序依据</th><th>包含话数（编号）</th></tr>
    {"".join(
        f'<tr><td>{esc(s["name"])}</td><td class="num">{s["count"]}</td>'
        f'<td>{esc(s["order_basis"])}</td>'
        f'<td class="num">{"、".join(esc(i) for i in s["item_ids"])}</td></tr>'
        for s in series)}
  </table></div>
</section>"""
    return page("系列 · " + SITE_TITLE, "./", body, current="series.html", built=built)


def build_series_detail(s: dict, by_id: dict, built: str) -> str:
    members = [by_id[i] for i in s["item_ids"] if i in by_id]
    if len(members) != len(s["item_ids"]):
        die(f"系列 {s['name']} 有 item_id 不在 comics 中")
    order_note = {
        "rule_based": "依据官方合辑动态的图片展示顺序（与发帖顺序一致）",
        "manual": "经人工核对官方连载体例后确定",
    }.get(s.get("order_basis"), s.get("order_basis") or "按官方证据确定")

    cards = "".join(
        card_html(c, "../../", series_pos=(c["series_order"], len(members)))
        for c in members)

    body = f"""<nav aria-label="面包屑" class="result-count" style="padding:14px 0 0">
  <a href="../../index.html">漫画</a> ›
  <a href="../../series.html">系列</a> › {esc(s["name"])}
</nav>
<section class="hero">
  <h1>{esc(s["name"])}</h1>
  <p class="lead">{s["count"]} 话 · {esc(s["first_date"])} → {esc(s["last_date"])}</p>
</section>

<div class="notice info"><strong>阅读顺序</strong>{esc(order_note)}。
   每一话都提供官方原帖链接。</div>

<div class="grid gallery-grid">{cards}</div>

<p style="margin-top:18px"><a href="../../index.html">← 返回全部漫画</a></p>"""
    return page(f"{s['name']} · 系列 · " + SITE_TITLE, "../../", body, built=built)


def build_comic_page(c: dict, by_id: dict, rights: dict, built: str) -> str:
    badges = []
    if c["series"]:
        badges.append(f'<span class="badge badge-series">系列：{esc(c["series"])}'
                      f'（第 {c["series_order"]} 话）</span>')
    badges.append('<span class="badge badge-official">官方来源</span>'
                  if c["canonical_official"] else
                  '<span class="badge badge-unofficial">民间汉化</span>')
    if any(s["status"] == "deleted" for s in c["sources"]):
        badges.append('<span class="badge badge-deleted">官方原帖已删除</span>')

    meta = (f'<span>全站第 <strong>{c["reading_index"]}</strong> / {len(by_id)} 话</span>'
            f'<span>发布于 {esc(fmt_date(c["date"]))}</span>'
            f'<span>编号 {esc(c["item_id"])}</span>'
            f'<span>存档画质 {c["canonical_width"]}×{c["canonical_height"]}</span>')

    body = f"""<nav aria-label="面包屑" class="result-count" style="padding:14px 0 0">
  <a href="../../index.html">漫画</a> › {esc(c["item_id"])}
</nav>

<header class="comic-head">
  <span class="cid">{esc(c["item_id"])}</span>
  <h1>{esc(c["title"])}</h1>
  <div class="comic-meta">{meta}</div>
  <div>{" ".join(badges)}</div>
</header>

{exception_block(c)}
{render_reader(c, rights, "../../")}
{attribution_block(c)}
{pager_block(c, by_id, "../../")}

<p><a href="../../index.html">← 返回全部漫画</a></p>"""
    return page(f"{c['title']} · {SITE_TITLE}", "../../", body, built=built,
                desc=f"《炽焰天穹》官方四格漫画「{c['title']}」（{c['date']}）"
                     f"——官方原帖链接与存档信息。")


def build_404(built) -> str:
    body = """<section class="hero">
  <h1>404 — 页面不存在</h1>
  <p class="lead">你访问的地址可能已变更，或该话尚未收录。</p>
</section>
<div class="cta-row">
  <a class="btn btn-primary" href="./index.html">全部漫画</a>
  <a class="btn" href="./search.html">搜索</a>
  <a class="btn" href="./about.html">关于</a>
</div>"""
    return page("404 · " + SITE_TITLE, "./", body, built=built)


# ══════════════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(description="由 data/*.json + media/ 构建静态站点")
    ap.add_argument("--out", default=None,
                    help="输出目录（默认 public-reader/site；用于临时目录比对构建）")
    args = ap.parse_args()
    out_dir = Path(args.out).resolve() if args.out else SITE

    built = datetime.date.today().isoformat()
    comics = load("comics.json")
    series = load("series.json")
    rights = json.loads(RIGHTS_FILE.read_text(encoding="utf-8"))
    r_index = rights_index()

    by_id = {c["item_id"]: c for c in comics}
    if len(by_id) != len(comics):
        die("comics.json 中存在重复 item_id")

    # ── 原子构建：先写到临时目录，成功后整体替换 ──────────────────────────
    # 避免构建中途失败/被杀时留下半成品 site/（v009 实测踩过这个坑：
    # validate_site.py 重跑构建时父进程超时被杀，导致 site/ 只剩部分文件）。
    # --out 指定目录时：直接写入该目录（调用方负责目录是全新的）。
    if args.out:
        if out_dir.exists():
            die(f"--out 目录已存在：{out_dir}")
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        build_into(out_dir, comics, series, rights, r_index, by_id, built)
        final_dir = out_dir
    else:
        tmp = PUBLIC / ".build_tmp"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)

        try:
            build_into(tmp, comics, series, rights, r_index, by_id, built)
            # 替换旧 site/
            if SITE.exists():
                shutil.rmtree(SITE, ignore_errors=True)
            os.replace(tmp, SITE)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        final_dir = SITE

    n_html = len(list(final_dir.rglob("*.html")))
    total_kb = sum(p.stat().st_size for p in final_dir.rglob("*")
                   if p.is_file() and ".git" not in p.parts) / 1024
    n_img = len(list(final_dir.glob("assets/comics/*.*"))) + \
        len(list(final_dir.glob("assets/comics/thumbs/*.jpg")))
    n_readable = sum(1 for c in comics if c.get("image"))
    print(f"✅ 站点构建完成：{n_html} 个 HTML，合计 {total_kb:.0f} KB")
    print(f"   单话页 {len(comics)} · 系列页 {len(series)} · 顶层页 6"
          f"（首页漫画墙 / 关于 / browse 重定向 / 搜索 / 系列兼容页 / 404）")
    print(f"   数据：comics.json / series.json / rights_manifest.json / "
          f"media_manifest.json（紧凑版）")
    print(f"   媒体：{n_img} 个图片文件（全图 + 缩略图），"
          f"可站内阅读 {n_readable} / {len(comics)} 话")
    print(f"   输出：{final_dir}")


def build_into(root: Path, comics, series, rights, r_index, by_id, built: str) -> None:
    """把站点写入 root（root 必须是全新的空目录）。"""
    # 数据（紧凑版，客户端加载用）
    (root / "data").mkdir(parents=True, exist_ok=True)
    for name in ("comics.json", "series.json", "rights_manifest.json",
                 "media_manifest.json"):
        obj = json.loads((DATA / name).read_text(encoding="utf-8"))
        (root / "data" / name).write_text(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 自制素材（源码在 site-assets/，构建时带入产物；site/ 本身是纯产物）
    shutil.copytree(ASSETS_SRC, root / "assets")

    # 公开媒体（build_media.py 导出；site/ 内为副本，源在 public-reader/media/）
    if MEDIA_SRC.is_dir():
        shutil.copytree(MEDIA_SRC, root / "assets" / "comics")
    else:
        die("media/ 不存在：请先运行 scripts/build_media.py 导出公开图片")

    (root / ".nojekyll").write_text("# GitHub Pages: bypass Jekyll\n", encoding="utf-8")

    # 静态页（v012：browse = 重定向页；rights 页已删除；series 为兼容保留页）
    (root / "index.html").write_text(build_index(comics, series, rights, built), encoding="utf-8")
    (root / "about.html").write_text(build_about(comics, series, built), encoding="utf-8")
    (root / "browse.html").write_text(build_browse(built), encoding="utf-8")
    (root / "search.html").write_text(build_search(built), encoding="utf-8")
    (root / "series.html").write_text(build_series_page(series, comics, built), encoding="utf-8")
    (root / "404.html").write_text(build_404(built), encoding="utf-8")

    # 系列详情
    for s in series:
        d = root / "series" / s["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_series_detail(s, by_id, built), encoding="utf-8")

    # 单话页
    for c in comics:
        d = root / "comic" / c["item_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(build_comic_page(c, by_id, r_index, built), encoding="utf-8")


if __name__ == "__main__":
    main()
