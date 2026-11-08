# -*- coding: utf-8 -*-
"""
import_zblog.py —— 把旧 Z-Blog Access 数据库增量导入成 Hugo 的三分区内容

数据来源（默认 mdb/ 目录，可用 --db-dir 指定）：
    novel   -> content/novel/    长篇小说库（一个分类一本书）
    fiction -> content/fiction/  短篇小说库（一个作者一个目录）
    story   -> content/story/    短篇故事库（一个分类一个合集）

    三个库的具体文件名放在本地配置里（默认 <db-dir>/sources.json，不提交仓库）；
    仓库不含 mdb/ 下的任何文件，配置格式见 README「内容导入」一节。
    文档、示例、注释里统一用分区名指代，不写文件名。

用法示例：
    python scripts/import_zblog.py --db all --dry-run       # 只看差异，不写文件
    python scripts/import_zblog.py --db novel --limit 3     # 小样本试导
    python scripts/import_zblog.py --db all                 # 增量导入（推荐日常使用）
    python scripts/import_zblog.py --db all --clean         # 清空三个分区后全量重建

约定：
    - mdb 只读：连接串固定 ReadOnly=True；并且一律先复制到临时目录再读，
      读完删除副本，保证不在 mdb/ 目录留下任何文件（包括 .ldb 锁文件）。
    - 目录名 / 文件名全部 ASCII 小写；中文只出现在 title。
    - slug：中文转拼音、全小写、连写不加连字符；重名自动加 -2 后缀。
    - 章节 / 篇目文件名用不带前导零的序号：1.md、2.md…；weight 同步为 1、2、3…。
      页面 URL 由 front matter 的 url 指定：
      书籍章节  /novel/<slug>/1.html
      短篇篇目  /fiction/<slug>/1.html
      故事篇目  /story/<slug>/1.html
    - 卷 / 部不建子目录，写进 front matter 的 part 字段。
    - 无署名时 author 留空，不写“未知”“佚名”这类占位词。
    - 增量：正文未变的文件跳过；库中删除的记录会移除对应文件。
"""

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict

import yaml

try:
    import pyodbc
except ImportError:
    sys.exit("缺少 pyodbc，请先执行：pip install pyodbc")

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MDB_DIR = os.path.join(ROOT, "mdb")
CONTENT_DIR = os.path.join(ROOT, "content")

# 每个分区对应的内容目录。数据库文件名不在代码里，统一从本地配置文件读取。
SECTION_DIRS = {
    "novel": "novel",
    "fiction": "fiction",
    "story": "story",
}

# 分区对应的中文叫法，只用于错误提示
SECTION_LABELS = {
    "novel": "长篇小说库",
    "fiction": "短篇小说库",
    "story": "短篇故事库",
}

# 运行时由 load_sources() 填充：{分区: 数据库绝对路径}
SOURCES = {}

# 分区首页（content/<section>/_index.md）的标题与简介。
# 不写这个文件时，Hugo 会用目录名自动生成英文标题（story -> Stories），
# 所以三个分区都显式写一份。
SECTION_INDEX = {
    "novel": ("长篇小说", "一本书多章，按书阅读；支持章节目录与上一章/下一章。", 1),
    "fiction": ("短篇小说", "单篇成篇的文学作品，按作者归类。", 2),
    "story": ("短篇故事", "按题材合集归类的通俗故事。", 3),
}

# 同一作者的不同写法合并到统一名字（键是不含标点的规范化名字）
AUTHOR_ALIASES = {
    "艾阿西莫夫": "艾萨克·阿西莫夫",
    "艾萨克阿西莫夫": "艾萨克·阿西莫夫",
    "弗波尔": "弗雷德里克·波尔",
    "弗雷德里克波尔": "弗雷德里克·波尔",
    "布阿尔迪斯": "布赖恩·奥尔迪斯",
    "布里安阿尔迪斯": "布赖恩·奥尔迪斯",
    "布赖恩奥尔迪斯": "布赖恩·奥尔迪斯",
    "亨利斯莱瑟": "亨利·斯莱萨",
    "亨利斯莱萨": "亨利·斯莱萨",
    "尼索维托夫": "尼·索维托夫",
}

# 这些不是作者名，导入时按“无署名”处理（author 留空）
JUNK_AUTHORS = {
    "佚名",
    "不详",
    "未知",
    "整理",
    "杂谈",
    "段子",
    "笑话",
    "爆笑",
    "鬼故事",
    "故事",
    "网络",
    "转载",
    "转",
    "摘",
    "编辑",
    "文摘",
    "无",
    "爱情故事",
    "情感故事",
    "人生故事",
    "幽默故事",
    "哲理故事",
    "科幻故事",
}

# 只匹配 章 / 回 / 节 等“章级”单位
CHAPTER_RE = re.compile(
    r"第[零〇○一二三四五六七八九十百千万廿卅两0-9]+(?:封信|信|章|回|节|篇|话|集)"
)
# 卷 / 部 / 编 是分卷单位（不算章）
PART_UNIT_RE = re.compile(r"^第[零〇○一二三四五六七八九十百千万廿卅两0-9]+(?:卷|部|编)$")
VOLUME_WORDS = {"上卷", "中卷", "下卷", "上部", "中部", "下部", "上册", "中册", "下册"}

SUMMARY_LENGTH = 110
DRY_RUN = False


# ============================================================
# 数据库：只读 + 临时副本
# ============================================================


def display_path(path):
    """把路径转成相对仓库根的短路径，便于提示信息阅读。"""
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def load_sources(path, sections):
    """
    读取本地数据库配置（JSON），返回 {分区: 数据库绝对路径}。

    配置文件不提交仓库：整个 mdb/ 目录被 .gitignore 忽略，实际文件名只写在
    本机的 sources.json 里。缺文件、缺键、还是占位符、库文件不存在时，
    都给出可直接照做的提示。
    """
    shown = display_path(path)
    if not os.path.isfile(path):
        sys.exit(
            "找不到数据库配置文件：" + shown + "\n"
            "  位置：默认放在 mdb/ 下，也可以用 --sources 指定别的路径\n"
            '  补法：在 mdb/ 下新建 sources.json（JSON 对象），填入各库的实际文件名\n'
            "  需要键：novel、fiction、story（分别对应长篇小说库、短篇小说库、短篇故事库）"
        )

    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        sys.exit(
            "数据库配置文件不是合法 JSON：" + shown + "（第 " + str(exc.lineno) + " 行）\n"
            '  期望内容：{"novel": "文件名", "fiction": "文件名", "story": "文件名"}'
        )

    if not isinstance(data, dict):
        sys.exit(
            "数据库配置文件的内容应为 JSON 对象：" + shown + "\n"
            "  需要键：novel、fiction、story，值填各库的文件名"
        )

    resolved = {}
    problems = []
    for section in sections:
        label = SECTION_LABELS[section]
        value = data.get(section)
        if not isinstance(value, str) or not value.strip():
            problems.append("缺少「" + section + "」（" + label + "）的文件名")
            continue
        value = value.strip()
        if "<" in value or ">" in value:
            problems.append("「" + section + "」（" + label + "）还是示例占位符：" + value)
            continue
        db_path = value if os.path.isabs(value) else os.path.join(MDB_DIR, value)
        if not os.path.isfile(db_path):
            problems.append(
                "「" + section + "」（" + label + "）指向的库文件不存在：" + value
                + "（相对路径按 " + display_path(MDB_DIR) + " 解析）"
            )
            continue
        resolved[section] = db_path

    if problems:
        sys.exit(
            "数据库配置不可用：" + shown + "\n  - " + "\n  - ".join(problems) + "\n"
            "  需要键：novel、fiction、story（长篇小说库 / 短篇小说库 / 短篇故事库）\n"
            "  补法：按上面提示补齐后重跑，或用 --sources 指向正确的配置文件"
        )

    return resolved


def connect(db_path):
    """
    打开 Access 数据库的只读副本。

    先复制到临时目录再连接，原库不写、不改、不优化，
    mdb/ 目录里也不会产生 .ldb 锁文件。连接用 close_db() 关闭并删副本。
    """
    driver = None
    for name in pyodbc.drivers():
        if "Access Driver" in name:
            driver = name
            break
    if not driver:
        sys.exit(
            "未找到 Microsoft Access 驱动。请安装 64 位 Access ODBC 驱动，"
            "并确认 Python 位数与驱动一致。"
        )

    tmp_dir = tempfile.mkdtemp(prefix="bookzh-mdb-")
    tmp_path = os.path.join(tmp_dir, os.path.basename(db_path))
    shutil.copy2(os.path.abspath(db_path), tmp_path)
    conn = pyodbc.connect(f"DRIVER={{{driver}}};DBQ={tmp_path};ReadOnly=True;")
    return conn, tmp_dir


def close_db(conn, tmp_dir=None):
    """关闭连接，并删除临时副本目录。"""
    try:
        conn.close()
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
# 文本与 Markdown 工具
# ============================================================


def plain_text(raw):
    """把 Z-Blog 正文里的 HTML / UBB / 分页标记清理成朴素文本，保留段落。"""
    if not raw:
        return ""
    text = raw
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<#[^>]*#>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"</(?:p|div|h[1-6]|li|tr)>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")

    # UBB 标签
    text = re.sub(
        r"\[(?:b|i|u|url|img|align|color|size|font|quote|code|list|\*|em|strong)"
        r"(?:=[^\]]*)?\]",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\[/?(?:b|i|u|url|img|align|color|size|font|quote|code|list|\*|em|strong)\]",
        "",
        text,
        flags=re.I,
    )

    # 保守清理整行的广告/来源残留
    clean_lines = []
    for line in text.split("\n"):
        line = line.rstrip()
        stripped = line.strip()
        if stripped and len(stripped) < 90 and re.match(
            r"^(本文来自|来源[:：]|原文链接|更多精彩|请记住本站|本站地址|"
            r"手机阅读|广告合作|（?广告）?)",
            stripped,
        ):
            continue
        clean_lines.append(line)
    text = "\n".join(clean_lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def summarize(text, limit=SUMMARY_LENGTH):
    """截取一段用于 meta description / 列表摘要的文字。"""
    s = re.sub(r"\s+", " ", text or "").strip()
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit].rstrip("，。；、,;:：") + "…"


def yaml_str(value):
    """用 JSON 的双引号字符串写法，合法且安全地写入 YAML。"""
    return json.dumps(str(value), ensure_ascii=False)


def front_matter(fields):
    """按顺序生成 YAML front matter，空值自动省略。"""
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {yaml_str(value)}")
    lines.append("---")
    return "\n".join(lines)


def render_md(fields, body):
    """生成完整 Markdown 文本（UTF-8、LF）。"""
    return front_matter(fields) + "\n\n" + (body or "") + "\n"


def read_md(path):
    """读入脚本自己生成的 Markdown，返回 (front matter dict, 全文)。"""
    with open(path, encoding="utf-8") as handle:
        raw = handle.read().replace("\r\n", "\n")
    data = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip()
                try:
                    data[key.strip()] = json.loads(value) if value.startswith('"') else value
                except json.JSONDecodeError:
                    data[key.strip()] = value
    return data, raw


# ============================================================
# slug
# ============================================================


def slugify(text, fallback="item"):
    """
    中文转拼音、全小写、连写不加连字符；英文/数字原样保留。
    例：“堂吉诃德” -> tangjikede
    """
    s = (text or "").strip()
    if not s:
        return fallback
    if lazy_pinyin:
        s = "".join(lazy_pinyin(s))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s or fallback


def unique_slug(base, used):
    """重名自动追加 -2、-3…"""
    slug = base
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def old_dirname(name):
    """旧版目录名规则（cate_Intro），仅用于定位历史目录。"""
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", name or "").strip("-").lower()
    return slug or "item"


# ============================================================
# 作者
# ============================================================


def author_key(name):
    """作者名规范化：全角转半角、去标点空格、小写。"""
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"[^\w\u4e00-\u9fff]", "", s).lower()


def canonical_author(name):
    """返回规范作者名；空值或占位词返回空字符串。"""
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ""
    if s in JUNK_AUTHORS:
        return ""
    key = author_key(s)
    if not key:
        return ""
    if key in JUNK_AUTHORS:
        return ""
    return AUTHOR_ALIASES.get(key, s)


# ============================================================
# 标题解析
# ============================================================


def strip_book_prefix(title, book_name):
    """去掉标题前面的书名，并压缩空白。"""
    t = (title or "").strip()
    if book_name and t.startswith(book_name):
        t = t[len(book_name) :].strip()
    return re.sub(r"\s+", " ", t)


def dedupe_chapter_title(title):
    """去掉“第一章 第一章”这类重复章号。"""
    t = title.strip()
    pattern = re.compile(
        r"^(第[零〇○一二三四五六七八九十百千万廿卅两0-9]+(?:章|回|节|篇|话|集|封信|信))"
        r"\s+\1(?:\s+|$)(.*)$"
    )
    match = pattern.match(t)
    if match:
        rest = match.group(2).strip()
        return (match.group(1) + " " + rest).strip()
    return t


def parse_novel_title(rest, state):
    """
    解析书名之后的标题，返回 (kind, title, part_label, state)。
    kind: chapter / part / plain
    """
    tokens = rest.split(" ")
    parts = []
    while tokens and PART_UNIT_RE.match(tokens[0]):
        parts.append(tokens.pop(0))
    remainder = " ".join(tokens).strip()

    has_chapter = bool(CHAPTER_RE.search(remainder))

    if has_chapter:
        title = dedupe_chapter_title(remainder)
        for component in parts:
            if component.endswith(("卷", "编")):
                state["volume"] = component
            elif component.endswith("部"):
                state["part"] = component
        label = " · ".join(x for x in [state["volume"], state["part"]] if x)
        return "chapter", title, label, state

    if parts:
        # 只有卷/部标题：可能是真正的分卷说明页，也可能是空壳
        if len(parts) >= 2:
            state["volume"] = " ".join(parts[:-1])
            state["part"] = parts[-1]
            label = rest
        elif parts[0].endswith(("卷", "编")):
            state["volume"] = rest
            state["part"] = ""
            label = rest
        else:
            state["part"] = rest
            label = " · ".join(x for x in [state["volume"], rest] if x)
        return "part", rest, label, state

    if rest in VOLUME_WORDS:
        state["volume"] = rest
        state["part"] = ""
        return "part", rest, rest, state

    # 前言、尾声、人物表、日期、人物名等普通篇目
    label = " · ".join(x for x in [state["volume"], state["part"]] if x)
    return "plain", rest, label, state


# ============================================================
# 增量写出：新增 / 更新 / 未变 / 删除
# ============================================================


class Counts:
    def __init__(self):
        self.new = 0
        self.updated = 0
        self.unchanged = 0
        self.deleted = 0

    def add(self, other):
        self.new += other.new
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.deleted += other.deleted

    def line(self):
        return (
            f"新增 {self.new} / 更新 {self.updated} / "
            f"未变 {self.unchanged} / 删除 {self.deleted}"
        )


def emit_md(path, fields, body, counts):
    """按内容差异决定跳过、更新还是新增（dry-run 只计数不落盘）。"""
    content = render_md(fields, body)
    if os.path.exists(path):
        _, old = read_md(path)
        if old == content:
            counts.unchanged += 1
            return
        counts.updated += 1
        if DRY_RUN:
            return
    else:
        counts.new += 1
        if DRY_RUN:
            return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def delete_md(path, counts):
    """删除库中已不存在的记录所对应的文件。"""
    if os.path.isfile(path):
        counts.deleted += 1
        if not DRY_RUN:
            os.remove(path)


def delete_stale(dir_path, planned, counts):
    """删除目录里本次没有计划的 .md（_index.md 永远保留）。"""
    if not os.path.isdir(dir_path):
        return
    for name in os.listdir(dir_path):
        if not name.endswith(".md") or name == "_index.md":
            continue
        if name in planned:
            continue
        delete_md(os.path.join(dir_path, name), counts)


# ============================================================
# 目录改名（slug 变化时不留旧目录）
# ============================================================


def scan_index_dirs(out_dir):
    """扫描现有目录，返回 {_index.md 的 title: 目录路径}。"""
    found = {}
    if not os.path.isdir(out_dir):
        return found
    for name in os.listdir(out_dir):
        path = os.path.join(out_dir, name)
        if not os.path.isdir(path):
            continue
        index = os.path.join(path, "_index.md")
        if not os.path.isfile(index):
            continue
        data, _ = read_md(index)
        title = str(data.get("title", "")).strip()
        if title:
            found[title] = path
    return found


def apply_dir_moves(out_dir, moves):
    """两阶段改名，避免新旧目录互相占用。"""
    if not moves:
        return
    print(f"[slug] 需要改名的目录：{len(moves)} 个")
    for old_dir, new_dir in moves:
        print(f"       {os.path.basename(old_dir)} -> {os.path.basename(new_dir)}")
    if DRY_RUN:
        return
    staged = []
    for index, (old_dir, new_dir) in enumerate(moves):
        tmp = os.path.join(out_dir, f".rename-{index}")
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.rename(old_dir, tmp)
        staged.append((tmp, new_dir))
    for tmp, new_dir in staged:
        if os.path.isdir(new_dir):
            shutil.rmtree(new_dir)
        os.rename(tmp, new_dir)


def reader_dir(new_dir, moves):
    """dry-run 时目录还没改名，读旧目录，保证差异统计准确。"""
    if os.path.isdir(new_dir):
        return new_dir
    for old_dir, moved_to in moves:
        if os.path.normpath(moved_to) == os.path.normpath(new_dir):
            return old_dir
    return new_dir


# ============================================================
# 长篇小说：一个分类 = 一本书
# ============================================================


def load_genre_map():
    """读 data/novel_genre_map.yaml，返回 {书名: 题材 key}。"""
    path = os.path.join(ROOT, "data", "novel_genre_map.yaml")
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        rows = yaml.safe_load(handle) or []
    return {
        str(row.get("title") or "").strip(): str(row.get("genre") or "").strip()
        for row in rows
        if row.get("title") and row.get("genre")
    }


def load_genre_labels():
    """读 data/novel_genres.yaml，返回 {key: 中文名}。"""
    path = os.path.join(ROOT, "data", "novel_genres.yaml")
    with open(path, encoding="utf-8") as handle:
        genres = yaml.safe_load(handle) or []
    return {genre["key"]: genre["name"] for genre in genres}


GENRE_LABELS = load_genre_labels()


def write_genre_pages(counts):
    """
    按 data/novel_genres.yaml 生成六个题材页。
    内容目录由脚本管辖，--clean 之后题材页会自动重建。
    """
    path = os.path.join(ROOT, "data", "novel_genres.yaml")
    with open(path, encoding="utf-8") as handle:
        genres = yaml.safe_load(handle) or []

    base = os.path.join(CONTENT_DIR, "novel", "genre")
    if not DRY_RUN:
        os.makedirs(base, exist_ok=True)

    # 题材容器页 /novel/genre/：列出六个题材入口；模板里按 layout=genre 把它
    # 从书库卡片列表中排除，所以书籍数量不会被它撑大。
    container_path = os.path.join(base, "_index.md")
    container = (
        "---\n"
        'title: "题材"\n'
        'summary: "按题材浏览长篇小说。"\n'
        'layout: "genre"\n'
        "weight: 0\n"
        "---\n"
    )
    if os.path.exists(container_path):
        _, old = read_md(container_path)
        if old == container:
            counts.unchanged += 1
        else:
            counts.updated += 1
            if not DRY_RUN:
                with open(container_path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(container)
    else:
        counts.new += 1
        if not DRY_RUN:
            with open(container_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(container)

    for index, genre in enumerate(genres, start=1):
        emit_md(
            os.path.join(base, genre["key"], "_index.md"),
            {
                "title": genre["name"],
                "summary": genre.get("intro") or "",
                "layout": "genre",
                "genre_key": genre["key"],
                "weight": index,
            },
            "",
            counts,
        )


def import_novels(limit, counts):
    db_path = SOURCES["novel"]
    conn, tmp_dir = connect(db_path)
    cur = conn.cursor()

    out_dir = os.path.join(CONTENT_DIR, "novel")
    stats = {
        "books": 0,
        "pages": 0,
        "skipped": 0,
        "stub_parts": 0,
        "books_with_author": 0,
        "genre_counts": Counter(),
    }
    author_counts = Counter()
    renumbered = []
    slug_table = {}
    genre_map = load_genre_map()

    # 分类 1 是旧库的栏目说明，不属于书籍内容，直接忽略：
    # 既不合并进 content/novel/_index.md，也不生成任何页面。
    categories = cur.execute(
        "SELECT cate_ID, cate_Name, cate_Intro, cate_Meta, cate_FullUrl, cate_Order "
        "FROM blog_Category WHERE cate_ID > 1 ORDER BY cate_ID"
    ).fetchall()

    # ---------- slug：全部拼音连写，重名加后缀 ----------
    used = set()
    slugs = {}
    for cat in categories:
        title = (cat.cate_Name or "").strip()
        slugs[cat.cate_ID] = unique_slug(slugify(title, fallback=f"book{cat.cate_ID}"), used)
        slug_table[title] = slugs[cat.cate_ID]

    # ---------- 目录改名：旧目录挪到新 slug，不留旧目录 ----------
    if not DRY_RUN:
        os.makedirs(out_dir, exist_ok=True)
    existing_dirs = scan_index_dirs(out_dir)
    moves = []
    for cat in categories:
        title = (cat.cate_Name or "").strip()
        new_dir = os.path.join(out_dir, slugs[cat.cate_ID])
        old_dir = existing_dirs.get(title)
        if not old_dir:
            # 兼容历史目录（早期用 cate_Intro 生成）
            guess = os.path.join(out_dir, old_dirname(cat.cate_Intro))
            if os.path.isdir(guess) and os.path.normpath(guess) != os.path.normpath(new_dir):
                old_dir = guess
        if old_dir and os.path.normpath(old_dir) != os.path.normpath(new_dir):
            moves.append((old_dir, new_dir))
    apply_dir_moves(out_dir, moves)

    # ---------- 分区首页 ----------
    emit_md(
        os.path.join(out_dir, "_index.md"),
        {
            "title": SECTION_INDEX["novel"][0],
            "summary": SECTION_INDEX["novel"][1],
            "weight": SECTION_INDEX["novel"][2],
        },
        "",
        counts,
    )

    # ---------- 逐本导入 ----------
    for cat in categories:
        book_name = (cat.cate_Name or "").strip()
        slug = slugs[cat.cate_ID]
        author = (cat.cate_FullUrl or "").strip()  # 保留库里的原值（含全角括号）
        summary = (cat.cate_Meta or "").strip()

        arts = cur.execute(
            "SELECT log_ID, log_Url, log_Title, log_Content, log_Level "
            "FROM blog_Article WHERE log_CateID = ? ORDER BY log_ID",
            cat.cate_ID,
        ).fetchall()

        # 库里的记录是倒序写入的；log_Url 的数字顺序才是阅读顺序
        def order_key(row):
            url = (row.log_Url or "").strip()
            if url.isdigit():
                return (0, int(url))
            return (1, int(row.log_ID))

        arts = sorted(arts, key=order_key)

        book_dir = os.path.join(out_dir, slug)
        entries = []
        state = {"volume": "", "part": ""}
        summary_from_intro = ""

        for row in arts:
            raw_title = (row.log_Title or "").strip()
            body = plain_text(row.log_Content)
            rest = strip_book_prefix(raw_title, book_name)

            if rest == "内容简介":
                if not summary:
                    summary_from_intro = summarize(body, 200)
                continue

            kind, title, part, state = parse_novel_title(rest, state)

            # 空壳分卷（正文只有 <!--more-->）只用来更新分卷上下文
            if len(body) < 20:
                stats["skipped"] += 1
                if kind == "part":
                    stats["stub_parts"] += 1
                continue

            if not title:
                title = rest or raw_title
            entries.append(
                {
                    "id": int(row.log_ID),
                    "title": title,
                    "part": part,
                    "summary": summarize(body),
                    "body": body,
                }
            )

        # 旧文件 -> source_id 映射（用于“正文未变时复用文件”）
        read_dir = reader_dir(book_dir, moves)
        old_by_id = {}
        old_ids = []
        if os.path.isdir(read_dir):
            for name in sorted(os.listdir(read_dir), key=lambda n: (len(n), n)):
                if not re.match(r"^\d+\.md$", name):
                    continue
                data, raw = read_md(os.path.join(read_dir, name))
                try:
                    source_id = int(str(data.get("source_id", "")).strip())
                except ValueError:
                    source_id = None
                if source_id is None:
                    continue
                old_by_id[source_id] = (os.path.join(read_dir, name), raw)
                old_ids.append(source_id)

        new_ids = [entry["id"] for entry in entries]
        # 末尾追加不算重编号；中间插入、删除、顺序变化都整本重排
        is_renumber = old_ids != new_ids[: len(old_ids)]
        if is_renumber and old_ids:
            renumbered.append((book_name, len(old_ids), len(new_ids)))

        planned = set()
        for index, entry in enumerate(entries, start=1):
            target_name = f"{index}.md"
            planned.add(target_name)
            target = os.path.join(book_dir, target_name)
            fields = {
                "title": entry["title"],
                "weight": index,
                "part": entry["part"],
                "summary": entry["summary"],
                "source_id": entry["id"],
                "url": f"/novel/{slug}/{index}.html",
            }
            expected = render_md(fields, entry["body"])

            # 目标文件已存在：按内容判断未变/更新
            if os.path.exists(target):
                _, old = read_md(target)
                if old == expected:
                    counts.unchanged += 1
                else:
                    counts.updated += 1
                    if not DRY_RUN:
                        with open(target, "w", encoding="utf-8", newline="\n") as handle:
                            handle.write(expected)
                continue

            # 章序变化但正文未变：直接改名，复用旧内容
            reused = old_by_id.get(entry["id"])
            if reused and reused[1] == expected:
                counts.unchanged += 1
                if not DRY_RUN:
                    os.rename(reused[0], target)
                continue

            if entry["id"] in old_by_id:
                counts.updated += 1
            else:
                counts.new += 1
            if not DRY_RUN:
                os.makedirs(book_dir, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(expected)

        delete_stale(read_dir, planned, counts)

        if not summary:
            summary = summary_from_intro or f"{book_name} 的章节正文。"

        # 题材：以 data/novel_genre_map.yaml 为准；缺省归入经典小说。
        genre = genre_map.get(book_name) or "jingdian"
        stats["genre_counts"][genre] += 1

        emit_md(
            os.path.join(book_dir, "_index.md"),
            {
                "title": book_name,
                "author": author,
                "summary": summary,
                "genre": genre,
                "layout": "book",
                "weight": int(cat.cate_ID),
            },
            "",
            counts,
        )

        stats["books"] += 1
        if author:
            stats["books_with_author"] += 1
            author_counts[author] += len(entries)
        stats["pages"] += len(entries)
        print(f"  [novel] {slug:<32} {stats['books']:>3} 本 / {len(entries):>4} 页  {book_name}")

        if limit and stats["books"] >= limit:
            break

    close_db(conn, tmp_dir)

    # 六个题材页（放在 content/novel/genre/<key>/，URL /novel/genre/<key>/）
    write_genre_pages(counts)

    return stats, author_counts, renumbered, slug_table


# ============================================================
# 短篇小说：一个作者 = 一个目录
# ============================================================


def is_announcement(row):
    """站点开通公告不算正文。"""
    title = (row.log_Title or "").strip()
    return "正式开通" in title or "正式建立" in title


def import_fiction(limit, counts):
    db_path = SOURCES["fiction"]
    conn, tmp_dir = connect(db_path)
    cur = conn.cursor()

    out_dir = os.path.join(CONTENT_DIR, "fiction")
    stats = {"authors": 0, "pages": 0, "skipped": 0, "credited": 0, "tag_filled": 0}
    author_counts = Counter()

    tags = {
        row.tag_ID: (row.tag_Name or "").strip()
        for row in cur.execute("SELECT tag_ID, tag_Name FROM blog_Tag").fetchall()
    }

    def tag_author(row):
        """log_Meta 为空时，用文章标签补全作者。"""
        names = set()
        for tag_id in re.findall(r"\{(\d+)\}", row.log_Tag or ""):
            name = tags.get(int(tag_id))
            if name and name != "短篇小说":
                canon = canonical_author(name)
                if canon:
                    names.add(canon)
        return next(iter(names)) if len(names) == 1 else ""

    rows = cur.execute(
        "SELECT log_ID, log_Title, log_Content, log_Meta, log_Tag "
        "FROM blog_Article ORDER BY log_ID"
    ).fetchall()

    groups = defaultdict(list)
    for row in rows:
        if is_announcement(row):
            stats["skipped"] += 1
            continue
        author = canonical_author(row.log_Meta)
        if not author:
            author = tag_author(row)
            if author:
                stats["tag_filled"] += 1
        group = author if author else "其他"
        groups[group].append(row)

    # 作者按篇数从多到少排列；“其他”放最后
    ordered = sorted(
        groups.items(),
        key=lambda item: (item[0] == "其他", -len(item[1]), item[0]),
    )

    # slug：全部拼音连写，重名加后缀
    used = set()
    slug_map = {}
    for name, _items in ordered:
        slug_map[name] = unique_slug(slugify(name, fallback="author"), used)

    # 目录改名（旧目录可能是英文作者名）
    if not DRY_RUN:
        os.makedirs(out_dir, exist_ok=True)
    existing_dirs = scan_index_dirs(out_dir)
    moves = []
    for name in slug_map:
        new_dir = os.path.join(out_dir, slug_map[name])
        old_dir = existing_dirs.get(name)
        if old_dir and os.path.normpath(old_dir) != os.path.normpath(new_dir):
            moves.append((old_dir, new_dir))
    apply_dir_moves(out_dir, moves)

    emit_md(
        os.path.join(out_dir, "_index.md"),
        {
            "title": SECTION_INDEX["fiction"][0],
            "summary": SECTION_INDEX["fiction"][1],
            "weight": SECTION_INDEX["fiction"][2],
        },
        "",
        counts,
    )

    for name, items in ordered:
        slug = slug_map[name]
        group_dir = os.path.join(out_dir, slug)
        if not DRY_RUN:
            os.makedirs(group_dir, exist_ok=True)

        items.sort(key=lambda row: int(row.log_ID))
        planned = set()
        for index, row in enumerate(items, start=1):
            body = plain_text(row.log_Content)
            if not body:
                stats["skipped"] += 1
                continue
            title = (row.log_Title or "").strip()
            if not title:
                title = f"第{index}篇"
            filename = f"{index}.md"
            planned.add(filename)

            if name != "其他":
                author_counts[name] += 1
                stats["credited"] += 1
            stats["pages"] += 1

            emit_md(
                os.path.join(group_dir, filename),
                {
                    "title": title,
                    "weight": index,
                    "author": "" if name == "其他" else name,
                    "summary": summarize(body),
                    "source_id": int(row.log_ID),
                    "url": f"/fiction/{slug}/{index}.html",
                },
                body,
                counts,
            )

        delete_stale(reader_dir(group_dir, moves), planned, counts)

        emit_md(
            os.path.join(group_dir, "_index.md"),
            {
                "title": name,
                "author": "" if name == "其他" else name,
                "summary": "未署名的短篇作品。" if name == "其他" else f"{name} 的短篇作品。",
                "weight": stats["authors"] + 1,
            },
            "",
            counts,
        )

        stats["authors"] += 1
        print(f"  [fiction] {slug:<20} {len(items):>3} 篇  {name}")
        if limit and stats["authors"] >= limit:
            break

    close_db(conn, tmp_dir)
    return stats, author_counts


# ============================================================
# 短篇故事：一个分类 = 一个合集
# ============================================================


def import_story(limit, counts):
    db_path = SOURCES["story"]
    conn, tmp_dir = connect(db_path)
    cur = conn.cursor()

    out_dir = os.path.join(CONTENT_DIR, "story")
    stats = {"collections": 0, "pages": 0, "skipped": 0, "credited": 0}
    author_counts = Counter()

    cats = cur.execute(
        "SELECT cate_ID, cate_Name, cate_Intro FROM blog_Category ORDER BY cate_ID"
    ).fetchall()

    # slug：分类中文名转拼音连写
    used = set()
    slug_map = {}
    for cat in cats:
        name = (cat.cate_Name or "").strip()
        slug_map[cat.cate_ID] = unique_slug(slugify(name, fallback=f"story{cat.cate_ID}"), used)

    if not DRY_RUN:
        os.makedirs(out_dir, exist_ok=True)
    existing_dirs = scan_index_dirs(out_dir)
    moves = []
    for cat in cats:
        name = (cat.cate_Name or "").strip()
        new_dir = os.path.join(out_dir, slug_map[cat.cate_ID])
        old_dir = existing_dirs.get(name)
        if old_dir and os.path.normpath(old_dir) != os.path.normpath(new_dir):
            moves.append((old_dir, new_dir))
    apply_dir_moves(out_dir, moves)

    emit_md(
        os.path.join(out_dir, "_index.md"),
        {
            "title": SECTION_INDEX["story"][0],
            "summary": SECTION_INDEX["story"][1],
            "weight": SECTION_INDEX["story"][2],
        },
        "",
        counts,
    )

    for cat in cats:
        slug = slug_map[cat.cate_ID]
        name = (cat.cate_Name or "").strip()
        rows = cur.execute(
            "SELECT log_ID, log_Title, log_Content, log_Meta "
            "FROM blog_Article WHERE log_CateID = ? ORDER BY log_ID",
            cat.cate_ID,
        ).fetchall()

        rows = [row for row in rows if not is_announcement(row)]
        rows.sort(key=lambda row: int(row.log_ID))

        group_dir = os.path.join(out_dir, slug)
        if not DRY_RUN:
            os.makedirs(group_dir, exist_ok=True)

        planned = set()
        index = 0
        for row in rows:
            body = plain_text(row.log_Content)
            if not body:
                stats["skipped"] += 1
                continue
            author = canonical_author(row.log_Meta)
            title = (row.log_Title or "").strip() or f"第{index + 1}篇"
            index += 1
            filename = f"{index}.md"
            planned.add(filename)

            stats["pages"] += 1
            if author:
                author_counts[author] += 1
                stats["credited"] += 1

            emit_md(
                os.path.join(group_dir, filename),
                {
                    "title": title,
                    "weight": index,
                    "author": author,
                    "collection": name,
                    "summary": summarize(body),
                    "source_id": int(row.log_ID),
                    "url": f"/story/{slug}/{index}.html",
                },
                body,
                counts,
            )

        delete_stale(reader_dir(group_dir, moves), planned, counts)

        emit_md(
            os.path.join(group_dir, "_index.md"),
            {
                "title": name,
                "summary": f"{name}题材合集。",
                "weight": int(cat.cate_ID),
            },
            "",
            counts,
        )

        stats["collections"] += 1
        print(f"  [story] {slug:<20} {index:>4} 篇  {name}")
        if limit and stats["collections"] >= limit:
            break

    close_db(conn, tmp_dir)
    return stats, author_counts


def write_tale_author_index(counts):
    """一个聚合页展示短篇故事的全部作者，避免生成上千个小页面。"""
    emit_md(
        os.path.join(CONTENT_DIR, "story", "author-index.md"),
        {"title": "作者索引", "layout": "author-index", "weight": 9999},
        "按作者汇总短篇故事的全部篇目。",
        counts,
    )


# ============================================================
# 短篇库标签表对照
# ============================================================


def report_tag_differences():
    """短篇库标签表 vs log_Meta 作者名对照，供人工校对。"""
    db_path = SOURCES["fiction"]
    conn, tmp_dir = connect(db_path)
    cur = conn.cursor()

    tags = {
        row.tag_ID: (row.tag_Name or "").strip()
        for row in cur.execute("SELECT tag_ID, tag_Name FROM blog_Tag").fetchall()
    }
    tag_counts = {
        (row.tag_Name or "").strip(): int(row.tag_Count or 0)
        for row in cur.execute("SELECT tag_Name, tag_Count FROM blog_Tag").fetchall()
    }

    rows = cur.execute(
        "SELECT log_ID, log_Title, log_Meta, log_Tag FROM blog_Article ORDER BY log_ID"
    ).fetchall()

    meta_counts = Counter()
    mismatches = []
    for row in rows:
        if is_announcement(row):
            continue
        meta_author = canonical_author(row.log_Meta)
        if meta_author:
            meta_counts[meta_author] += 1

        tag_names = set()
        for tag_id in re.findall(r"\{(\d+)\}", row.log_Tag or ""):
            name = tags.get(int(tag_id))
            if name and name != "短篇小说":
                tag_names.add(name)
        tag_author = canonical_author(next(iter(tag_names))) if len(tag_names) == 1 else ""
        if meta_author != tag_author:
            mismatches.append((row.log_ID, row.log_Title, meta_author, sorted(tag_names)))

    print("\n[短篇库] 标签表与 log_Meta 作者对照（以 log_Meta 为准）：")
    names = sorted(set(meta_counts) | set(tag_counts), key=lambda x: -meta_counts.get(x, 0))
    for name in names:
        if name == "短篇小说":
            continue
        print(f"  {name:<12} 标签表 {tag_counts.get(name, 0):>3} 篇 / log_Meta {meta_counts.get(name, 0):>3} 篇")
    print(f"  逐篇不一致：{len(mismatches)} 篇")
    for item in mismatches[:10]:
        print(f"    #{item[0]} {item[1]} | log_Meta={item[2] or '（空）'} | 标签={item[3]}")

    close_db(conn, tmp_dir)
    return meta_counts


# ============================================================
# 主流程
# ============================================================


def section_dir(section):
    return os.path.join(CONTENT_DIR, SECTION_DIRS[section])


def clean_section(section):
    path = section_dir(section)
    if os.path.isdir(path):
        shutil.rmtree(path)


def count_md(section):
    total = 0
    for _, _, files in os.walk(section_dir(section)):
        total += sum(1 for name in files if name.endswith(".md"))
    return total


def main():
    global DRY_RUN, MDB_DIR

    parser = argparse.ArgumentParser(description="Z-Blog Access 数据库 -> Hugo 三分区（增量）")
    parser.add_argument(
        "--db",
        choices=["novel", "fiction", "story", "all"],
        default="all",
        help="要导入的分区（默认全部）",
    )
    parser.add_argument(
        "--db-dir",
        default="",
        help="数据库所在目录，相对路径基于仓库根目录（默认 mdb/）",
    )
    parser.add_argument(
        "--sources",
        default="",
        help="数据库配置文件路径，相对路径基于仓库根目录（默认 <db-dir>/sources.json）",
    )
    parser.add_argument("--limit", type=int, default=0, help="每个分区最多导入 N 个书/作者/合集（0 为不限）")
    parser.add_argument("--dry-run", action="store_true", help="只统计差异，不写文件")
    parser.add_argument("--clean", action="store_true", help="导入前清空对应分区的旧内容（全量重建）")
    args = parser.parse_args()

    if args.db_dir:
        MDB_DIR = args.db_dir if os.path.isabs(args.db_dir) else os.path.join(ROOT, args.db_dir)

    DRY_RUN = args.dry_run
    selected = ["novel", "fiction", "story"] if args.db == "all" else [args.db]

    if args.sources:
        sources_path = args.sources if os.path.isabs(args.sources) else os.path.join(ROOT, args.sources)
    else:
        sources_path = os.path.join(MDB_DIR, "sources.json")
    SOURCES.update(load_sources(sources_path, selected))

    if not DRY_RUN and args.clean:
        for section in selected:
            clean_section(section)
        print("[clean] 已清空：" + ", ".join(selected))

    started = time.time()
    print("=" * 66)
    print(f"导入模式：{'全部' if args.db == 'all' else args.db} | dry-run={DRY_RUN} | limit={args.limit}")
    print("=" * 66)

    totals = {}
    section_counts = {}
    story_authors = Counter()
    renumbered = []
    book_slugs = {}

    if "novel" in selected:
        counts = Counts()
        stats, authors, renumbered, book_slugs = import_novels(args.limit, counts)
        totals["novel"] = stats
        section_counts["novel"] = counts

    if "fiction" in selected:
        counts = Counts()
        stats, authors = import_fiction(args.limit, counts)
        totals["fiction"] = stats
        section_counts["fiction"] = counts
        story_authors.update(authors)

    if "story" in selected:
        counts = Counts()
        stats, authors = import_story(args.limit, counts)
        totals["story"] = stats
        section_counts["story"] = counts
        story_authors.update(authors)
        index_counts = Counts()
        write_tale_author_index(index_counts)
        section_counts["story"].add(index_counts)

    # 短篇库标签对照（只在导入短篇或全部时打印）
    if "fiction" in selected:
        report_tag_differences()

    # ---------- 统计 ----------
    print("\n" + "=" * 66)
    print("导入统计")
    print("=" * 66)
    all_counts = Counts()
    for section, stats in totals.items():
        counts = section_counts[section]
        all_counts.add(counts)
        if section == "novel":
            print(
                f"  长篇小说：{stats['books']} 本书（{stats['books_with_author']} 本有作者），"
                f"{stats['pages']} 个章节页，跳过 {stats['skipped']} 个空条目"
            )
            genre_counts = stats.get("genre_counts") or {}
            if genre_counts:
                parts = [
                    f"{GENRE_LABELS.get(key, key)} {count} 本"
                    for key, count in genre_counts.most_common()
                ]
                print("             题材：" + " / ".join(parts))
        elif section == "fiction":
            uncredited = stats["pages"] - stats["credited"]
            print(
                f"  短篇小说：{stats['authors']} 个作者目录，{stats['pages']} 个篇目页"
                f"（有署名 {stats['credited']} / 无署名 {uncredited}，标签补全 {stats['tag_filled']}），"
                f"跳过 {stats['skipped']} 个公告/空条目"
            )
        else:
            uncredited = stats["pages"] - stats["credited"]
            print(
                f"  短篇故事：{stats['collections']} 个合集，{stats['pages']} 个篇目页"
                f"（有署名 {stats['credited']} / 无署名 {uncredited}），"
                f"跳过 {stats['skipped']} 个公告/空条目"
            )
        print(f"             {counts.line()}")

    print(f"  合计：{all_counts.line()}")

    if not DRY_RUN:
        md_files = sum(count_md(section) for section in selected)
        print(f"  生成的 Markdown 文件：{md_files} 个（含分区/作者/合集 _index.md）")

    if renumbered:
        print("\n  本次被重编号的书（中间插入/删除/顺序变化，已整本重排）：")
        for name, old_count, new_count in renumbered:
            print(f"    - {name}（旧 {old_count} 章 → 新 {new_count} 章）")
    elif "novel" in selected:
        print("\n  本次没有被重编号的书。")

    if book_slugs:
        print("\n  书籍 slug（拼音连写）：")
        for index, title in enumerate(sorted(book_slugs), start=1):
            print(f"    {index:>3}. {title} -> /novel/{book_slugs[title]}/")

    if story_authors:
        total = sum(story_authors.values())
        print(
            f"\n  短篇类作者：有署名 {total} 篇，作者总数 {len(story_authors)} 位（已合并别名与全角/半角写法）"
        )
        print("  按篇数排序前 10：")
        for index, (name, count) in enumerate(story_authors.most_common(10), start=1):
            print(f"    {index:>2}. {name}  {count} 篇")

    print(f"\n耗时：{time.time() - started:.1f} 秒")


if __name__ == "__main__":
    main()
