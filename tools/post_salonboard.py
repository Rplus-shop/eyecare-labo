#!/usr/bin/env python3
"""
ホットペッパービューティー（サロンボードのブログ）に記事を投稿する

公開APIが無いため、Playwrightでサロンボードの画面を操作する。

入力欄の位置（SELECTORS）と上限は、2026-10-09 に実際の画面で確かめたもの。
画面が変わって欄が見つからなくなったら、写真を残して止まる。

出し方は、岸川様が手で出してきた形（2026年9〜10月のブログ一覧）に合わせる。
- 予約投稿で、水曜と土曜の朝9時。すでに予約が入っている日は使わず、次の空いている日にする
- カテゴリは「サロンのNEWS」、投稿者は「Ren」
- クーポンを1つ添える。子ども向けの記事は【お悩み相談】、それ以外は【先着5名様限定】視力改善

画像認証（CAPTCHA）が出たら、自動で越えずに止める。

必要な環境変数（GitHub Secrets）:
    SALONBOARD_LOGIN_ID / SALONBOARD_PASSWORD
    SALONBOARD_STAFF     任意。投稿者（既定：Ren）
    SALONBOARD_CATEGORY  任意。カテゴリ（既定：サロンのNEWS）
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from article_text import Article

LOGIN_URL = "https://salonboard.com/login/"
BLOG_NEW_URL = "https://salonboard.com/KLP/blog/blog/"
BLOG_LIST_URL = "https://salonboard.com/KLP/blog/blogList/"
JST = timezone(timedelta(hours=9))
SHOT_DIR = Path(__file__).parent.parent / "screenshots"

# 2026-10-09 アイケアLaBo四ツ谷店のサロンボードで、多々良がログインした画面を読んで埋めた。
# 確認画面（/KLP/blog/blog/confirm）まで進めたが、登録のボタンは押していない。
SELECTORS: dict[str, str | None] = {
    "login_id": "input[name=userId]",
    "login_password": "input[name=password]",
    "login_submit": "a.common-CNCcommon__primaryBtn",  # 「ログイン」のリンク
    "staff": "#staffId",  # 投稿者。いまは「Ren」だけ
    "category": "#blogCategoryCd",  # プライベート／サロンのNEWS／おすすめメニュー／おすすめデザイン／ビューティー
    "title": "#blogTitle",
    "body_textarea": "blogContents",  # nicEdit の元の textarea の id。本文は nicEditors 経由で入れる
    "image_open": "#upload",  # 「画像アップロード」
    "image_input": "#sendFile",
    "image_submit": "input.jscImageUploaderModalSubmitButton",  # モーダルの「登録する」
    "rsv_on": "input[name=rsvTokoFlg][value='1']",  # 予約投稿「設定する」
    "rsv_date": "#rsvTokoDate",  # 表示は「2026年10月14日（水）」。今日から14日先まで
    "rsv_time": "#rsvTokoTime",  # 15分刻み
    "coupon_open": "a.SB_modal_add_coupon_btn",  # 「クーポン選択」
    "coupon_item": "div.couponListBox",  # クーポン1件。押すと選ばれる
    "coupon_set": "a.jsc_SB_modal_setting_btn",  # 「設定する」（選ぶまで押せない）
    "confirm": "#confirm",  # 「確認する」
    "submit": "#reflect",  # 確認画面の「登録・反映する」（試行では押さない）
}

# 画面の注記（全角で数える）
TITLE_MAX = 25
BODY_MAX = 1000
LINES_MAX = 80
IMAGES_MAX = 4
WEEKDAYS = "月火水木金土日"

DEFAULT_STAFF = "Ren"
DEFAULT_CATEGORY = "サロンのNEWS"
POST_WEEKDAYS = (2, 5)  # 水・土
POST_TIME = (9, 0)
RSV_DAYS_AHEAD = 14  # 予約投稿で選べるのは今日から14日先まで

# 先に一致したものを使う。クーポンの名前が変わったら、ここを直す
KIDS_PATTERN = re.compile(r"子ども|子供|こども|お子")
COUPONS_KIDS = ["【お悩み相談】"]
COUPONS_DEFAULT = ["【先着5名様限定】視力改善", "【先着5名様限定】眼精疲労", "【お悩み相談】"]


class SalonBoardError(Exception):
    pass


def _env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SalonBoardError(f"{name} が未設定です")
    return v


def check_limits(article: Article) -> None:
    """サロンボードの上限を超えるものは、入力する前に止める（黙って切らない）"""
    problems = []
    if len(article.title) > TITLE_MAX:
        problems.append(f"タイトル{len(article.title)}字（上限{TITLE_MAX}字）")
    if len(article.body) > BODY_MAX:
        problems.append(f"本文{len(article.body)}字（上限{BODY_MAX}字）")
    lines = article.body.count("\n")
    if lines > LINES_MAX:
        problems.append(f"改行{lines}回（上限{LINES_MAX}回）")
    if problems:
        raise SalonBoardError("サロンボードの上限を超えています: " + "、".join(problems))


def coupon_candidates(article: Article, theme: str = "") -> list[str]:
    """これまでの傾向：子ども向けは【お悩み相談】、それ以外は【先着5名様限定】"""
    if theme == "子どもの視力" or KIDS_PATTERN.search(article.title):
        return COUPONS_KIDS
    return COUPONS_DEFAULT


def next_slot(today: date, taken: set[date]) -> datetime:
    """水・土の朝9時のうち、まだ予約が入っていない一番近い日（明日以降・14日先まで）"""
    for n in range(1, RSV_DAYS_AHEAD + 1):
        d = today + timedelta(days=n)
        if d.weekday() in POST_WEEKDAYS and d not in taken:
            return datetime(d.year, d.month, d.day, *POST_TIME, tzinfo=JST)
    raise SalonBoardError(f"{RSV_DAYS_AHEAD}日先まで、水・土の予約投稿の枠が埋まっています")


def taken_dates(list_text: str) -> set[date]:
    """ブログ一覧の「初回反映日時」から、予約・公開済みの日付を拾う"""
    out = set()
    for y, m, d in re.findall(r"(\d{4})/(\d{2})/(\d{2}) \d{2}:\d{2}", list_text):
        out.add(date(int(y), int(m), int(d)))
    return out


def body_html(text: str) -> str:
    """プレーンテキストを、改行を <br> にしたHTMLにする"""
    import html

    return "<br>".join(html.escape(line) for line in text.split("\n"))


def rsv_label(d) -> str:
    return f"{d.year}年{d.month:02d}月{d.day:02d}日（{WEEKDAYS[d.weekday()]}）"


def select_coupon(page, candidates: list[str]) -> str:
    """クーポン選択を開き、候補の順に名前で探して1つ設定する。どれも無ければ止める"""
    page.click(SELECTORS["coupon_open"])
    page.wait_for_selector(SELECTORS["coupon_item"], state="visible")
    for key in candidates:
        item = page.locator(SELECTORS["coupon_item"], has_text=key).first
        if item.count():
            name = item.inner_text().split("有効期限")[0].strip()
            item.click()
            page.locator(SELECTORS["coupon_set"]).filter(has_text="設定する").first.click()
            return name
    raise SalonBoardError("添えるクーポンが見つかりません（候補: " + "、".join(candidates) + "）")


def post_to_salonboard(article: Article, image_path: Path | None, dry_run: bool, theme: str = "") -> str:
    """投稿して、結果の画面のURLを返す。dry_run では入力して写真を撮り、投稿のボタンは押さない"""
    check_limits(article)

    from playwright.sync_api import sync_playwright  # 使うときだけ読み込む

    SHOT_DIR.mkdir(exist_ok=True)
    stem = article.path.stem
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="ja-JP")
        try:
            page.goto(LOGIN_URL)
            if page.locator("iframe[src*='recaptcha'], .g-recaptcha").count() > 0:
                raise SalonBoardError("ログイン画面に画像認証が出ています。自動では進めません")
            page.fill(SELECTORS["login_id"], _env("SALONBOARD_LOGIN_ID"))
            page.fill(SELECTORS["login_password"], _env("SALONBOARD_PASSWORD"))
            page.click(SELECTORS["login_submit"])
            page.wait_for_load_state("networkidle")

            if "/login" in page.url:
                raise SalonBoardError("ログインできませんでした（IDかパスワードを確認してください）")

            page.goto(BLOG_LIST_URL)
            publish_at = next_slot(datetime.now(JST).date(), taken_dates(page.inner_text("body")))
            print(f"[サロンボード] 予約投稿の日時: {publish_at:%Y-%m-%d %H:%M}")

            page.goto(BLOG_NEW_URL)
            page.select_option(SELECTORS["staff"], label=os.environ.get("SALONBOARD_STAFF") or DEFAULT_STAFF)
            page.select_option(SELECTORS["category"], label=os.environ.get("SALONBOARD_CATEGORY") or DEFAULT_CATEGORY)
            page.fill(SELECTORS["title"], article.title)
            # 本文は nicEdit（リッチテキスト）。画面の欄に直接打たず、エディタのAPIで入れる
            page.evaluate(
                "([id, html]) => nicEditors.findEditor(id).setContent(html)",
                [SELECTORS["body_textarea"], body_html(article.body)],
            )
            if image_path and image_path.exists():
                page.click(SELECTORS["image_open"])
                page.set_input_files(SELECTORS["image_input"], str(image_path))
                page.click(SELECTORS["image_submit"])
                page.wait_for_timeout(3000)
            coupon = select_coupon(page, coupon_candidates(article, theme))
            print(f"[サロンボード] クーポン: {coupon}")
            page.check(SELECTORS["rsv_on"])
            page.select_option(SELECTORS["rsv_date"], label=rsv_label(publish_at))
            page.select_option(SELECTORS["rsv_time"], label=publish_at.strftime("%H:%M"))
            page.click(SELECTORS["confirm"])
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(SHOT_DIR / f"{stem}_confirm.png"), full_page=True)
            if "/confirm" not in page.url:
                # 入力に誤りがあると、確認画面へ進まず入力画面のまま赤字が出る
                raise SalonBoardError(f"確認画面へ進めませんでした。写真: screenshots/{stem}_confirm.png")

            if dry_run:
                print(f"[サロンボード・試行] 確認画面で止めました。写真: screenshots/{stem}_confirm.png")
                return "dry-run"

            page.click(SELECTORS["submit"])
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(SHOT_DIR / f"{stem}_done.png"), full_page=True)
            return page.url
        except SalonBoardError:
            raise
        except Exception as e:  # 画面が変わった・時間切れなど
            page.screenshot(path=str(SHOT_DIR / f"{stem}_error.png"), full_page=True)
            raise SalonBoardError(f"サロンボードの操作で止まりました（{type(e).__name__}）") from e
        finally:
            browser.close()
