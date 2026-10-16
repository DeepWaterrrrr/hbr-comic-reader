# 炽焰天穹 HBR 四格漫画 · 公开阅读站

《炽焰天穹》(Heaven Burns Red) 官方四格漫画的**公开阅读站**。
收录 **213 话**（6 个系列共 16 话 + 197 独立篇），
按「系列优先、时间其次」整理阅读顺序，**每话均可站内阅读完整图片**，
图片下方附来源与署名。站点发布体积约 **130 MB**（225 个 HTML + 4 份 JSON +
426 张公开图片 + 自制素材）。

> **关于授权状态**：漫画著作权归 WFS / Key 及官方运营方所有。
> 本站公开完整图片的依据是**收藏者的授权声明**（Brief v010，状态记为
> `user_declared`——本项目未持有书面许可材料，不虚称已核验）。
> 每一话图片下方均标注来源与署名；官方原帖已删除的保留链接并标记状态。
> 详见 [`PUBLISHING_GUIDE.md`](PUBLISHING_GUIDE.md) 与站点内[版权与授权页](site/rights.html)。

## 功能

| 页面 | 说明 |
|---|---|
| 首页 | 项目介绍、收录统计、最新收录（缩略图）、系列入口 |
| 浏览全部 | 按最新/最早/阅读顺序排列，系列筛选，分页（每页 24，卡片含缩略图） |
| 搜索 | 按正式标题、发布日期（如 `2026-06`）、系列名、编号搜索 |
| 系列 | 6 个系列，系列内按官方证据确定的顺序排列 |
| 单话页 | 完整漫画图片、**来源与署名**、上一话/下一话、返回目录 |
| 版权与授权 | 授权声明范围、授权状态清单、署名口径、免责声明 |
| 404 | 自定义未找到页 |

设计口径：手机优先、中文、无跟踪器（无 Cookie / 分析脚本 / 第三方请求）、
全部相对路径（GitHub Pages 任意子路径可用）、单话页与系列页静态预渲染（固定 URL + SEO）、
图片惰性加载（列表缩略图 + 单话完整图）。

## 目录结构

```text
public-reader/
├─ README.md                 本文件
├─ PUBLISHING_GUIDE.md       发布指南（含授权边界与部署步骤）
├─ .gitignore
├─ .github/workflows/        GitHub Actions 自动部署（可选）
├─ data/                     ← build_catalog.py / build_media.py 产出（可读版源数据）
│  ├─ comics.json            213 条轻量条目（公开字段白名单 + 署名 attribution）
│  ├─ series.json            6 个系列
│  ├─ rights_manifest.json   发布授权状态与证据（user_declared / approved / …）
│  └─ media_manifest.json    公开媒体导出记录（源 hash / 路径 / 宽高 / 字节 / 授权状态）
├─ media/comics/             ← build_media.py 导出的公开图片（随仓库发布）
│  ├─ <item_id>.jpg          213 张完整阅读图（JPEG q87，不裁切、不缩放）
│  └─ thumbs/<item_id>.jpg   213 张缩略图（宽 480）
├─ scripts/
│  ├─ build_site.py          目录数据 + media → 静态站点（CI 用）
│  └─ validate_site.py       上线前自检（16 项验收，CI 用）
└─ site/                     ← 构建产物，即 GitHub Pages 发布目录（不入库，CI 重建）
   ├─ assets/{css,js,img}/   自制样式、交互、中性占位图
   ├─ assets/comics/         公开图片副本（构建时从 media/ 复制）
   ├─ index.html / browse.html / search.html / series.html / rights.html / 404.html
   ├─ comic/<item_id>/index.html     213 页
   ├─ series/<slug>/index.html       6 页
   └─ data/*.json            紧凑版目录数据
```

> **仓库边界**：本公开仓库只包含「数据 + 媒体 + 站点构建器」。
> `data/*.json` 与 `media/` 由项目侧工具链生成（依赖内部 manifest 与归档图片，
> 不属于公开内容），因此 `build_catalog.py` / `build_media.py` **不随本仓库发布**；
> 新增漫画的完整流程在项目侧执行后，把更新后的 `data/` 与 `media/` 提交进来即可，
> CI 会自动重建站点并跑 16 项自检。

## 本地构建与预览

```bash
# 1) 生成静态站点（数据 data/*.json 与媒体 media/ 已在仓库中）
python scripts/build_site.py

# 2) 上线前自检（版权 / 隐私 / 链接 / 署名 / 媒体一致性）
python scripts/validate_site.py

# 3) 本地预览
cd site && python -m http.server 8000
# 打开 http://localhost:8000
```

> 项目侧（有内部 manifest 与归档的环境）完整管线为：
> `build_catalog.py` → `build_media.py`（需 Pillow，只读归档 canonical）→
> `build_site.py` → `validate_site.py`。前两步不随本公开仓库发布。
> `build_media.py` 幂等：已导出且记录匹配的图片自动跳过。

## 媒体导出口径（Brief v010 §3.3）

- 全图：源 canonical **1:1 重编码**，不裁切漫画格、不缩放、不丢文字；
  JPEG 质量 87（progressive + optimize，实测 MAD ≤ 1.2）；
  源为 PNG 时先按 MAD ≤ 2.0 试转 JPEG，不达标保留 PNG；
- 缩略图：宽 480（保持纵横比），JPEG 质量 78；
- 命名用 `item_id`（ASCII 稳定 ID），不用中文文件名；
- 导出记录（`data/media_manifest.json`）：item_id、源 canonical hash、
  发布路径、宽高、格式、字节数、授权状态——发布物与归档可逐字节追溯；
- 源文件缺失 / 打不开 / hash 不符 → **显式失败退出**，不留静默缺口。

## 数据导出安全口径

`build_catalog.py` 采用**字段白名单**，只导出明确列出的公开字段。
以下内容一律**不会**出现在站点数据中：

- 本地绝对路径（`local_path` / `archive_path` / `original_local_path`）
- B站 CDN 图片地址（`image_url`，即 `i0.hdslb.com/bfs/...`）
- `filename_fallback`
- Cookie / Token / `.env` / 任何凭证

`media_manifest.json` 按 Brief v010 Phase B 要求记录**源 canonical hash**
（内部校验值而非凭证，用于发布物与归档的一致性追溯）。

可导出的公开信息仅：`item_id`、正式标题、发布日期、系列与系列内顺序、
canonical 的来源类型与尺寸、**官方原帖链接**（`bilibili.com/read|opus`）、
已核实的署名信息。

## 授权状态

| 内容类别 | 数量 | 状态 |
|---|---|---|
| 官方漫画 | 212 | `user_declared`（用户授权声明，Brief v010 §1/§3.4） |
| 民间汉化（CM_0111） | 1 | `user_declared`（用户明确民间汉化版可公开分享；页面明示汉化来源与 `official_source=false`） |
| 官方封面 | 1 | `not_verified`（授权声明未明确覆盖 → 不生成公开媒体） |
| 自制素材（占位图 / 样式 / 脚本） | — | `approved`（本项目自制） |

**授权口径**：`user_declared`（用户明确声明授权，无书面材料）与 `approved`
（有可核实证据）均视为授权范围内可发布；`not_verified` / `excluded` 一律
不生成公开媒体，只给官方原帖链接。本项目**不伪造**书面许可，
**不热链、不反代、不用缩略图变通**公开未授权内容。

## 署名口径（Brief v010 §3A）

每一话图片下方都有「来源与署名」区，包含：作品/原作、官方发布账号
（已认证账号 + 本话官方动态/专栏链接）、来源链接（动态/专栏 + 日期 + 状态）、
漫画作者/绘者、翻译/汉化、版本说明。

- 漫画作者**仅在官方文本或汉化原帖有明确署名时填写**（如官方合辑动态正文
  「漫画：津留崎 优」）；未标注的一律显示「未标注/待核实」，**不猜作者**；
- 民间汉化信息取自汉化原帖自述与发布者账号（cv36235931：汉化工房九九组 译，
  发布者 StuartRiki_鍵視），不凭空扩展人员名单；
- 官方原帖已删除的（CM_0111）保留链接并标记「原帖已删除」。

## 许可与免责

- 本项目是**非官方**爱好者整理项目，与 WFS / Key / 官方运营方无从属关系。
- **署名与免责声明不等于转载许可。**
- 若权利方认为本站内容不当，请通过仓库 Issues 联系，将立即处理。
