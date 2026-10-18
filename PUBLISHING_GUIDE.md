# 发布指南（PUBLISHING_GUIDE）

本文件说明如何把本站发布到 GitHub Pages，以及**发布前必须遵守的版权边界**。

---

## 0. 先说边界：什么能发，什么不能发

| 内容 | 能否公开上传到 GitHub / GitHub Pages | 依据 |
|---|---|---|
| 本站自制素材（占位图 SVG、CSS、JS） | ✅ 可以 | 本项目自制，无第三方内容 |
| 目录数据（`comics.json` / `series.json`，仅公开字段） | ✅ 可以 | 标题/日期/官方原帖链接，取自官方公开发布 |
| `rights_manifest.json`、`media_manifest.json`、README、指南 | ✅ 可以 | 本项目自有（media_manifest 记录源 hash 供追溯，非凭证） |
| **完整漫画图像与缩略图**（官方 212 话 + 民间汉化 1 话） | ✅ **可以** | Brief v010 §1/§3.4：用户已明确声明取得公开发布授权，且民间汉化版亦可分享；状态记 `user_declared` |
| 归档封面图（cover） | ❌ 不可以 | 用户授权声明未明确覆盖封面图 |
| 用远程图片热链（`i0.hdslb.com`）或反向代理「变相发布」 | ❌ **不可以** | Brief v009 Phase C 明确禁止的规避手段；本站图片一律随仓库发布 |
| `.env`、Cookie、Token、原始 API dump | ❌ **不可以** | 凭证泄漏 |
| 项目内部文档（Brief / Report / 人工复核 / 执行日志）、manifest、归档目录 | ❌ **不可以** | 内部治理资料 |

**授权边界**：公开完整图片的依据是**收藏者的授权声明**（`user_declared`）——
用户明确说明「已经取得 HBR 漫画公开发布授权，希望所有 HBR 玩家能够直接在线阅读
完整图片」，且民间汉化版本也可以公开分享。本项目**未持有书面许可材料**，
因此不声称已核验书面授权；每一话图片下方均标注来源与署名。
若发现与用户声明冲突的具体权利限制，将记录证据并升级策略层，**不静默更改**。

---

## 1. 当前状态

| 状态项 | 值 |
|---|---|
| `WEBSITE_IMPLEMENTATION_STATUS` | **已完成**（全部页面 + 媒体管线 + 署名 + 自检） |
| `PUBLIC_DEPLOYMENT_STATUS` | **Deployed / Live**（见 v010/v011/v012 Report 真实 URL） |
| `FULL_COMIC_REPUBLICATION_RIGHTS_STATUS` | **User Declared（213/213，无书面材料）** |
| `FULL_COMIC_ONLINE_READING_STATUS` | **Enabled（213 / 213 话可站内阅读完整图）** |

---

## 2. 方式 A：GitHub Actions 自动部署（推荐）

```bash
# 1) 在 GitHub 上新建一个公开仓库，例如 hbr-comic-reader

# 2) 以 public-reader/ 为仓库根（独立仓库；data/ + media/ + scripts/ 一并提交）
cd public-reader
git init
git add .
git commit -m "HBR public reader: initial"
git branch -M main
git remote add origin https://github.com/<your-account>/<your-repo>.git
git push -u origin main

# 3) 仓库 Settings → Pages → Source 选 "GitHub Actions"
#    推送后 Actions 会自动：构建站点 → 自检（23 项）→ 部署
```

工作流文件：`.github/workflows/deploy-public-reader.yml`。
它在 CI 中执行 `build_site.py` → `validate_site.py`，
**任何一步失败都会中止部署**（包括版权/隐私自检失败）。

> CI 中**不运行** `build_catalog.py` / `build_media.py`：这两步依赖项目内部
> manifest 与归档图片，不属于公开仓库内容。`data/*.json` 与 `media/` 作为
> 提交内容进入仓库，CI 只做「数据 → 站点 → 自检 → 部署」。
> manifest 缺失时 `validate_site.py` 的 #01/#12 自动降级为 SKIPPED 并注明
> CI 模式；项目侧全量复跑见 v012 Report §10。

---

## 3. 方式 B：手动发布构建产物（不用 Actions）

```bash
python scripts/build_catalog.py     # 项目侧：manifest → data/
python scripts/build_media.py       # 项目侧：canonical → media/（需 Pillow）
python scripts/build_site.py
python scripts/validate_site.py     # 必须通过

cd site
git init
git add .
git commit -m "deploy"
git branch -M gh-pages               # 或按仓库设置选择分支
git remote add origin https://github.com/<your-account>/<your-repo>.git
git push -f origin gh-pages
```

然后仓库 Settings → Pages → Source 选 `gh-pages` 分支（root）。

---

## 4. 子路径注意事项

如果仓库名不是 `<your-account>.github.io`，站点会挂在
`https://<your-account>.github.io/<your-repo>/` 子路径下。

本站**全部使用相对路径**（`./assets/...`、`../comic/CM_0001/`），
因此子路径下所有 CSS / JS / 图片 / 数据 / 页面链接都有效，**无需配置 base path**。

> 自定义域名时同样无需改路径；只需在仓库 Settings → Pages 里绑定域名，
> 并在 `site/` 放一个 `CNAME` 文件（内容为域名）。当前未放 `CNAME`。

---

## 5. 发布前检查清单

- [ ] `python scripts/validate_site.py` 全部 PASS（或明确标注的 SKIPPED）
- [ ] `git status` 中没有 `.env`、Cookie、Token、原始 API dump
- [ ] 仓库中的位图只出现在 `media/comics/`（及其构建副本 `site/assets/comics/`），
      且与 `media_manifest.json` 一一对应
- [ ] README 的统计数字与站点一致
- [ ] 已阅读站点「关于」页与页脚的授权声明（v011 起 rights.html 已删除，声明浓缩在关于页与页脚），确认表述准确
- [ ] CM_0111 页面明示民间汉化来源、汉化组署名与 `official_source=false`

---

## 6. GitHub Pages 官方限制（Brief v009 §3.8 / v010 §3.3）

| 限制 | 值 | 本站实际 |
|---|---|---|
| 站点大小 | 1 GB | 约 **130 MB**（225 HTML + 4 JSON + 426 张图片） |
| 仓库大小（软限） | 1 GB（建议 < 1 GB） | 约 **130 MB**（不含 site/ 构建副本） |
| 月软带宽 | 100 GB | 单话完整图约 300–600 KB；列表页每页 24 张缩略图（约 40–70 KB/张）且惰性加载，余量充足 |
| 构建时长（Actions） | 6 小时/月 | 单次约 30–60 秒（仅复制媒体 + 渲染 225 页） |

图片加载策略（v011/v012）：**首页即全量缩略图墙，只加载宽 480 缩略图**
（首屏 10 张 eager，其余 lazy + 宽高属性防 CLS），单话页才加载完整图；
`browse.html` 旧入口重定向到首页；`series.html`/`series/<slug>/` 为不出导航的
兼容保留页；主导航固定为 漫画/搜索/关于 三项。

---

## 7. 图片再压缩 / 重新导出

```bash
python scripts/build_media.py --force    # 忽略幂等记录，全部重编码
```

质量参数在 `build_media.py` 头部常量：`FULL_QUALITY=87`、`THUMB_WIDTH=480`、
`THUMB_QUALITY=78`、`PNG_TO_JPEG_MAD_MAX=2.0`。改参数后重跑
`build_media.py --force` + `build_site.py` + `validate_site.py` 即可。
