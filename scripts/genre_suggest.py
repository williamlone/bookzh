# -*- coding: utf-8 -*-
"""
genre_suggest.py —— 按书名 / 作者 / 简介给长篇小说做题材自动归类，产出建议表

用途：
    1. 扫描 content/novel/<slug>/_index.md，读 title / author / summary；
    2. 用关键词规则打分，命中明确题材则归入该题材；
    3. 没把握的统一归入 jingdian（经典小说），并标记「待人工确认」；
    4. 打印建议表，同时写出 data/novel_genre_map.yaml 供人工修正。

用法：
    python scripts/genre_suggest.py            # 打印建议表；映射表已存在时不会覆盖
    python scripts/genre_suggest.py --write    # 重新生成 data/novel_genre_map.yaml（会丢人工修改）
    python scripts/genre_suggest.py --print    # 只打印，不写文件

注意：data/novel_genre_map.yaml 是唯一权威映射，导入脚本按它给书籍 _index.md 写 genre。
人工改完这张表后直接重跑导入即可，不需要再跑本脚本。
"""

import argparse
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOVEL_DIR = os.path.join(ROOT, "content", "novel")
OUT_FILE = os.path.join(ROOT, "data", "novel_genre_map.yaml")

GENRES = ["jingdian", "aiqing", "maoxian", "xuanyi", "qihuan", "lishi"]

GENRE_NAMES = {
    "jingdian": "经典小说",
    "aiqing": "爱情小说",
    "maoxian": "冒险小说",
    "xuanyi": "悬疑小说",
    "qihuan": "奇幻小说",
    "lishi": "历史小说",
}

# 关键词：命中越多分越高。标题里的命中额外加权。
KEYWORDS = {
    "aiqing": [
        "爱情", "恋爱", "情人", "婚姻", "婚外", "恋人", "初恋", "失恋",
        "痴情", "妻子", "丈夫", "求婚", "结婚", "离婚", "风流", "艳",
    ],
    "maoxian": [
        "冒险", "历险", "探险", "漂流", "航海", "海盗", "海岛", "荒岛",
        "寻宝", "远征", "骑士", "侠", "逃", "旅途", "流浪", "骑兵",
    ],
    "xuanyi": [
        "侦探", "谋杀", "凶杀", "悬疑", "案件", "犯罪", "谜", "尸",
        "审讯", "审判", "间谍", "追踪", "凶", "血案", "罪案", "密室",
    ],
    "qihuan": [
        "魔", "奇幻", "精灵", "妖精", "神话", "幽灵", "鬼", "吸血鬼",
        "巫", "法术", "童话", "寓言", "幻境", "异世界", "神",
    ],
    "lishi": [
        "历史", "战争", "王朝", "帝国", "革命", "拿破仑", "大革命",
        "二战", "第一次世界大战", "南北战争", "王朝", "起义", "殖民",
        "中世纪", "古罗马", "封建",
    ],
}


def read_front_matter(path):
    """读取脚本/人工写的 _index.md，拿到 title / author / summary。"""
    with open(path, encoding="utf-8") as handle:
        raw = handle.read().replace("\r\n", "\n")
    data = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            block = parts[1]
            try:
                parsed = yaml.safe_load(block)
                if isinstance(parsed, dict):
                    return parsed
            except yaml.YAMLError:
                pass
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip('"')
                data[key.strip()] = value
    return data


def score(genre, title, author, summary):
    """返回 (得分, 命中的关键词)。标题命中算 3 分，简介/作者命中算 1 分。"""
    hits = []
    total = 0
    for word in KEYWORDS[genre]:
        if word in title:
            total += 3
            hits.append(word)
        elif word in summary:
            total += 1
            hits.append(word)
    return total, hits


def classify(title, author, summary):
    """返回 (genre, 是否待人工确认, 依据关键词)。"""
    scores = {}
    for genre in ("aiqing", "maoxian", "xuanyi", "qihuan", "lishi"):
        scores[genre] = score(genre, title, author, summary)

    ranked = sorted(scores.items(), key=lambda item: item[1][0], reverse=True)
    best_genre, (best_score, best_hits) = ranked[0]
    second_score = ranked[1][1][0]

    # 有明确命中且明显领先，才算确定；否则归 jingdian 并标记待确认
    if best_score >= 3 and best_score >= second_score + 3:
        return best_genre, False, best_hits

    # 没有明确命中的书，本来就属于“经典小说”的常见情况
    if best_score == 0:
        return "jingdian", False, []

    return "jingdian", True, best_hits


def main():
    parser = argparse.ArgumentParser(description="长篇小说题材归类建议")
    parser.add_argument("--print", action="store_true", dest="only_print", help="只打印不写文件")
    parser.add_argument("--write", action="store_true", help="覆盖 data/novel_genre_map.yaml（会丢掉人工修改）")
    args = parser.parse_args()

    if not os.path.isdir(NOVEL_DIR):
        sys.exit("找不到 content/novel/，请先运行导入脚本")

    # 已有的映射表是人工定稿的权威数据：命中即沿用，不再重新猜测、也不标待确认
    existing = {}
    if os.path.isfile(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as handle:
            for row in yaml.safe_load(handle) or []:
                if row.get("title") and row.get("genre"):
                    existing[str(row["title"]).strip()] = (
                        str(row["genre"]).strip(),
                        bool(row.get("pending")),
                    )

    rows = []
    for name in sorted(os.listdir(NOVEL_DIR)):
        if name == "genre":  # 题材目录不是书
            continue
        index_path = os.path.join(NOVEL_DIR, name, "_index.md")
        if not os.path.isfile(index_path):
            continue
        fm = read_front_matter(index_path)
        title = str(fm.get("title") or "").strip()
        if not title:
            continue
        author = str(fm.get("author") or "").strip()
        summary = str(fm.get("summary") or "")
        if title in existing:
            genre, pending = existing[title]
            hits = []
        else:
            genre, pending, hits = classify(title, author, summary)
        rows.append(
            {
                "title": title,
                "slug": name,
                "author": author,
                "genre": genre,
                "pending": pending,
                "hits": hits,
            }
        )

    # 打印建议表
    print("=" * 78)
    print(f"题材归类建议：共 {len(rows)} 本")
    print("=" * 78)
    for genre in GENRES:
        group = [row for row in rows if row["genre"] == genre]
        print(f"\n【{GENRE_NAMES[genre]}】{len(group)} 本")
        for row in group:
            mark = "  待人工确认" if row["pending"] else ""
            evidence = "、".join(row["hits"][:4])
            print(f"  {row['title']:<22} {row['author']:<20} {evidence}{mark}")

    pending_rows = [row for row in rows if row["pending"]]
    print(f"\n待人工确认：{len(pending_rows)} 本")
    for row in pending_rows:
        print(f"  {row['title']}（{row['author'] or '无作者'}）")

    if args.only_print:
        return

    # 映射表是人工维护的权威数据，只有显式 --write 才覆盖
    if os.path.exists(OUT_FILE) and not args.write:
        print(f"\n{os.path.relpath(OUT_FILE, ROOT)} 已存在，未覆盖；如需重新生成请加 --write")
        return

    # 写映射表（人工修正的入口）
    payload = []
    for genre in GENRES:
        for row in rows:
            if row["genre"] == genre:
                item = {"title": row["title"], "genre": genre}
                if row["pending"]:
                    item["pending"] = True
                payload.append(item)

    with open(OUT_FILE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("# 长篇小说题材映射：一本书恰好一个题材\n")
        handle.write("# genre 取值：" + " / ".join(GENRES) + "\n")
        handle.write("# pending: true 表示自动归类没把握、需要人工确认（不影响导入）\n")
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
    print(f"\n已写出 {os.path.relpath(OUT_FILE, ROOT)}")


if __name__ == "__main__":
    main()
