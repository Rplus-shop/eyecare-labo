#!/usr/bin/env python3
"""
最新記事を読み込み、OpenAI gpt-image-1で画像を生成してimages/に保存するスクリプト

Usage:
    python tools/generate_image.py
"""

import base64
import json
import os
import re
import subprocess
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
Instagram投稿用の横長サムネイル画像（16:9）。日本の整体・アイケア・健康系コラム向けデザイン。
実写は禁止、すべてイラストで統一。生成AI特有の不自然な質感は避ける。

【線質・スタイル】
手描き風の線に強弱をつけ、ペン画のような温かみのある線質で描く。フラットすぎるベタ塗りではなく、\
ハッチングや細かいテクスチャを加えてアナログ感を出す。

【レイアウト・構成】
左エリアに人物イラスト（シーンに合った表情・ポーズ）、右エリアにメインコピーとフロー図を配置。\
背景は薄いパステルグラデーション（例：空色→白）に生活シーンの要素（デスク・窓・観葉植物など）を\
うっすら描き込んで情報密度を上げる。余白を適度に埋め、のっぺりした印象を避ける。

【フロー図（必須）】
①②③の3ステップを矢印（→）でつないだフロー図を必ず含める。\
各ステップは丸囲み数字＋短いラベル（10字以内）で表記し、ステップ間に手描き風の曲線矢印を添える。

【アイコン・装飾】
目・筋肉・矢印・星・ハート・稲妻・吹き出しなど複数の小アイコンを画面各所に散りばめる（6〜10個程度）。\
重要キーワードは丸囲みまたは手描き吹き出しで強調する。

【色使い】
パステルカラー（水色・クリーム・薄緑・ラベンダー）をベースに、\
珊瑚色またはレモンイエローを1〜2色の強調色として使いメリハリをつける。\
文字は濃いネイビーまたはチャコールで可読性を確保する。

【テキスト】
メインコピー：「{title}」（最大フォントサイズで中央〜右寄りに配置）
シーン：{scene}
補足ポイント（フロー図の各ステップに対応）：{points}\
"""


# ── 最新記事の取得 ────────────────────────────────────────


def find_latest_article() -> Path:
    """articlesフォルダから最終更新日時が最新のMarkdownファイルを返す"""
    articles = sorted(ARTICLES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not articles:
        print("[エラー] articles/ フォルダに記事が見つかりません。", file=sys.stderr)
        sys.exit(1)
    return articles[0]


# ── 記事から情報抽出 ──────────────────────────────────────


def extract_article_info(article_text: str) -> dict:
    """Claude CLIを使って記事からタイトル・シーン・ポイントを抽出する"""
    prompt = f"""以下の記事から画像生成に使う情報を抽出してください。

## 記事本文
{article_text}

## 抽出項目
- title: 読者の悩みを表す短いキャッチコピー（15字以内、記事の核心を一言で）
- scene: 記事が想定するシーン・状況（例：夕方のオフィスでパソコン作業中の30代女性）
- points: 施術・改善の3つのポイント（各15字以内、箇条書き3件）

## 出力形式
JSONのみ出力する。説明文・前置き・コードブロック記号（```）は不要。

{{
  "title": "...",
  "scene": "...",
  "points": ["...", "...", "..."]
}}
"""
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"[エラー] Claude実行失敗:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    output = re.sub(r"```[^\n]*\n?", "", result.stdout.strip()).strip()
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if not match:
        print(f"[エラー] JSON取得失敗:\n{output}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"[エラー] JSONパース失敗: {e}", file=sys.stderr)
        sys.exit(1)


# ── 画像生成 ──────────────────────────────────────────────


def build_image_prompt(info: dict) -> str:
    points = info.get("points", [])
    points_str = "・".join(points) if isinstance(points, list) else str(points)
    return IMAGE_BASE_PROMPT.format(
        title=info.get("title", ""),
        scene=info.get("scene", ""),
        points=points_str,
    )


def generate_image(prompt: str) -> bytes:
    """OpenAI gpt-image-1で画像を生成してバイナリで返す"""
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=IMAGE_SIZE,
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

    print("\n[1/4] 最新記事を読み込み中...")
    article_path = find_latest_article()
    article_text = article_path.read_text(encoding="utf-8")
    print(f"  対象記事: {article_path.name}")

    print("\n[2/4] Claude Codeで記事情報を抽出中...")
    info = extract_article_info(article_text)
    print(f"  タイトル : {info.get('title')}")
    print(f"  シーン   : {info.get('scene')}")
    print(f"  ポイント : {info.get('points')}")

    print("\n[3/4] OpenAI gpt-image-1で画像を生成中...")
    image_prompt = build_image_prompt(info)
    image_bytes = generate_image(image_prompt)
    print(f"  生成完了（{len(image_bytes):,} bytes）")

    print("\n[4/4] 画像を保存中...")
    out_path = save_image(article_path, image_bytes)
    print(f"  保存先: {out_path.relative_to(PROJECT_ROOT)}")

    print("\n" + "=" * 40)
    print("  完了")
    print("=" * 40)


if __name__ == "__main__":
    main()
