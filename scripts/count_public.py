# -*- coding: utf-8 -*-
"""
count_public.py —— 统计构建产物 public/ 的文件数与总大小，对照部署上限。

背景：Cloudflare Pages 单次部署上限 20,000 个文件（软目标 18,000，留余量）。
GitHub Pages 限制更宽，但仍按 20,000 管理（更紧的那个说了算）。

用法：
    python scripts/count_public.py              # 默认统计 public/
    python scripts/count_public.py --dir public
    python scripts/count_public.py --soft 18000 # 自定义软目标

退出码：
    0 = 在软目标以内
    2 = 超过软目标（警告）
    1 = 超过 20,000 硬上限（CI 里会失败）
"""

import argparse
import os
import sys

HARD_LIMIT = 20000
DEFAULT_SOFT = 18000


def human(size):
    """把字节数转成便于阅读的大小。"""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


def count(root):
    """返回 (文件总数, 总字节数, 各顶层目录统计)。"""
    total_files = 0
    total_bytes = 0
    buckets = {}

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            total_files += 1
            total_bytes += size

            rel = os.path.relpath(path, root).replace("\\", "/")
            top = rel.split("/", 1)[0] if "/" in rel else "(根目录)"
            if "." in top:  # 根目录里的 index.html、sitemap.xml 等
                top = "(根目录)"
            bucket = buckets.setdefault(top, [0, 0])
            bucket[0] += 1
            bucket[1] += size

    return total_files, total_bytes, buckets


def main():
    parser = argparse.ArgumentParser(description="统计 public 文件数与总大小")
    parser.add_argument("--dir", default="public", help="构建输出目录（默认 public）")
    parser.add_argument("--soft", type=int, default=DEFAULT_SOFT, help="软目标文件数（默认 18000）")
    args = parser.parse_args()

    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        sys.exit(f"找不到目录：{root}（请先运行 hugo 构建）")

    total_files, total_bytes, buckets = count(root)

    print("=" * 46)
    print(f"构建产物目录：{root}")
    print("=" * 46)
    for name in sorted(buckets):
        files, size = buckets[name]
        print(f"  {name:<16} {files:>6} 个文件   {human(size):>10}")

    print("-" * 46)
    print(f"  文件总数        {total_files:>6} 个")
    print(f"  总大小          {human(total_bytes):>10}")
    print(f"  硬上限          {HARD_LIMIT:>6} 个（Cloudflare Pages 单次部署）")
    print(f"  软目标          {args.soft:>6} 个")
    print("-" * 46)

    if total_files > HARD_LIMIT:
        print(f"  ✗ 超出硬上限 {total_files - HARD_LIMIT} 个文件，必须先修结构再部署。")
        sys.exit(1)
    if total_files > args.soft:
        print(f"  ! 超出软目标 {total_files - args.soft} 个文件（未超硬上限，但余量变薄）。")
        print(f"  剩余余量（对 {HARD_LIMIT}）：{HARD_LIMIT - total_files} 个文件")
        sys.exit(2)
    print(f"  ✓ 在软目标以内，剩余余量 {args.soft - total_files} 个文件（对硬上限 {HARD_LIMIT - total_files} 个）。")


if __name__ == "__main__":
    main()
