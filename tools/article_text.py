#!/usr/bin/env python3
"""
articles/ のMarkdown記事を、投稿先に貼れるプレーンテキストに直す

GBP・サロンボードのブログはどちらもMarkdownを解釈しない。
見出し記号（##）や太字（**）がそのまま文字として出てしまうため、投稿の前に外す。

記事ファイルの形（generate_article.py が書くもの）:
    # タイトル
    **投稿月：…／ターゲット：…**
    ---
    こんにちは！…（冒頭定型文）
    ## 見出し
    本文…
    ⚠️ご注意
    当店は医療機関ではありません。…（末尾免責文）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GREETING_PREFIX = "こんにちは"


@dataclass
class Article:
    title: str
    body: str  # 冒頭定型文〜末尾免責文。Markdown記号を外したもの
    path: Path


def _strip_inline(line: str) -> str:
    line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
    line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)
    return line


def to_plain(markdown: str) -> str:
    """Markdownの記号を外す。段落の区切り（空行）は残す"""
    out = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if re.fullmatch(r"-{3,}", line.strip()):
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            # 見出しは【】で囲んで1行にする。前後を空ける
            if out and out[-1] != "":
                out.append("")
            out.append(f"【{_strip_inline(m.group(1)).strip()}】")
            continue
        out.append(_strip_inline(line))
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_article(path: Path) -> Article:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    title = ""
    for line in lines:
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            title = m.group(1).strip()
            break
    if not title:
        title = path.stem.split("_", 1)[-1]

    # 冒頭定型文より前（タイトル・投稿月の行）は投稿しない
    start = next((i for i, l in enumerate(lines) if l.startswith(GREETING_PREFIX)), None)
    if start is None:
        raise ValueError(f"冒頭定型文（{GREETING_PREFIX}…）が見つかりません: {path.name}")
    body = to_plain("\n".join(lines[start:]))
    return Article(title=title, body=body, path=path)
