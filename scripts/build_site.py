#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v010 build_site.py — 由 data/*.json + media/ 生成可发布的静态站点（site/）。

生成：
    site/index.html                 首页
    site/browse.html                浏览（排序 / 系列筛选 / 分页，客户端渲染）
    site/search.html                搜索（客户端）
    site/series.html                系列列表
    site/series/<slug>/index.html   系列详情（6 页，静态预渲染）
    site/comic/<id>/index.html      单话页（213 页，静态预渲染）
    site/rights.html                版权与授权说明
    site/404.html
    site/data/*.json                紧凑版目录数据（构建时从 data/ 复制）
    site/assets/comics/<id>.<ext>   完整阅读图（由 build_media.py 导出后复制）
    site/assets/comics/thumbs/<id>.jpg  缩略图
    site/.nojekyll

v010 变化（Brief v010）：
- **licensed-reader 默认启用**：授权范围内（rights_manifest 为 user_declared /
  approved，且 build_media.py 已导出媒体）的单话页直接渲染完整图片；
  未授权条目仍走自制占位图 + 官方原帖链接分支；
- **每话图片下方新增「来源与署名」区**（Brief §3A）：作品/原作、官方发布账号、
  可点击来源链接（动态/专栏 + 日期 + 失效标记）、漫画作者（仅有证据时填写）、
  翻译/汉化署名（适用时）、版本说明；
- 列表卡片加载缩略图（惰性加载）；
- `built` 改为构建当天动态生成，不再写死。

设计口径：
- **全部相对路径**，GitHub Pages 任意子路径可用；
- 单话页 / 系列页静态预渲染 → 固定 URL + SEO + 无 JS 也可读核心信息；
- 浏览 / 搜索客户端渲染 → 213 条轻量 JSON，避免 200+ 页重复构建；
- 所有来源文字与 HTML 属性一律经 esc() 转义（Brief §3A 验收 6）。
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

SITE_TITLE = "炽焰天穹 HBR 四格漫画 · 公开阅读站"
SITE_DESC = "《炽焰天穹》(Heaven Burns Red) 官方四格漫画公开阅读站，" \
            "收录 213 话完整图片，每话附来源与署名。"
REPO_HINT = "https://github.com/DeepWaterrrrr/hbr-comic-reader"

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

NAV = [
    ("index.html", "首页"),
    ("browse.html", "浏览全部"),
    ("search.html", "搜索"),
    ("series.html", "系列"),
    ("rights.html", "版权与授权"),
]

FOOTER = """<footer class="site-footer">
  <div class="wrap">
    <p><strong>{title}</strong></p>
    <p>《炽焰天穹》(Heaven Burns Red) 官方四格漫画原作权利归 WFS / Key 及官方运营方所有。
       本站经收藏者授权声明（Brief v010，user_declared）公开完整图片，
       每一话图片下方均标注来源与署名；若您认为内容不当，请通过仓库 Issues 联系。</p>
    <p>数据由项目 manifest 自动生成，最后构建：{built}。
       站点无跟踪器、无 Cookie、无第三方请求。</p>
    <p><a href="{repo}">项目仓库</a> ·
       <a href="{prefix}rights.html">版权与授权说明</a> ·
       <a href="https://www.bilibili.com">哔哩哔哩</a></p>
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
    <a class="brand" href="{prefix}index.html">炽焰天穹 HBR<small>官方四格漫画 · 公开阅读站</small></a>
    <nav class="nav" aria-label="主导航">{nav}</nav>
  </div>
</header>
<main class="wrap">
{body}
</main>
{FOOTER.replace("{title}", esc(SITE_TITLE)).replace("{built}", esc(built))
        .replace("{repo}", REPO_HINT).replace("{prefix}", prefix)}
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


def card_html(c: dict, prefix: str) -> str:
    badges = []
    if c["series"]:
        badges.append(f'<span class="badge badge-series">{esc(c["series"])}</span>')
    badges.append('<span class="badge badge-official">官方</span>'
                  if c["canonical_official"] else
                  '<span class="badge badge-unofficial">民间汉化</span>')
    if any(s["status"] == "deleted" for s in c["sources"]):
        badges.append('<span class="badge badge-deleted">官方原帖已删除</span>')
    thumb = ""
    if c.get("thumb"):
        thumb = (f'<span class="card-thumb"><img src="{prefix}'
                 f'assets/comics/thumbs/{esc(Path(c["thumb"]).name)}" '
                 f'alt="" loading="lazy" decoding="async" '
                 f'width="{c.get("thumb_width") or 0}" '
                 f'height="{c.get("thumb_height") or 0}"></span>')
    return (f'<a class="card" href="{prefix}comic/{esc(c["item_id"])}/">'
            + thumb
            + f'<span class="cid">#{c["reading_index"]} · {esc(c["item_id"])}</span>'
            f'<span class="ct">{esc(c["title"])}</span>'
            f'<span class="cm">{esc(c["date"])}</span>'
            f'<span class="badge">' + " ".join(badges) + "</span></a>")


def fmt_date(d: str) -> str:
    if not d:
        return "日期不详"
    p = d.split("-")
    return f"{p[0]} 年 {int(p[1])} 月 {int(p[2])} 日" if len(p) == 3 else d


# ══════════════════════════════════════════════════════════════════════════
#  页面构建
# ══════════════════════════════════════════════════════════════════════════

def build_index(comics, series, rights, built) -> str:
    latest = sorted(comics, key=lambda c: c["reading_index"], reverse=True)[:8]
    n_official = sum(1 for c in comics if c["canonical_official"])
    n_unofficial = len(comics) - n_official
    first, last = comics[0]["date"], comics[-1]["date"]
    deleted = [c for c in comics if any(s["status"] == "deleted" for s in c["sources"])]

    series_cards = "".join(
        f'<a class="card" href="./series/{esc(s["slug"])}/">'
        f'<span class="cid">{s["count"]} 话 · {esc(s["first_date"])} → {esc(s["last_date"])}</span>'
        f'<span class="ct">{esc(s["name"])}</span>'
        f'<span class="cm">按官方证据确定的顺序排列</span></a>'
        for s in series)

    body = f"""<section class="hero">
  <h1>《炽焰天穹》官方四格漫画<br>公开阅读站</h1>
  <p class="lead">本站收录《炽焰天穹》(Heaven Burns Red) 官方四格漫画
     <strong>{len(comics)} 话</strong>完整图片，按「系列优先、时间其次」整理阅读顺序，
     每一话图片下方均附来源与署名。原作权利归 WFS / Key 及官方运营方所有，
     本站经收藏者授权声明公开分享，详见
     <a href="./rights.html">版权与授权</a>。</p>
</section>

<div class="notice info">
  <strong>关于本站的授权状态</strong>
  本站公开完整图片的依据是<strong>收藏者的授权声明</strong>（Brief v010，
  状态记为 <code>user_declared</code>——本项目未持有书面许可材料，不虚称已核验）。
  所有标题、日期、来源链接均取自官方公开发布内容；每一话都标注官方动态 / 专栏
  链接与已核实的署名信息。如权利方认为内容不当，请通过仓库 Issues 联系，将立即处理。
</div>

<div class="stats">
  <div class="stat"><b>{len(comics)}</b><span>收录话数（可站内阅读）</span></div>
  <div class="stat"><b>{len(series)}</b><span>系列 / {len(comics) - sum(s["count"] for s in series)} 独立篇</span></div>
  <div class="stat"><b>{n_official}</b><span>官方来源</span></div>
  <div class="stat"><b>{n_unofficial}</b><span>民间汉化（已标注）</span></div>
</div>

<div class="cta-row">
  <a class="btn btn-primary" href="./browse.html">浏览全部 {len(comics)} 话</a>
  <a class="btn" href="./search.html">搜索标题 / 日期</a>
  <a class="btn" href="./series.html">按系列阅读</a>
</div>

<section class="section">
  <h2>系列（按官方证据确定的顺序）</h2>
  <div class="grid">{series_cards}</div>
</section>

<section class="section">
  <h2>最新收录</h2>
  <div class="grid">{"".join(card_html(c, "./") for c in latest)}</div>
  <p><a href="./browse.html">查看全部 →</a></p>
</section>

<section class="section">
  <h2>收录范围与数据说明</h2>
  <div class="table-scroll"><table class="data">
    <tr><th>项目</th><th>说明</th></tr>
    <tr><td>时间范围</td><td>{esc(first)} → {esc(last)}（官方发布时间）</td></tr>
    <tr><td>阅读顺序</td><td>系列内按官方合辑/连载体例确定的顺序；独立篇与跨系列按发布时间推进</td></tr>
    <tr><td>标题来源</td><td>全部 {len(comics)} 话均为官方正式篇名，不编造、不猜测</td></tr>
    <tr><td>图像状态</td><td>{n_official} 话官方完整版 + {n_unofficial} 话民间汉化（已明确标注）</td></tr>
    <tr><td>官方原帖已删除</td><td>{len(deleted)} 话（{"、".join(esc(c["item_id"]) for c in deleted) or "无"}）</td></tr>
    <tr><td>署名</td><td>每话图片下方标注来源与署名；官方文本无署名的显示「未标注/待核实」，不猜作者</td></tr>
    <tr><td>数据生成</td><td>由项目 manifest 自动导出，可重跑构建；不手写目录</td></tr>
  </table></div>
</section>"""
    return page(SITE_TITLE, "./", body, current="index.html", built=built)


def build_browse(built) -> str:
    body = """<section class="hero">
  <h1>浏览全部漫画</h1>
  <p class="lead">可按发布时间或阅读顺序排列，并按系列筛选。</p>
</section>

<div class="toolbar">
  <div class="field">
    <label for="f-sort">排序</label>
    <select id="f-sort">
      <option value="new">最新发布</option>
      <option value="old">最早发布</option>
      <option value="reading">阅读顺序（系列优先）</option>
    </select>
  </div>
  <div class="field">
    <label for="f-series">系列</label>
    <select id="f-series"><option value="">加载中…</option></select>
  </div>
  <div class="field">
    <label for="f-q">关键词（可选）</label>
    <input id="f-q" type="search" placeholder="标题 / 日期 / 系列" autocomplete="off">
  </div>
  <span class="spacer"></span>
  <span class="result-count" id="count">加载中…</span>
</div>

<div id="results"><div class="empty"><p>正在加载目录数据…</p></div></div>
<div id="pager"></div>"""
    return page("浏览全部 · " + SITE_TITLE, "./", body, current="browse.html", built=built)


def build_search(built) -> str:
    body = """<section class="hero">
  <h1>搜索</h1>
  <p class="lead">支持正式标题、发布日期（如 <code>2026-06</code>）、系列名与编号。</p>
</section>

<div class="notice info">
  <strong>搜索范围说明</strong>
  本站只收录官方正式篇名，<strong>不编造人物、剧情或标签</strong>，
  因此按角色名搜索可能没有结果。
</div>

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
</section>

<div class="notice">
  <strong>其余 {len(comics) - sum(s["count"] for s in series)} 话为独立篇</strong>，
  未发现官方系列体例证据，按发布时间排列，见
  <a href="./browse.html">浏览全部</a>。
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
        f'<a class="card" href="../../comic/{esc(c["item_id"])}/">'
        + (f'<span class="card-thumb"><img src="../../'
           f'assets/comics/thumbs/{esc(Path(c["thumb"]).name)}" alt="" '
           f'loading="lazy" decoding="async" width="{c.get("thumb_width") or 0}" '
           f'height="{c.get("thumb_height") or 0}"></span>'
           if c.get("thumb") else "")
        + f'<span class="cid">系列内第 {c["series_order"]} 话 · 全站 #{c["reading_index"]}</span>'
        f'<span class="ct">{esc(c["title"])}</span>'
        f'<span class="cm">{esc(c["date"])}</span></a>'
        for c in members)

    body = f"""<nav aria-label="面包屑" class="result-count" style="padding:14px 0 0">
  <a href="../../index.html">首页</a> ›
  <a href="../../series.html">系列</a> › {esc(s["name"])}
</nav>
<section class="hero">
  <h1>{esc(s["name"])}</h1>
  <p class="lead">{s["count"]} 话 · {esc(s["first_date"])} → {esc(s["last_date"])}</p>
</section>

<div class="notice info"><strong>阅读顺序</strong>{esc(order_note)}。
   每一话都提供官方原帖链接。</div>

<div class="grid">{cards}</div>

<p style="margin-top:18px"><a href="../../browse.html">← 返回浏览全部</a></p>"""
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
  <a href="../../index.html">首页</a> ›
  <a href="../../browse.html">浏览全部</a> › {esc(c["item_id"])}
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

<p><a href="../../browse.html">← 返回目录</a></p>"""
    return page(f"{c['title']} · {SITE_TITLE}", "../../", body, built=built,
                desc=f"《炽焰天穹》官方四格漫画「{c['title']}」（{c['date']}）"
                     f"——官方原帖链接与存档信息。")


def build_rights(comics, series, rights, built) -> str:
    n_unofficial = sum(1 for c in comics if not c["canonical_official"])
    decl = rights.get("authorization_declaration") or {}
    cat_rows = "".join(
        f'<tr><td>{esc(cat["category"])}</td>'
        f'<td class="num">{cat.get("count") if cat.get("count") is not None else "—"}</td>'
        f'<td>{esc(", ".join(cat.get("usage_scope") or []) or "—")}</td>'
        f'<td><strong>{esc(cat.get("status"))}</strong></td>'
        f'<td>{esc(cat.get("evidence") or "（无）")}</td></tr>'
        for cat in rights.get("categories", []))

    body = f"""<section class="hero">
  <h1>版权与授权说明</h1>
  <p class="lead">本站公开《炽焰天穹》官方四格漫画的完整图片，
     本页说明权利归属、授权声明范围与署名口径。</p>
</section>

<div class="notice">
  <strong>一句话结论</strong>
  《炽焰天穹》(Heaven Burns Red) 官方四格漫画的著作权归 WFS / Key 及官方运营方所有。
  本站公开完整图片的依据是<strong>收藏者的授权声明</strong>（状态
  <code>user_declared</code>）：用户已明确说明「已经取得 HBR 漫画公开发布授权，
  希望所有 HBR 玩家能够直接在线阅读完整图片」，且<strong>民间汉化版本也可以公开分享</strong>。
  本项目<strong>未持有书面许可材料</strong>，因此不声称已核验书面授权；
  每一话图片下方均标注来源与署名，官方原帖已删除的也保留链接并标记状态。
</div>

<section class="section">
  <h2>授权声明范围（Brief v010 §3.4）</h2>
  <div class="table-scroll"><table class="data">
    <tr><th>项目</th><th>内容</th></tr>
    <tr><td>声明人</td><td>{esc(decl.get("declared_by"))}</td></tr>
    <tr><td>声明出处</td><td>{esc(decl.get("declared_in"))}</td></tr>
    <tr><td>覆盖范围</td><td>{esc(decl.get("scope"))}</td></tr>
    <tr><td>形式</td><td>{esc(decl.get("form"))}</td></tr>
    <tr><td>状态</td><td><strong>{esc(decl.get("status"))}</strong>（不虚称 written_license_verified）</td></tr>
    <tr><td>边界</td><td>{"；".join(esc(x) for x in decl.get("limits") or [])}</td></tr>
  </table></div>
</section>

<section class="section">
  <h2>授权状态清单</h2>
  <p class="result-count">状态取值：<code>user_declared</code>（用户明确声明授权，无书面材料）/
     <code>approved</code>（有可核实证据）/
     <code>not_verified</code>（无证据，默认值）/
     <code>excluded</code>（明确排除）。<code>user_declared</code> 与
     <code>approved</code> 均视为授权范围内可发布；无权类别不生成任何公开媒体。</p>
  <div class="table-scroll"><table class="data">
    <tr><th>内容类别</th><th>数量</th><th>允许用途</th><th>状态</th><th>证据</th></tr>
    {cat_rows}
  </table></div>
</section>

<section class="section">
  <h2>各话来源状态</h2>
  <div class="table-scroll"><table class="data">
    <tr><th>类别</th><th>话数</th><th>说明</th></tr>
    <tr><td>官方来源</td><td class="num">{len(comics) - n_unofficial}</td>
        <td>官方账号「炽焰天穹_HBR」发布的动态 / 专栏，站内提供完整图片并附原帖链接</td></tr>
    <tr><td>民间汉化</td><td class="num">{n_unofficial}</td>
        <td>CM_0111：官方原帖已删除、官方完整原图不可再生，经收藏者裁定采用民间汉化组
            译制的完整竖版；按用户授权声明在本站公开分享，页面明示汉化来源、
            汉化组署名与 <code>official_source=false</code> 标记，不冒充官方</td></tr>
    <tr><td>官方原帖已删除</td><td class="num">1</td>
        <td>CM_0111 绑定的官方动态已被官方删除，专栏正文不可见；站点保留原链接并标记「原帖已删除」</td></tr>
    <tr><td>归档封面图</td><td class="num">1</td>
        <td>用户授权声明未明确覆盖封面图，不生成公开媒体</td></tr>
    <tr><td>自制素材</td><td class="num">—</td>
        <td>占位图、样式与脚本均由本项目自制，无第三方内容，可自由使用</td></tr>
  </table></div>
</section>

<section class="section">
  <h2>署名口径</h2>
  <ul>
    <li>每一话图片下方都有「来源与署名」区：作品/原作、官方发布账号、来源链接
        （动态/专栏 + 日期 + 状态）、漫画作者、翻译/汉化、版本说明。</li>
    <li>漫画作者/绘者<strong>仅在官方文本或汉化原帖有明确署名时填写</strong>
        （如官方合辑动态正文「漫画：津留崎 优」）；未标注的一律显示「未标注/待核实」，
        <strong>不猜作者</strong>。</li>
    <li>民间汉化信息取自汉化原帖自述与发布者账号信息（cv36235931：
        汉化工房九九组 译，发布者 StuartRiki_鍵視），不凭空扩展人员名单。</li>
  </ul>
</section>

<section class="section">
  <h2>免责声明</h2>
  <ul>
    <li>本站为<strong>非官方</strong>的爱好者整理项目，与 WFS / Key / 官方运营方无从属关系。</li>
    <li>站内所有漫画标题、日期、来源链接均取自官方公开发布内容，未作改写。</li>
    <li><strong>署名与免责声明不等于转载许可。</strong>
        若权利方认为本站内容不当，请通过仓库 Issues 联系，将立即处理。</li>
    <li>本站不跟踪访客：无 Cookie、无分析脚本、无第三方请求。</li>
  </ul>
</section>"""
    return page("版权与授权 · " + SITE_TITLE, "./", body, current="rights.html", built=built)


def build_404(built) -> str:
    body = """<section class="hero">
  <h1>404 — 页面不存在</h1>
  <p class="lead">你访问的地址可能已变更，或该话尚未收录。</p>
</section>
<div class="cta-row">
  <a class="btn btn-primary" href="./index.html">返回首页</a>
  <a class="btn" href="./browse.html">浏览全部漫画</a>
  <a class="btn" href="./search.html">搜索</a>
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
    print(f"   单话页 {len(comics)} · 系列页 {len(series)} · 顶层页 6")
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

    # 静态页
    (root / "index.html").write_text(build_index(comics, series, rights, built), encoding="utf-8")
    (root / "browse.html").write_text(build_browse(built), encoding="utf-8")
    (root / "search.html").write_text(build_search(built), encoding="utf-8")
    (root / "series.html").write_text(build_series_page(series, comics, built), encoding="utf-8")
    (root / "rights.html").write_text(build_rights(comics, series, rights, built), encoding="utf-8")
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
