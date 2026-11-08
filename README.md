# 经典小说（bookzh.com）

单语言、单站点的 Hugo 静态阅读站，三个内容分区：

| 分区 | 目录 / URL | 组织方式 | 阅读导航 |
| --- | --- | --- | --- |
| 长篇小说 | `content/novel/` → `/novel/` | 一个分类一本书，一章一个文件 | 章节目录 + 上一章/下一章 + 阅读进度 |
| 短篇小说 | `content/fiction/` → `/fiction/` | 一个作者一个目录，一篇一页 | 上一篇/下一篇 + 回到作者目录 |
| 短篇故事 | `content/story/` → `/story/` | 一个题材一个合集，一篇一页 | 上一篇/下一篇 + 回到合集目录 |

三个分区共用同一套阅读模板（`layouts/_default/single.html`）和字号/行高设置，新增分区只需要加配置和内容，不需要再写模板。

长篇小说在「分区 → 书」之间还有一层题材索引，共六类（经典 / 爱情 / 冒险 / 悬疑 / 奇幻 / 历史）。题材不用 Hugo taxonomy，而是 `data/novel_genres.yaml`（题材定义）+ `data/novel_genre_map.yaml`（书名 → 题材，一本书恰好一个），导入脚本把结果写进每本书的 `genre` 字段；题材页由脚本生成 `content/novel/genre/<key>/_index.md`。

## 本地运行

需要 Hugo **0.165.0 extended**（版本写在 `hugo.toml` 之外，CI 里固定为同一版本）。

```bash
hugo server
```

打开 <http://localhost:1313/>。`hugo server` 会自动把 baseURL 换成 localhost，无需手工改配置。

构建静态文件：

```bash
hugo --gc --minify --cleanDestinationDir
# 产物在 public/
```

`--cleanDestinationDir` 会删掉 `public/` 里不属于本次构建的旧文件。改过 URL 规则（例如从 `uglyURLs` 切到 front matter `url`）之后必须带上它，否则旧页面会残留在产物里、把文件数撑大。

## 目录结构

```
bookzh/
├─ hugo.toml
├─ archetypes/            book.md / chapter.md / short-story.md / tale.md
├─ content/
│   ├─ _index.md          首页
│   ├─ novel/_index.md + novel/<slug>/_index.md、1.md、2.md…
│   │   └─ novel/genre/_index.md + genre/<key>/_index.md（六个题材页，脚本生成）
│   ├─ fiction/_index.md + fiction/<author-slug>/_index.md、1.md、2.md…
│   └─ story/_index.md + story/<collection-slug>/_index.md、1.md、2.md…
├─ layouts/               模板（三节共用）
├─ assets/css/reader.css  唯一一份 CSS
├─ assets/js/reader.js    唯一一份 JS（目录抽屉、阅读进度）
├─ static/images/covers/  书籍封面（不给章节配图）
├─ mdb/                   本地数据库目录（不提交，仅 sources.example.json 入库）
├─ scripts/import_zblog.py  从 Z-Blog Access 库导入内容
├─ scripts/genre_suggest.py 小说题材自动归类建议
├─ scripts/count_public.py  统计构建产物文件数
└─ data/                  featured.yaml（推荐）、sections.yaml（分区文案）、
                          novel_genres.yaml（题材定义）、novel_genre_map.yaml（书名→题材）
```

约定：

- 目录名、文件名一律 ASCII 小写，中文只出现在 `title`。
- slug 由中文转拼音、全小写、连写不加连字符（如 `/novel/tangjihede/`），重名自动加 `-2` 后缀。
- 章节/篇目文件用不带前导零的序号：`1.md`、`2.md`…，`weight` 同步为 1、2、3…，排序不依赖文件名。
- 页面 URL 由 front matter 的 `url` 指定，不依赖全局 `uglyURLs`：
  - 书籍页 `/novel/<slug>/`，章节页 `/novel/<slug>/1.html`
  - 短篇篇目 `/fiction/<slug>/1.html`，故事篇目 `/story/<slug>/1.html`
  - 分区列表 `/novel/`、`/fiction/`、`/story/`
  - 题材页 `/novel/genre/`、`/novel/genre/jingdian/`、`/novel/genre/aiqing/` 等
- 题材单选：每本书的 `_index.md` 里 `genre` 取 `jingdian / aiqing / maoxian / xuanyi / qihuan / lishi` 之一，改题材只改 `data/novel_genre_map.yaml` 后重跑导入。
- 卷/部不建子目录，用 front matter 的 `part` 字段分组，跨卷的上一章/下一章不会断。
- 一本书一个目录、一章一个文件，不合并成整本单文件。
- 封面可选：只有 `cover` 指向的文件确实存在于 `static/images/covers/` 时才渲染图片；没填或文件缺失时，卡片、首页推荐、书籍详情头部都不显示任何占位块。
- 无作者/无年份/无合集时对应字段留空，页面上整项不显示，不出现“未知”“佚名”这类占位词。
- 模板里的「第 N 章」按 `weight` 顺序计算，和文件名无关。

## 内容导入

内容来自 `mdb/` 下的三个 Access 数据库（`mdb/` 已在 `.gitignore` 中，不提交）：

| 数据库 | 分区参数 | 规则 |
| --- | --- | --- |
| 长篇小说库 | `--db novel` | 分类 1 是旧库栏目说明，导入时忽略（不合并进分区页、不生成页面）；其余 120 个分类各一本书；章节按 `log_Url` 数字升序 |
| 短篇小说库 | `--db fiction` | 按 `log_Meta` 作者归堆，空值用标签表补全，无署名归入“其他” |
| 短篇故事库 | `--db story` | 7 个分类各一个合集，单篇挂所属题材 |

库的具体文件名只写在本机的 `mdb/sources.json` 里，不进仓库；文档统一用「长篇小说库 / 短篇小说库 / 短篇故事库」指代。仓库文档只写相对路径，不要写本地绝对路径。

**先准备配置**：复制占位示例，填入实际的库文件名（复制出来的 `sources.json` 已被 `.gitignore` 排除）。

```bash
copy mdb\sources.example.json mdb\sources.json   # Windows；macOS/Linux 用 cp
```

`sources.json` 需要三个键：`novel`、`fiction`、`story`，分别对应长篇小说库、短篇小说库、短篇故事库；值填库文件名（相对路径按 `mdb/` 或 `--db-dir` 指定的目录解析，也可写绝对路径）。配置缺失、某项为空、仍是 `<...>` 占位符或指向的文件不存在时，脚本会直接说明缺什么、放哪里、怎么补。配置文件路径可用 `--sources` 指定，默认是 `<db-dir>/sources.json`。

```bash
pip install pyodbc pypinyin          # Windows 需装 64 位 Access ODBC 驱动
python scripts/import_zblog.py --db all --dry-run   # 只统计差异，不写文件
python scripts/import_zblog.py --db novel --limit 2 # 小样本试导
python scripts/import_zblog.py --db all             # 日常增量导入
python scripts/import_zblog.py --db all --clean     # 全量重导（先清空三个分区）
```

**mdb 只读**：脚本固定 `ReadOnly=True`，并且一律先把 `.mdb` 复制到系统临时目录再连接，读完删除副本。原库不写、不改、不优化，`mdb/` 目录里也不会留下 `.ldb` 锁文件。

**增量导入**：

- 库里的新记录 → 新增文件；正文有变化 → 覆盖更新；完全没变 → 跳过。
- 库里已删除的记录 → 删除对应的 `.md`（`_index.md` 不受影响）。
- 每次运行输出「新增 / 更新 / 未变 / 删除」四类数量；`--dry-run` 只算不落盘。

**章序与重编号**：

- 数据库里 `log_ID` 升序实际是倒序（`log_ID` 越大章越靠前），阅读顺序是 `log_Url` 的数字升序，脚本按 `log_Url` 排序。
- 重新导入某本书时会比对章序：末尾追加或某章正文更新，正常处理；一旦检测到中间插入、章节删除或顺序变化，整本书按新章序重新生成 `1.md…N.md`（正文未变的章节内容直接复用），旧序号文件被清理。
- 结构变更不会阻塞导入，报告里会列出「本次被重编号的书：书名（旧 N 章 → 新 M 章）」。

> `content/` 由脚本管辖：重复导入会覆盖手工修改，请改模板/配置而不是改生成文件。

## 文件数预算（硬约束）

Cloudflare Pages 单次部署上限 **20,000 个文件**，本站软目标 **18,000**，留出余量。

换算方式：一章/一篇 = 一个 HTML 页面。按每语言 8,000–9,000 个内容页设计，例如一本 100 章的书占 100 个文件。本站当前内容（中文单站）：

- 长篇小说：120 本书 + 6,498 个章节页
- 短篇小说：19 个作者目录 + 665 个篇目页
- 短篇故事：7 个合集 + 1,529 个篇目页
- 另有分区/书/作者/合集/题材 `_index.md`，Markdown 合计 8,849 个

当前实测（`hugo --gc --minify`）：**8,856 个文件，214.2 MB**（含 6 个题材页 + 1 个题材总览页），距 18,000 软目标还有 9,144 个文件，距 20,000 硬上限还有 11,144 个。

控制手段：

- `disableKinds = ['taxonomy', 'term']`，不生成标签/分类聚合页。
- 分区、书、作者、合集页均不分页。
- CSS/JS 各一份，构建时 `minify + fingerprint`，不引入图标库或字体子集。
- 只给书放封面，不给章节配图。
- 首页推荐等可变内容放 `data/`，不在模板里堆页面。

构建后统计文件数与总大小：

```bash
hugo --gc --minify
python scripts/count_public.py
```

输出会列出各顶层目录的文件数、文件总数、总大小、对 18,000 软目标的余量；超过 20,000 时脚本以退出码 1 结束，GitHub Actions 会直接失败。

## 部署

### GitHub Pages（当前方案）

1. 仓库推到 GitHub，**Settings → Pages → Source** 选 “GitHub Actions”。
2. 工作流 `.github/workflows/pages.yml` 会在推送到 `main` 时构建并部署：
   - `actions/configure-pages` 提供 baseURL；
   - `hugo --gc --minify --baseURL "${{ steps.pages.outputs.base_url }}/"` 构建，固定 Hugo 0.165.0；
   - `actions/upload-pages-artifact` + `actions/deploy-pages` 发布。
3. 项目站点地址是 `https://<用户名>.github.io/<仓库名>/`。模板里的链接全部走 `relURL` / `RelPermalink`，子路径不会断。
4. 绑定 `bookzh.com` 后 URL 保持不变（`hugo.toml` 里的默认 baseURL 就是它），不需要改模板。

GitHub Pages 的限制：免费账号需要公开仓库；站点体积 ≤ 1 GB；每月 100 GB 流量软限制；通过 Actions 部署时构建频率受 Actions 配额约束（不要在循环里反复触发部署）。

### 迁移到 Cloudflare Pages

代码不用改，只改平台设置：

- 新建 Cloudflare Pages 项目，连接同一仓库；
- 构建命令：`hugo --gc --minify --baseURL "$CF_PAGES_URL/"`
- 输出目录：`public`
- 环境变量里固定 Hugo 版本（与 GitHub Actions 一致，0.165.0）；
- 单次部署文件数上限 20,000，`scripts/count_public.py` 继续作为上线前检查。

## 关于主题

没有启用 `themes/hugo-book` 子模块。需求里的阅读页结构（38em 正文宽、`clamp()` 字号、移动端目录抽屉、三分区共用模板、无外部字体/图标、Book/Chapter JSON-LD）如果叠在 Hugo Book 上，需要大量覆盖它的模板和 CSS，维护成本反而更高。因此改用仓库内一套轻量自定义主题（`layouts/` + `assets/`），只有一份 CSS 和一份 JS，文件数可控，也方便将来整体复制给英文站。

## SEO

- 每页唯一 title：章节页为「第X章 章名 - 书名 - 经典小说」。
- meta description：章节页优先用 front matter 的 `summary`，否则从正文截取约 120 字。
- 语义化 `article` / `h1`、面包屑导航；上一章/下一章是真实链接，爬虫可走完整本书。
- `sitemap.xml`、`robots.txt`（`enableRobotsTXT = true`）、canonical 均启用。
- 书籍页输出 `Book` JSON-LD，章节页输出 `Chapter` JSON-LD（含书名、作者、章节序号、所属书），列表页输出 `BreadcrumbList`。
- 正文纯静态输出，不依赖外部字体、图标库或统计脚本。
