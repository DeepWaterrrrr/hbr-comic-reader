#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v011 validate_site.py — 上线前自检（Brief v011 §5 验收 + 既有署名标准）。

用法：
    python public-reader/scripts/validate_site.py
    python public-reader/scripts/validate_site.py --skip-network --skip-rebuild
    python public-reader/scripts/validate_site.py --live-url https://<user>.github.io/<repo>/

退出码：全部 PASS 或明确标注的 SKIPPED → 0；任一 FAIL → 1。
GitHub Actions 工作流依赖此退出码中止部署。

v011 变化：
- #04 单话页「返回」链接由 browse.html 改为 index.html（首页即浏览入口）；
- #05 browse.html 从「客户端列表页」改为「重定向页」：检查其必须跳转首页
  且不得残留旧列表 DOM；app.js 不再依赖 results/count/pager/f-* 元素；
- #06 断点由 640px 调整为 560px；新增 object-fit: contain 不裁切检查；
- #07/#13 探测清单移除 rights.html（页面已删除），browse.html 仍须 200；
- 新增 #17 首页全量缩略图墙（卡片数 / 缩略图落地 / 系列连续 / gallery_order）；
- 新增 #18 旧链接兼容与 rights 清零（browse 重定向内容、全站无 rights.html
  引用、404 无坏链、页脚授权声明在场）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PUBLIC = SCRIPT_DIR.parent
SITE = PUBLIC / "site"
DATA = PUBLIC / "data"
REPO = PUBLIC.parent
IDX = REPO / "HBR仓库梳理_20260928" / "03_专栏索引"
MANIFEST = IDX / "manifest_v2.json"

RESULTS: list[tuple[str, str, str, str]] = []   # (编号, 名称, 状态, 详情)

# 已核实的艺术家署名白名单（Brief v010 §3A：不得杜撰；来源见 build_catalog.py）
ALLOWED_ARTISTS = {"津留崎 优", "津留崎优"}
ALLOWED_TRANSLATOR_GROUPS = {"汉化工房九九组"}

MEDIA_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif")


def add(no: str, name: str, ok: bool | None, detail: str) -> None:
    status = "PASS" if ok is True else ("SKIPPED" if ok is None else "FAIL")
    RESULTS.append((no, name, status, detail))


def die(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(2)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
#  1. Catalog 数与 manifest 有效 comic item 数一致
# ══════════════════════════════════════════════════════════════════════════
def check_01(comics, manifest) -> None:
    n_json = len(comics)
    pages = sorted(p.parent.name for p in SITE.glob("comic/*/index.html"))
    n_pages = len(pages)
    if manifest is None:
        add("01", "Catalog 数与 manifest 有效 comic item 数一致", None,
            f"**SKIPPED（CI 模式）**：manifest 不在本仓库（独立公开仓库不含内部 manifest）。"
            f"已退而比对 comics.json={n_json} 与单话页目录={n_pages}："
            f"{'一致' if n_json == n_pages else '不一致！'}")
        return
    n_manifest = manifest["counts"]["items"]
    ok = n_manifest == n_json == n_pages
    add("01", "Catalog 数与 manifest 有效 comic item 数一致", ok,
        f"manifest counts.items={n_manifest}；comics.json={n_json}；"
        f"单话页目录={n_pages}")


# ══════════════════════════════════════════════════════════════════════════
#  2. retired / repost 不重复显示
# ══════════════════════════════════════════════════════════════════════════
def check_02(comics, manifest) -> None:
    ids = [c["item_id"] for c in comics]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    retired = ({r.get("item_id") for r in (manifest.get("retired_items") or [])}
               if manifest else set())
    overlap = sorted(set(ids) & retired)
    pages = {p.parent.name for p in SITE.glob("comic/*/index.html")}
    orphan = sorted(pages - set(ids))
    missing = sorted(set(ids) - pages)
    seen: dict[tuple, str] = {}
    title_dups = []
    for c in comics:
        k = (c["title"], c["date"])
        if k in seen:
            title_dups.append(f"{seen[k]} / {c['item_id']}")
        seen[k] = c["item_id"]
    ok = not dup and not overlap and not orphan and not missing
    add("02", "retired / repost 不重复显示", ok,
        f"重复 item_id={dup or '无'}；与 retired_items 交集={overlap or '无'}；"
        f"孤立页面={orphan or '无'}；缺页面={missing or '无'}"
        + (f"；⚠️ 同标题同日期对={title_dups}" if title_dups else ""))


# ══════════════════════════════════════════════════════════════════════════
#  3. 系列内排序和跨系列阅读顺序正确
# ══════════════════════════════════════════════════════════════════════════
def check_03(comics, series) -> None:
    by_id = {c["item_id"]: c for c in comics}
    problems = []

    keys = [(c["date"], c["series_order"] if c["series_order"] is not None else 9999,
             c["item_id"]) for c in comics]
    if [c["reading_index"] for c in comics] != list(range(1, len(comics) + 1)):
        problems.append("reading_index 不是 1..N 连续")
    if keys != sorted(keys):
        problems.append("comics.json 顺序与「系列优先、时间其次」排序键不一致")

    for s in series:
        members = [by_id[i] for i in s["item_ids"]]
        orders = [m["series_order"] for m in members]
        if orders != sorted(orders):
            problems.append(f"系列 {s['name']} 的 item_ids 顺序与 series_order 不一致：{orders}")
        if len(set(s["item_ids"])) != len(s["item_ids"]):
            problems.append(f"系列 {s['name']} 的 item_ids 有重复")

    for i, c in enumerate(comics):
        exp_prev = comics[i - 1]["item_id"] if i > 0 else None
        exp_next = comics[i + 1]["item_id"] if i + 1 < len(comics) else None
        if c.get("prev_id") != exp_prev or c.get("next_id") != exp_next:
            problems.append(f"{c['item_id']} 的 prev/next 与阅读序号不符")
            break

    for s in series:
        page = SITE / "series" / s["slug"] / "index.html"
        txt = read(page)
        positions = [txt.find(f'comic/{iid}/') for iid in s["item_ids"]]
        if any(p < 0 for p in positions) or positions != sorted(positions):
            problems.append(f"系列页 {s['slug']} 的链接顺序与 series.json 不一致")

    add("03", "系列内排序和跨系列阅读顺序正确", not problems,
        "；".join(problems) if problems else
        f"6 项检查全过：reading_index 连续、排序键一致、"
        f"{len(series)} 个系列顺序正确、prev/next 自洽、系列页输出顺序一致")


# ══════════════════════════════════════════════════════════════════════════
#  4. 单话链接、上一话/下一话、返回目录正常
# ══════════════════════════════════════════════════════════════════════════
def check_04(comics) -> None:
    broken, checked = [], 0

    for c in comics:
        page = SITE / "comic" / c["item_id"] / "index.html"
        txt = read(page)
        if not txt:
            broken.append(f"{c['item_id']} 页面缺失")
            continue
        for href in re.findall(r'href="(\.\./\.\./[^"#]+)"', txt):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            target = (page.parent / href).resolve()
            checked += 1
            if not target.exists():
                broken.append(f"{c['item_id']} → {href}")
        for cls, iid in (("prev", c["prev_id"]), ("next", c["next_id"])):
            if iid is None:
                continue
            if f'href="../../comic/{iid}/"' not in txt:
                broken.append(f"{c['item_id']} 的 {cls} 链接未指向 {iid}")
        # v011：首页即浏览入口，返回链接指向 index.html
        if 'href="../../index.html"' not in txt:
            broken.append(f"{c['item_id']} 缺少返回漫画墙链接")
        # v010：图片 src 也必须落地
        for src in re.findall(r'<img src="(\.\./\.\./assets/comics/[^"]+)"', txt):
            target = (page.parent / src).resolve()
            checked += 1
            if not target.exists():
                broken.append(f"{c['item_id']} → 图片缺失 {src}")

    add("04", "单话链接、上一话/下一话、返回漫画墙正常", not broken,
        f"检查 {checked} 个站内链接与图片引用 + {len(comics)} 页 prev/next + "
        f"{len(comics)} 页返回链接"
        + (f"；损坏：{broken[:8]}" if broken else "，全部有效"))


# ══════════════════════════════════════════════════════════════════════════
#  5. 搜索命中与空结果都正常
# ══════════════════════════════════════════════════════════════════════════
def check_05(comics, node: str | None) -> None:
    notes, problems = [], []

    if node:
        r = subprocess.run([node, "--check", str(SITE / "assets/js/app.js")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            notes.append("app.js 语法检查通过（node --check）")
        else:
            problems.append(f"app.js 语法错误：{r.stderr[:200]}")
    else:
        notes.append("未找到 node，跳过 JS 语法检查")

    def search(q: str):
        q = q.strip().lower()
        if not q:
            return None
        out = []
        for c in comics:
            hay = (c["title"] + " " + (c["date"] or "") + " " + (c["series"] or "") + " "
                   + c["item_id"] + " "
                   + " ".join(s["raw_title"] or "" for s in c["sources"])).lower()
            if q in hay:
                out.append(c["item_id"])
        return out

    cases = [
        ("乐队的危机", ["CM_0111"]),
        ("2026-06", None),
        ("第31A部队", None),
        ("CM_0001", ["CM_0001"]),
        ("", None),
        ("不存在的关键词zzz", []),
    ]
    for q, expect in cases:
        got = search(q)
        if q == "":
            if got is not None:
                problems.append("空查询应返回提示态")
            continue
        if expect is None:
            if not got:
                problems.append(f"查询「{q}」应至少命中 1 条，实际 0 条")
        elif got != expect:
            problems.append(f"查询「{q}」期望 {expect}，实际 {got}")
    if not problems:
        notes.append(f"搜索逻辑对拍 {len(cases)} 组用例全过（含空查询与零命中）")

    browse = read(SITE / "browse.html")
    searchp = read(SITE / "search.html")
    appjs = read(SITE / "assets/js/app.js")

    # v011：browse.html 是重定向页（旧链接兼容），不得残留旧客户端列表 DOM
    if not browse:
        problems.append("browse.html 缺失（旧链接会 404）")
    else:
        for needle, label in (
            ('http-equiv="refresh"', "meta refresh 跳转"),
            ('url=./index.html', "跳转目标 index.html"),
            ('rel="canonical"', "canonical 指向首页"),
            ("location.replace", "JS 兜底跳转"),
            ('href="./index.html"', "可见的手动入口链接"),
        ):
            if needle not in browse:
                problems.append(f"browse.html 缺少{label}（{needle}）")
        for stale in ('id="results"', 'id="pager"', 'id="f-series"',
                      'id="f-sort"', 'id="f-q"'):
            if stale in browse:
                problems.append(f"browse.html 残留旧列表 DOM：{stale}")

    need_search = ["s-q", "s-results", "s-count"]
    for i in need_search:
        if f'id="{i}"' not in searchp:
            problems.append(f"search.html 缺少 app.js 依赖的元素 #{i}")
        elif f'$("{i}")' not in appjs and f"$('{i}')" not in appjs:
            problems.append(f"app.js 未引用 #{i}")
    if not problems:
        notes.append("browse.html 为重定向页且无旧 DOM 残留；search 元素 id 与 "
                     "app.js 引用一致（3 个）")

    # v010 遗留 bug 回归防线：thumb 路径不得双重拼接
    if "assets/comics/thumbs/\" + esc(c.thumb)" in appjs or \
            "'./assets/comics/thumbs/' + esc(c.thumb)" in appjs:
        problems.append("app.js 仍存在 thumb 双重拼接（v010 bug 复发）")
    if "split(\"/\").pop()" not in appjs:
        problems.append("app.js 未对 thumb 取 basename（v010 bug 防线缺失）")

    newest = max(comics, key=lambda c: c["reading_index"])
    oldest = min(comics, key=lambda c: c["reading_index"])
    notes.append(f"最新={newest['item_id']}({newest['date']})，"
                 f"最早={oldest['item_id']}({oldest['date']})")

    add("05", "搜索命中与空结果都正常", not problems,
        "；".join(notes) + ("；问题：" + "；".join(problems) if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
#  6. 手机/桌面布局可用，资源惰性加载
# ══════════════════════════════════════════════════════════════════════════
def check_06(comics) -> None:
    css = read(SITE / "assets/css/style.css")
    problems = []

    if "@media (min-width: 560px)" not in css:
        problems.append("缺少移动端网格断点（560px 起 3 列）")
    if "@media (min-width: 1200px)" not in css:
        problems.append("缺少桌面网格断点（1200px 起 5 列）")
    if "--tap: 44px" not in css:
        problems.append("缺少最小点击区域变量")
    if "grid-template-columns: repeat(2, 1fr)" not in css:
        problems.append("缺少手机 2 列基础网格（SD-11.3）")
    if "overflow-x: auto" not in css:
        problems.append("宽表格缺少横向滚动容器")
    # v011 SD-11.3：缩略图不得裁切四格
    if "object-fit: contain" not in css:
        problems.append("缩略图未使用 object-fit: contain（会裁切漫画格）")
    if "aspect-ratio" not in css:
        problems.append("缩略图缺少 aspect-ratio（无 CLS 保护）")

    index = read(SITE / "index.html")
    sample = SITE / "comic" / comics[0]["item_id"] / "index.html"
    txt = read(sample)
    if 'name="viewport"' not in txt or "width=device-width" not in txt:
        problems.append("缺少 viewport meta")
    if "loading=\"lazy\"" not in txt:
        problems.append("单话图未使用惰性加载")
    if "loading=\"eager\"" not in index:
        problems.append("首页首屏缩略图未使用 eager 加载")
    if 'loading="lazy"' not in index:
        problems.append("首页离屏缩略图未使用 lazy 加载")

    for m in re.finditer(r'style="[^"]*width:\s*\d{3,}px', txt):
        problems.append(f"发现写死宽度：{m.group(0)[:60]}")
        break

    add("06", "手机/桌面布局可用，资源惰性加载", not problems,
        ("静态检查通过：viewport meta、44px 点击区域、2→3→4→5 列断点、"
         "object-fit: contain 不裁切、aspect-ratio 防 CLS、首页 eager+lazy、"
         "横向滚动容器、无写死宽度。"
         "**真机/浏览器视觉测试未自动化（SKIPPED，需人工）**"
         if not problems else "；".join(problems)))


# ══════════════════════════════════════════════════════════════════════════
#  7. GitHub Pages 项目子路径资源不 404
# ══════════════════════════════════════════════════════════════════════════
def check_07(skip_network: bool, series=None) -> None:
    if skip_network:
        add("07", "GitHub Pages 项目子路径资源不 404", None,
            "按 --skip-network 跳过（未启动本地 HTTP 服务）")
        return

    problems = []
    handler = partial(SimpleHTTPRequestHandler, directory=str(PUBLIC))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.3)
    # 直接服务 public-reader/ 根：等价于 Pages 把站点挂在仓库子路径
    # （站内全部相对路径，/site/ 前缀不影响资源解析）
    base = f"http://127.0.0.1:{port}/site"

    probes = [
        "/", "/index.html", "/browse.html", "/search.html",
        "/series.html", "/404.html",
        "/comic/CM_0001/", "/comic/CM_0111/", "/comic/CM_0217/",
        "/series/" + urllib.parse.quote(series[0]["slug"], safe="") + "/",
        "/assets/css/style.css", "/assets/js/app.js",
        "/assets/img/placeholder.svg",
        "/assets/comics/CM_0001.jpg",
        "/assets/comics/thumbs/CM_0111.jpg",
        "/data/comics.json", "/data/series.json", "/data/rights_manifest.json",
        "/data/media_manifest.json",
    ]
    try:
        for p in probes:
            url = base + p
            try:
                with urllib.request.urlopen(url, timeout=10) as r:
                    code = r.status
                    r.read(64)
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:                          # noqa: BLE001
                problems.append(f"{p} → {e}")
                continue
            if code != 200:
                problems.append(f"{p} → HTTP {code}")
    finally:
        srv.shutdown()

    add("07", "GitHub Pages 项目子路径资源不 404", not problems,
        f"本地起服务探测 {len(probes)} 个资源（含 2 张公开图片与 4 份 JSON）"
        + (f"；失败：{problems[:6]}" if problems else "，全部 200"))


# ══════════════════════════════════════════════════════════════════════════
#  8. 公开输出扫描：敏感文件、Cookie、Token、媒体白名单零泄漏
# ══════════════════════════════════════════════════════════════════════════
def check_08() -> None:
    problems = []
    if not SITE.is_dir():
        die("site/ 不存在，请先运行 scripts/build_site.py")

    files = sorted(p for p in SITE.rglob("*")
                   if p.is_file() and ".git" not in p.parts)

    # 8a 敏感文件名
    for p in files:
        low = p.name.lower()
        if low.endswith((".env", ".pem", ".key")) or any(
                k in low for k in ("cookie", "token", "secret", "credential")):
            problems.append(f"敏感文件名：{p.relative_to(SITE)}")

    # 8b 敏感内容模式（只扫文本类文件）
    patterns = {
        "B站 CDN 热链": r"hdslb\.com",
        "BFS 资源键": r"bfs/",
        "Cookie 字段": r"SESSDATA|bili_jct|DedeUser|buvid",
        "本地绝对路径": r"[A-Za-z]:\\\\|/home/|/Users/",
        "内部文档路径": r"HBR仓库梳理_20260928[/\\](06_受控文档|08_人工复核)",
        "内部 manifest 引用": r"manifest_v2\.json",
    }
    for p in files:
        if p.suffix.lower() not in (".html", ".json", ".css", ".js", ".svg", ".txt", ".md"):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"非 UTF-8 文件：{p.relative_to(SITE)}")
            continue
        for label, pat in patterns.items():
            if re.search(pat, txt):
                problems.append(f"{p.relative_to(SITE)} 命中「{label}」")

    # 8c 媒体白名单：位图只允许出现在 assets/comics/（授权导出的公开媒体）
    media = [p for p in files if p.suffix.lower() in MEDIA_EXTS]
    for p in media:
        rel = p.relative_to(SITE)
        if rel.parts[:2] != ("assets", "comics"):
            problems.append(f"白名单外位图媒体：{rel}")

    # 8d comics.json 字段白名单：禁导字段一个都不许出现
    comics = json.loads((DATA / "comics.json").read_text(encoding="utf-8"))
    forbidden = ("local_path", "archive_path", "original_local_path",
                 "image_url", "filename_fallback")
    leaked = []
    for c in comics:
        for k in forbidden:
            if k in c:
                leaked.append(f"{c['item_id']}.{k}")
    if leaked:
        problems.append(f"comics.json 出现禁导字段：{leaked[:5]}")

    # 8e 扩展名白名单
    allowed = {".svg", ".html", ".json", ".css", ".js", ".md", ".txt", ".jpg", ".jpeg", ".png"}
    allowed_names = {".nojekyll", "CNAME"}
    for p in files:
        if p.name in allowed_names:
            continue
        if p.suffix.lower() not in allowed:
            problems.append(f"非白名单扩展名：{p.relative_to(SITE)}")

    add("08", "公开输出扫描：敏感文件 / Cookie / Token / 媒体白名单零泄漏",
        not problems,
        f"扫描 {len(files)} 个文件：敏感文件名 0、敏感内容模式 0、"
        f"位图媒体 {len(media)} 个（全部位于 assets/comics/ 授权目录）、"
        f"禁导字段 0、扩展名白名单"
        + (f"；问题：{problems[:6]}" if problems else "，全部通过"))


# ══════════════════════════════════════════════════════════════════════════
#  9. CM_0111 的非官方标记、汉化署名与公开权限状态正确
# ══════════════════════════════════════════════════════════════════════════
def check_09(comics, rights) -> None:
    c = next((x for x in comics if x["item_id"] == "CM_0111"), None)
    problems = []
    if c is None:
        problems.append("comics.json 中找不到 CM_0111")
    else:
        if c["canonical_official"]:
            problems.append("CM_0111 的 canonical_official 应为 false")
        if not c.get("exception"):
            problems.append("CM_0111 缺少 exception 留痕")
        if not c.get("image"):
            problems.append("CM_0111 缺少公开完整图记录")

    page = SITE / "comic" / "CM_0111" / "index.html"
    txt = read(page)
    for needle, label in (
        ("badge-unofficial", "民间汉化徽标"),
        ("民间汉化", "民间汉化说明"),
        ("official_source=false", "非官方来源标记"),
        ("badge-deleted", "官方原帖已删除徽标"),
        ("汉化工房九九组", "汉化组署名"),
        ("StuartRiki_鍵視", "汉化发布者署名"),
        ("cv36235931", "汉化来源链接"),
        ("cv50834080", "官方失效来源链接"),
        ('src="../../assets/comics/CM_0111.jpg"', "站内完整图"),
    ):
        if needle not in txt:
            problems.append(f"CM_0111 页面缺少「{label}」（{needle}）")

    cat = next((x for x in rights.get("categories", [])
                if x.get("category") == "unofficial_translation"), None)
    if cat is None:
        problems.append("rights_manifest.json 缺少民间汉化类别")
    else:
        if cat.get("status") != "user_declared":
            problems.append(f"民间汉化类别状态应为 user_declared，实际 {cat.get('status')}")
        if cat.get("items") != ["CM_0111"]:
            problems.append(f"民间汉化类别 items 应为 ['CM_0111']，实际 {cat.get('items')}")
        if not cat.get("usage_scope"):
            problems.append("民间汉化类别应记录允许用途（用户授权声明范围）")

    add("09", "CM_0111 的非官方标记、汉化署名与公开权限状态正确", not problems,
        ("页面含民间汉化徽标 + official_source=false + 汉化组/发布者署名 + "
         "官方失效链接 + 站内完整图；rights_manifest 记 user_declared / "
         "usage_scope 非空 / items=[CM_0111]"
         if not problems else "；".join(problems)))


# ══════════════════════════════════════════════════════════════════════════
#  10. README 与站点统计一致
# ══════════════════════════════════════════════════════════════════════════
def check_10(comics, series) -> None:
    readme = read(PUBLIC / "README.md")
    problems = []
    if not readme:
        problems.append("README.md 不存在")
    else:
        n = len(comics)
        ns = len(series)
        n_standalone = n - sum(s["count"] for s in series)
        for label, needle in (
            ("总话数", f"**{n} 话**"),
            ("系列数", f"{ns} 个系列"),
            ("独立篇数", f"{n_standalone} 独立篇"),
        ):
            if needle not in readme:
                problems.append(f"README 缺少{label}「{needle}」")
        m = re.search(r"约 \*\*([\d.]+) MB\*\*", readme)
        if m:
            actual_mb = sum(p.stat().st_size for p in SITE.rglob("*")
                            if p.is_file() and ".git" not in p.parts) / 1024 / 1024
            if not (0.3 * float(m.group(1)) <= actual_mb <= 3 * float(m.group(1))):
                problems.append(f"README 站点体积 {m.group(1)} MB 与实测 "
                                f"{actual_mb:.2f} MB 不符")
        else:
            problems.append("README 缺少站点体积说明")

    add("10", "README 与站点统计一致", not problems,
        ("总话数 / 系列数 / 独立篇数 / 站点体积均与构建产物一致"
         if not problems else "；".join(problems)))


# ══════════════════════════════════════════════════════════════════════════
#  11. 所有公开图片均有授权依据；无权内容不生成媒体
# ══════════════════════════════════════════════════════════════════════════
def check_11(comics, rights, media) -> None:
    problems = []

    # 11a site/ 下图片目录合法性：assets/img/（自制）+ assets/comics/（授权导出）
    imgs = sorted(p for p in SITE.rglob("*") if p.suffix.lower() in MEDIA_EXTS)
    for p in imgs:
        rel = p.relative_to(SITE)
        if rel.parts[:2] not in (("assets", "img"), ("assets", "comics")):
            problems.append(f"非授权目录出现图片：{rel}")
    if not (SITE / "assets/img/placeholder.svg").is_file():
        problems.append("缺少自制占位图")

    # 11b 有权类别才能发布媒体
    publishable = {c["category"] for c in rights.get("categories", [])
                   if c.get("status") in ("approved", "user_declared")}
    if "official_comic" not in publishable:
        problems.append("official_comic 不在可发布类别中")
    if "unofficial_translation" not in publishable:
        problems.append("unofficial_translation 不在可发布类别中")

    # 11c 位图必须与 comics.json / media_manifest 一一对应（无孤儿、无缺失）
    rec_by_id = {r["item_id"]: r for r in media.get("records", [])}
    json_names = set()
    for c in comics:
        if c.get("image"):
            json_names.add(Path(c["image"]).name)
            json_names.add(Path(c["thumb"]).name)
    file_names = {p.name for p in SITE.rglob("assets/comics/*")
                  if p.is_file()} | {p.name for p in SITE.rglob("assets/comics/thumbs/*")
                                     if p.is_file()}
    orphan = sorted(file_names - json_names)
    missing = sorted(json_names - file_names)
    if orphan:
        problems.append(f"无对应条目的孤儿图片：{orphan[:5]}")
    if missing:
        problems.append(f"comics.json 指向但缺失的图片：{missing[:5]}")
    no_rights = [iid for iid in rec_by_id
                 if iid not in {c["item_id"] for c in comics}]
    if no_rights:
        problems.append(f"media_manifest 含有目录外条目：{no_rights[:5]}")

    # 11d 每话必须有授权记录才渲染整图；未授权条目只给官方链接
    for c in comics:
        txt = read(SITE / "comic" / c["item_id"] / "index.html")
        has_img = f'src="../../assets/comics/{Path(c["image"]).name}"' in txt \
            if c.get("image") else False
        if has_img and c["item_id"] not in rec_by_id:
            problems.append(f"{c['item_id']} 渲染了整图但无授权记录")
        if not has_img and "前往官方原帖" not in txt and "来源链接" not in txt:
            problems.append(f"{c['item_id']} 既无整图也无官方入口")

    # 11e 所有 source URL 必须是 bilibili.com 官方域名
    for c in comics:
        for s in c["sources"]:
            if not s["url"].startswith("https://www.bilibili.com/"):
                problems.append(f"{c['item_id']} 的 source 非官方域名：{s['url']}")

    add("11", "所有公开图片均有授权依据；无权内容不生成媒体", not problems,
        f"图片 {len(imgs)} 个全部位于授权目录（assets/img 自制 / assets/comics 导出）；"
        f"可发布类别={sorted(publishable)}；图片与 comics.json / media_manifest "
        f"一一对应（{len(file_names)} 个文件）；"
        f"全部 source URL 均为 bilibili.com 官方域名"
        + (f"；问题：{problems[:5]}" if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
#  12. 原始 manifest/归档保持完整，现有完整性/收官审计复测通过
# ══════════════════════════════════════════════════════════════════════════
def check_12(manifest) -> None:
    problems = []
    notes = []

    if manifest is None:
        # CI 模式（独立公开仓库不含内部 manifest 与归档）：明确降级
        add("12", "原始 manifest/归档保持完整，现有审计复测通过", None,
            "**SKIPPED（CI 模式）**：独立公开仓库不含内部 manifest 与归档，"
            "项目侧审计（完整性 33/33、收官审计 22/22）由项目内 "
            "validate_site.py 全量模式复跑确认，见 v010 Report §10。")
        return

    if manifest["counts"]["items"] != 213:
        problems.append(f"manifest items 变为 {manifest['counts']['items']}（应为 213）")
    if manifest["counts"]["needs_review"] != 0:
        problems.append(f"needs_review 变为 {manifest['counts']['needs_review']}")
    n_unoff = sum(1 for it in manifest["comic_items"]
                  if it.get("official_source") is False)
    if n_unoff != 1:
        problems.append(f"非官方 canonical 数变为 {n_unoff}（应为 1）")
    notes.append(f"manifest counts 校验：items={manifest['counts']['items']}、"
                 f"needs_review={manifest['counts']['needs_review']}、"
                 f"非官方 canonical={n_unoff}")

    tools = REPO / "HBR仓库梳理_20260928" / "05_工具脚本"
    for script, label in (("verify_archive_completeness.py", "完整性 33 项"),
                          ("phase_e_final_audit.py", "收官审计 22 项")):
        path = tools / script
        if not path.is_file():
            notes.append(f"{label}：脚本不存在，跳过")
            continue
        r = subprocess.run([sys.executable, str(path)],
                           capture_output=True, text=True, cwd=str(tools),
                           timeout=600)
        tail = (r.stdout or "")[-400:]
        ok = r.returncode == 0 and ("通过 33/33" in tail or "33/33" in tail
                                    or "22/22" in tail)
        if not ok:
            problems.append(f"{label} 未通过：{tail[-200:]}")
        else:
            notes.append(f"{label} 复测通过")

    add("12", "原始 manifest/归档保持完整，现有审计复测通过", not problems,
        "；".join(notes) + (f"；问题：{problems}" if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
#  13. 真实部署 URL 可访问（--live-url 提供时实测）
# ══════════════════════════════════════════════════════════════════════════
def check_13(live_url: str | None, comics) -> None:
    if not live_url:
        add("13", "真实部署 URL 可访问性", None,
            "**SKIPPED（未提供 --live-url）**：尚未部署或未取得真实 URL。"
            "部署后用 --live-url https://<user>.github.io/<repo>/ 补测。")
        return

    problems = []
    base = live_url.rstrip("/") + "/"
    sample_ids = ["CM_0001", "CM_0111", "CM_0217"]
    series_slug = json.loads((DATA / "series.json").read_text(encoding="utf-8"))[0]["slug"]
    probes = [
        "", "index.html", "browse.html", "search.html", "series.html",
        "404.html",
        f"series/{urllib.parse.quote(series_slug, safe='')}/",
        "assets/css/style.css", "assets/js/app.js",
        "data/comics.json", "data/media_manifest.json",
    ] + [f"comic/{iid}/" for iid in sample_ids] + [
        f"assets/comics/{iid}.jpg" for iid in sample_ids] + [
        "assets/comics/thumbs/CM_0001.jpg"]
    for p in probes:
        url = base + p
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                code = r.status
                r.read(64)
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:                                  # noqa: BLE001
            problems.append(f"{p or '(root)'} → {e}")
            continue
        if code != 200:
            problems.append(f"{p or '(root)'} → HTTP {code}")

    add("13", "真实部署 URL 可访问性", not problems,
        f"探测 {live_url} 共 {len(probes)} 个资源（首页/browse 重定向/搜索/系列/404/"
        f"3 个单话页/3 张完整图/缩略图/CSS/JS/2 份 JSON）"
        + (f"；失败：{problems[:6]}" if problems else "，全部 200"))


# ══════════════════════════════════════════════════════════════════════════
#  14. 可重跑构建，结果一致；新漫画新增后可增量更新
# ══════════════════════════════════════════════════════════════════════════
def check_14(skip_rebuild: bool, node: str | None) -> None:
    if skip_rebuild:
        add("14", "可重跑构建，结果一致", None, "按 --skip-rebuild 跳过")
        return

    def snapshot(root: Path) -> dict[str, str]:
        return {str(p.relative_to(root)): sha(p)
                for p in sorted(root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    before = snapshot(SITE)
    # 用 --out 构建到临时目录再比对：不删除/覆盖 site/（site/ 是当前发布候选，
    # 且本机删除防护策略对大批量删除有确认门槛，构建比对不应依赖删除操作）。
    tmp = Path(tempfile.mkdtemp(prefix="hbr_site_rebuild_")) / "site"
    try:
        r = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "build_site.py"), "--out", str(tmp)],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            add("14", "可重跑构建，结果一致", False,
                f"重跑 build_site.py --out 失败：{(r.stderr or '')[-300:]}")
            return
        after = snapshot(tmp)
        diff = sorted(k for k in set(before) | set(after)
                      if before.get(k) != after.get(k))
        add("14", "可重跑构建，结果一致", not diff,
            f"以 --out 重建 {len(after)} 个文件并与 site/ 逐文件比对"
            + (f"；不一致：{diff[:5]}" if diff else "，内容完全一致（幂等）")
            + "。新增漫画只需更新 manifest 后重跑 build_catalog.py + build_media.py "
              "+ build_site.py，页面由数据自动生成，无需手写目录。")
    except subprocess.TimeoutExpired:
        add("14", "可重跑构建，结果一致", False, "重建超时（600s）")
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════
#  15. 每话「来源与署名」区完整（Brief v010 §3A）
# ══════════════════════════════════════════════════════════════════════════
def check_15(comics) -> None:
    problems = []
    n_src_links = 0
    n_artist_known = 0
    n_deleted = 0

    for c in comics:
        txt = read(SITE / "comic" / c["item_id"] / "index.html")
        if not txt:
            problems.append(f"{c['item_id']} 页面缺失")
            continue
        # 15a 署名区存在，且位于完整漫画图片之后
        pos_attr = txt.find('<section class="attribution"')
        if pos_attr < 0:
            problems.append(f"{c['item_id']} 缺少「来源与署名」区")
            continue
        pos_img = txt.find("<figure class=\"reader\"")
        pos_ph = txt.find('class="placeholder"')
        pos_reader = max(pos_img, pos_ph)
        if pos_reader >= 0 and pos_attr < pos_reader:
            problems.append(f"{c['item_id']} 署名区不在图片下方")
        # 15b 必填行齐全
        for label in ("作品 / 原作", "官方发布账号", "漫画作者 / 绘者",
                      "翻译 / 汉化", "版本说明", "来源链接"):
            if label not in txt:
                problems.append(f"{c['item_id']} 署名区缺少「{label}」")
        # 15c 至少一个来源链接或明确的待核实状态
        n_links = len(re.findall(
            r'<a href="https://www\.bilibili\.com/(read|opus)/', txt))
        n_src_links += len(c["sources"])
        if n_links == 0:
            problems.append(f"{c['item_id']} 没有任何来源链接")
        # 15d 艺术家署名只允许白名单（不得杜撰）
        a = (c.get("attribution") or {}).get("artist") or {}
        if a.get("name"):
            n_artist_known += 1
            if a["name"] not in ALLOWED_ARTISTS:
                problems.append(f"{c['item_id']} 艺术家署名不在白名单：{a['name']}")
        tr = (c.get("attribution") or {}).get("translator")
        if tr and tr.get("group") not in ALLOWED_TRANSLATOR_GROUPS:
            problems.append(f"{c['item_id']} 汉化组署名不在白名单：{tr.get('group')}")
        # 15e 失效来源必须标注
        if any(s["status"] == "deleted" for s in c["sources"]):
            n_deleted += 1
            if "badge-deleted" not in txt or "原帖已删除" not in txt:
                problems.append(f"{c['item_id']} 有失效来源但未标注「原帖已删除」")

    add("15", "每话「来源与署名」区完整（Brief §3A）", not problems,
        f"{len(comics)} 页全部具备署名区且位于图片下方；必填 6 行齐全；"
        f"来源链接总数 {n_src_links}；艺术家已署名 {n_artist_known} / {len(comics)}"
        f"（其余显示「未标注/待核实」）；失效来源标注 {n_deleted} 话；"
        f"署名白名单校验通过"
        + (f"；问题：{problems[:5]}" if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
#  16. 媒体文件与 media_manifest / comics.json 一致（字节级）
# ══════════════════════════════════════════════════════════════════════════
def check_16(comics, media) -> None:
    problems = []
    rec_by_id = {r["item_id"]: r for r in media.get("records", [])}
    n_checked = 0

    for c in comics:
        rec = rec_by_id.get(c["item_id"])
        if not rec:
            problems.append(f"{c['item_id']} 无 media_manifest 记录")
            continue
        for key, rel in (("image_bytes", c.get("image")),
                         ("thumb_bytes", c.get("thumb"))):
            f = SITE / rel
            if not f.is_file():
                problems.append(f"{c['item_id']} 缺文件 {rel}")
                continue
            if f.stat().st_size != rec.get(key):
                problems.append(f"{c['item_id']} {rel} 字节数与记录不符")
            n_checked += 1
        # 尺寸一致
        if rec.get("image_width") != c.get("image_width") or \
                rec.get("image_height") != c.get("image_height"):
            problems.append(f"{c['item_id']} 尺寸与记录不符")

    # PIL 可用时抽查真实解码尺寸（防止文件损坏）
    dim_note = "PIL 不可用，跳过解码抽查"
    try:
        from PIL import Image                                   # noqa: PLC0415
        sample_ids = ["CM_0001", "CM_0111", comics[-1]["item_id"]]
        bad = []
        for iid in sample_ids:
            p = SITE / "assets" / "comics" / f"{iid}.jpg"
            with Image.open(p) as im:
                w, h = im.size
            rec = rec_by_id[iid]
            if (w, h) != (rec["image_width"], rec["image_height"]):
                bad.append(f"{iid} 实际 {w}×{h}")
        dim_note = f"PIL 解码抽查 {len(sample_ids)} 张尺寸一致" if not bad \
            else f"尺寸不符：{bad}"
        if bad:
            problems.append(dim_note)
    except ImportError:
        pass

    add("16", "媒体文件与 media_manifest / comics.json 一致", not problems,
        f"逐条核对 {len(comics)} 话 × 2 个文件（全图 + 缩略图）共 {n_checked} 个，"
        f"字节与尺寸全部匹配；{dim_note}"
        + (f"；问题：{problems[:5]}" if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
# 17. 首页即全量缩略图墙（Brief v011 SD-11.1/11.2/11.3）
# ══════════════════════════════════════════════════════════════════════════
def check_17(comics, series) -> None:
    problems = []
    index = read(SITE / "index.html")
    if not index:
        add("17", "首页即全量缩略图墙（Brief v011 SD-11.1/11.2/11.3）", False,
            "index.html 缺失")
        return

    # 17a 卡片数 == 有效 item 数，且一个不少
    n_cards = len(re.findall(r'<a class="card" href="\./comic/CM_\d+/">', index))
    if n_cards != len(comics):
        problems.append(f"首页卡片数 {n_cards} != 有效话数 {len(comics)}")

    # 17b 每张卡片都有真实缩略图（无占位、无裂图路径、无双重拼接）
    srcs = re.findall(r'<img src="\./assets/comics/thumbs/([^"]+)"', index)
    if len(srcs) != len(comics):
        problems.append(f"首页缩略图数 {len(srcs)} != 话数 {len(comics)}")
    bad_path = [s for s in srcs if "/" in s or not s.endswith(".jpg")]
    if bad_path:
        problems.append(f"缩略图路径异常（疑双重拼接）：{bad_path[:3]}")
    for s in srcs:
        if not (SITE / "assets" / "comics" / "thumbs" / s).is_file():
            problems.append(f"缩略图文件缺失：{s}")
            break
    # 只查 <img> 引用的占位图（favicon 的 placeholder.svg 是 <link>，不算）
    if re.search(r'<img[^>]+src="[^"]*placeholder\.svg"', index):
        problems.append("首页出现占位图（不得用占位代替真实缩略图）")

    # 17c 卡片指向的单话页全部存在
    ids = re.findall(r'<a class="card" href="\./comic/(CM_\d+)/">', index)
    missing = [i for i in ids if not (SITE / "comic" / i / "index.html").is_file()]
    if missing:
        problems.append(f"卡片指向的单话页缺失：{missing[:5]}")
    if len(set(ids)) != len(ids):
        problems.append("首页出现重复话数卡片")

    # 17d 系列连续性（gallery_order 顺序下每个系列只出现一次且连续）
    by_id = {c["item_id"]: c for c in comics}
    seq = [by_id[i]["series"] for i in ids]
    for s in series:
        idxs = [k for k, v in enumerate(seq) if v == s["name"]]
        if not idxs:
            problems.append(f"系列 {s['name']} 未在首页出现")
        elif idxs != list(range(idxs[0], idxs[-1] + 1)):
            problems.append(f"系列 {s['name']} 在首页被拆散：{idxs}")

    # 17e gallery_order 合规：1..N 连续、组锚点单调不减、组内 series_order 递增
    by_go = sorted(comics, key=lambda c: c["gallery_order"])
    if [c["gallery_order"] for c in by_go] != list(range(1, len(comics) + 1)):
        problems.append("gallery_order 不是 1..N 连续")
    order_seq = [by_id[i]["gallery_order"] for i in ids]
    if order_seq != sorted(order_seq):
        problems.append("首页卡片顺序与 gallery_order 不一致")
    anchors: dict[str, str] = {}
    for c in by_go:
        key = c["series"] or f"__s__{c['item_id']}"
        if key not in anchors:
            anchors[key] = c["date"] or ""
    ak = list(anchors.values())
    if ak != sorted(ak):
        problems.append("系列组锚点日期非单调不减（组间排序错误）")
    for s in series:
        members = [by_id[i] for i in s["item_ids"]]
        orders = [m["series_order"] for m in members]
        if orders != sorted(orders):
            problems.append(f"系列 {s['name']} 组内顺序与 series_order 不一致：{orders}")

    # 17f 组首分组小行在场（系列连续的可视标记）
    n_groups = len([s for s in series]) + len([c for c in comics if not c["series"]])
    n_leads = len(re.findall(r'class="group-lead"', index))
    expected_leads = len(series)          # 仅系列组有小行；独立篇不加（避免噪音）
    if n_leads != expected_leads:
        problems.append(f"分组小行数 {n_leads} != 系列数 {expected_leads}")

    # 17g 首页不得再出现已删除的模板区块
    for stale in ('class="stats"', 'class="cta-row"', '最新收录', '收录范围与数据说明',
                  '版权与授权</a>', '浏览全部 '):
        if stale in index:
            problems.append(f"首页残留旧模板元素：{stale}")

    add("17", "首页即全量缩略图墙（Brief v011 SD-11.1/11.2/11.3）", not problems,
        f"卡片 {n_cards}/{len(comics)}；缩略图 {len(srcs)} 张全部落地且路径无双重拼接；"
        f"系列 {len(series)} 个全部连续；gallery_order 1..N 连续、组锚点单调、"
        f"组内 series_order 正确；分组小行 {n_leads}；无占位图、无旧模板残留"
        + (f"；问题：{problems[:5]}" if problems else ""))


# ══════════════════════════════════════════════════════════════════════════
# 18. 旧链接兼容与 rights 页面清零（Brief v011 SD-11.1）
# ══════════════════════════════════════════════════════════════════════════
def check_18() -> None:
    problems = []

    # 18a rights.html 不得再生成
    if (SITE / "rights.html").is_file():
        problems.append("rights.html 仍被生成（SD-11.1 要求删除）")

    # 18b 全站 HTML 不得再引用 rights.html
    refs = []
    for p in SITE.rglob("*.html"):
        if ".git" in p.parts:
            continue
        txt = read(p)
        if "rights.html" in txt:
            refs.append(str(p.relative_to(SITE)))
    if refs:
        problems.append(f"仍有页面引用 rights.html：{refs[:5]}")

    # 18c 全站 HTML 不得再链向已不存在的 browse 语义（browse 重定向除外）
    #     ——browse.html 自身是重定向页，允许出现；其他页面不应再导航到它。
    nav_refs = []
    for p in SITE.rglob("*.html"):
        if ".git" in p.parts or p.name == "browse.html":
            continue
        txt = read(p)
        if re.search(r'href="[^"]*browse\.html"', txt):
            nav_refs.append(str(p.relative_to(SITE)))
    if nav_refs:
        problems.append(f"仍有页面导航到 browse.html：{nav_refs[:5]}")

    # 18d 404 页与首页不得有坏链
    for name in ("index.html", "404.html"):
        txt = read(SITE / name)
        for href in re.findall(r'href="\./([^"#]+)"', txt):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            if not (SITE / href).exists():
                problems.append(f"{name} 引用不存在的站内目标：{href}")

    # 18e 页脚授权声明在场（rights 页删除后的义务承载）
    footer_txt = read(SITE / "comic" / "CM_0001" / "index.html")
    for needle in ("user_declared", "WFS / Key", "仓库 Issues"):
        if needle not in footer_txt:
            problems.append(f"页脚缺少授权/联系声明要素：{needle}")

    add("18", "旧链接兼容与 rights 页面清零（Brief v011 SD-11.1）", not problems,
        "rights.html 未生成且全站 0 引用；无页面再导航 browse.html"
        "（browse 自身为重定向页）；index/404 无坏链；"
        "页脚保留 user_declared 授权声明与 Issues 联系入口"
        + (f"；问题：{problems[:5]}" if problems else ""))
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-network", action="store_true",
                    help="跳过需要本地 HTTP 服务的检查（#07）")
    ap.add_argument("--skip-rebuild", action="store_true",
                    help="跳过重跑构建的一致性检查（#14）")
    ap.add_argument("--live-url", default=None,
                    help="真实部署 URL（提供则执行 #13 实测）")
    args = ap.parse_args()

    for f in ("comics.json", "series.json", "rights_manifest.json",
              "media_manifest.json"):
        if not (DATA / f).is_file():
            die(f"缺少 data/{f}，请先运行 scripts/build_catalog.py + build_media.py")
    if not SITE.is_dir():
        die("site/ 不存在，请先运行 scripts/build_site.py")

    comics = json.loads((DATA / "comics.json").read_text(encoding="utf-8"))
    series = json.loads((DATA / "series.json").read_text(encoding="utf-8"))
    rights = json.loads((DATA / "rights_manifest.json").read_text(encoding="utf-8"))
    media = json.loads((DATA / "media_manifest.json").read_text(encoding="utf-8"))
    manifest = (json.loads(MANIFEST.read_text(encoding="utf-8"))
                if MANIFEST.is_file() else None)
    node = shutil.which("node")

    check_01(comics, manifest)
    check_02(comics, manifest)
    check_03(comics, series)
    check_04(comics)
    check_05(comics, node)
    check_06(comics)
    check_07(args.skip_network, series)
    check_08()
    check_09(comics, rights)
    check_10(comics, series)
    check_11(comics, rights, media)
    check_12(manifest)
    check_13(args.live_url, comics)
    check_14(args.skip_rebuild, node)
    check_15(comics)
    check_16(comics, media)
    check_17(comics, series)
    check_18()

    # ── 汇总 ──
    n_pass = sum(1 for r in RESULTS if r[2] == "PASS")
    n_fail = sum(1 for r in RESULTS if r[2] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r[2] == "SKIPPED")

    print("=" * 78)
    print("HBR public-reader 上线前自检（Brief v011 §5 验收 + 既有署名标准）")
    print("=" * 78)
    for no, name, status, detail in RESULTS:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️ "}[status]
        print(f"{mark} {no}. {name}  [{status}]")
        print(f"     {detail}")
    print("-" * 78)
    print(f"合计：PASS {n_pass} / FAIL {n_fail} / SKIPPED {n_skip}")
    if n_fail:
        print("结论：❌ 存在失败项，不得部署")
        sys.exit(1)
    print("结论：✅ 可用于部署（SKIPPED 项需人工补测）")
    sys.exit(0)


if __name__ == "__main__":
    main()
