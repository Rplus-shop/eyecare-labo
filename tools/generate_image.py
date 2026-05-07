#!/usr/bin/env python3
"""
最新記事を読み込み、OpenAI gpt-image-1で画像を生成してimages/に保存するスクリプト

Usage:
    python tools/generate_image.py
"""

import base64
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    print("[エラー] OPENAI_API_KEY が未設定です。.env ファイルを確認してください。", file=sys.stderr)
    sys.exit(1)

try:
    from openai import OpenAI
except ImportError:
    print("[エラー] openai パッケージが未インストールです。pip install openai を実行してください。", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
ARTICLES_DIR = PROJECT_ROOT / "articles"
IMAGES_DIR = PROJECT_ROOT / "images"

# gpt-image-1 がサポートする横長サイズ（1792x1024 は DALL-E 3 専用のため 1536x1024 を使用）
IMAGE_SIZE = "1536x1024"

IMAGE_BASE_PROMPT = """\
以下の記事本文を読んで、内容に合ったInstagram投稿用の横長サムネイル画像を生成してください。

【記事本文】
{article_text}

【画像デザイン指示】
・横長16:9
・手描き風イラスト、線に強弱あり、ペン画のような温かみのある線質
・実写禁止、すべてイラスト
・白背景ベース＋パステルカラー、珊瑚色orレモンイエローで1〜2色強調
・記事のメインコピーを大きく配置
・左側に人物イラスト（記事が想定するシーン・人物像に合わせる）
・右側に①②③の矢印付きフロー図（記事の3つのポイントを対応させる）
・目・星・ハート・稲妻など小アイコンを6〜10個散りばめる
・重要キーワードは丸囲みや吹き出しで強調
・背景に薄いパステルグラデーションと生活シーンの要素（デスク・窓・観葉植物など）
・40〜50代女性に向けた落ち着いた雰囲気
・広告感を弱める\
"""


# ── 最新記事の取得 ────────────────────────────────────────


def find_latest_article() -> Path:
    """articlesフォルダから最終更新日時が最新のMarkdownファイルを返す"""
    articles = sorted(ARTICLES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not articles:
        print("[エラー] articles/ フォルダに記事が見つかりません。", file=sys.stderr)
        sys.exit(1)
    return articles[0]


# ── 画像生成 ──────────────────────────────────────────────


def trim_article_text(text: str) -> str:
    """冒頭定型文と末尾免責文を除いた本文のみを返す"""
    lines = text.splitlines()

    # 冒頭定型文（「こんにちは」で始まる行）をスキップ
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("こんにちは"):
            start = i + 1
            break

    # 末尾免責文（「⚠️ご注意」または区切り線「---」）以降をカット
    end = len(lines)
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("⚠️") or stripped == "---":
            end = i
            break

    return "\n".join(lines[start:end]).strip()


def build_image_prompt(article_text: str) -> str:
    body = trim_article_text(article_text)
    return IMAGE_BASE_PROMPT.format(article_text=body)


def generate_image(prompt: str) -> bytes:
    """OpenAI gpt-image-1で画像を生成してバイナリで返す"""
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=IMAGE_SIZE,
        quality="high",
        n=1,
    )
    image_data = response.data[0]

    # gpt-image-1 は b64_json を返す
    if getattr(image_data, "b64_json", None):
        return base64.b64decode(image_data.b64_json)

    # フォールバック：URL が返された場合はダウンロード
    if getattr(image_data, "url", None):
        import urllib.request
        with urllib.request.urlopen(image_data.url) as resp:
            return resp.read()

    print("[エラー] 画像データが取得できませんでした。", file=sys.stderr)
    sys.exit(1)


# ── 保存 ──────────────────────────────────────────────────


def save_image(article_path: Path, image_bytes: bytes) -> Path:
    """images/YYYYMM_タイトル.png に保存してパスを返す"""
    IMAGES_DIR.mkdir(exist_ok=True)
    out_path = IMAGES_DIR / f"{article_path.stem}.png"
    out_path.write_bytes(image_bytes)
    return out_path


# ── メイン ────────────────────────────────────────────────


def main():
    print("=" * 40)
    print("  画像生成フロー開始")
    print("=" * 40)

    print("\n[1/3] 最新記事を読み込み中...")
    article_path = find_latest_article()
    article_text = article_path.read_text(encoding="utf-8")
    trimmed = trim_article_text(article_text)
    print(f"  対象記事: {article_path.name}")
    print(f"  本文文字数（定型文・免責文除外後）: {len(trimmed)} 字")

    print("\n[2/3] OpenAI gpt-image-1で画像を生成中...")
    image_prompt = build_image_prompt(article_text)
    image_bytes = generate_image(image_prompt)
    print(f"  生成完了（{len(image_bytes):,} bytes）")

    print("\n[3/3] 画像を保存中...")
    out_path = save_image(article_path, image_bytes)
    print(f"  保存先: {out_path.relative_to(PROJECT_ROOT)}")

    print("\n" + "=" * 40)
    print("  完了")
    print("=" * 40)


if __name__ == "__main__":
    main()
