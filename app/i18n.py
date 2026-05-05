"""Lightweight i18n: dict lookup keyed by English source string.

Why a hand-rolled dict and not Babel/gettext: this is a single-user
self-hosted app. A 200-line `.po`/`.mo` toolchain plus an extraction
job is overkill compared with one Python dict that any contributor
can edit. Every Jinja template uses `{{ "Library" | t }}` — if the
key is missing for the active language, the English source falls
through unchanged so a forgotten key shows up in plain English
rather than as a stack trace.

To add a language:
1. Add a key to ``LANGUAGES`` and a translation map below.
2. Surface it as a radio in ``/settings/ui``.
3. Run the app and click around; any string that wasn't translated
   shows in English — add it to the dict and reload.
"""
from __future__ import annotations

from typing import Final


# Locales that ship with the app. Keep the codes ISO 639-1 / RFC 5646
# so they double as <html lang="..."> values.
LANGUAGES: Final[tuple[tuple[str, str], ...]] = (
    ("en", "English"),
    ("ja", "日本語"),
)

DEFAULT_LANGUAGE: Final[str] = "en"


# ja: Translations for the most-visible UI strings. English is the
# canonical source — any string that lands in a template should be
# wrapped with `| t` and added here when we want it localized.
_JA: Final[dict[str, str]] = {
    # ── Navigation / global chrome ──────────────────────────────────────
    "Dashboard": "ダッシュボード",
    "Review": "復習",
    "Library": "ライブラリ",
    "Authors": "著者",
    "Tags": "タグ",
    "Activity": "アクティビティ",
    "Search": "検索",
    "Settings": "設定",
    "Import": "インポート",
    "API tokens": "APIトークン",
    "Mastered": "習得済み",
    "Favorites": "お気に入り",
    "Discarded": "破棄済み",
    "Recent": "最近",
    "Random": "ランダム",
    "Duplicates": "重複",
    "Ask": "質問",
    "Logout": "ログアウト",
    # ── Dashboard ───────────────────────────────────────────────────────
    "Today's review": "今日の復習",
    "Past 7 days": "過去7日間",
    "Total highlights": "ハイライト合計",
    "Books": "本",
    "Highlights": "ハイライト",
    "Streak": "連続記録",
    "days": "日",
    "day": "日",
    "Start daily review": "今日の復習を始める",
    "Continue review": "復習を続ける",
    "No reviews yet": "まだ復習がありません",
    "Random highlight": "ランダムなハイライト",
    "Echoes": "こだま",
    "From your library": "あなたの本棚から",
    "Current Streak": "現在の連続記録",
    "Longest Streak": "最長記録",
    "in a row": "連続",
    "Personal best": "自己ベスト",
    "Total Books": "総書籍数",
    "Total Highlights": "総ハイライト数",
    "Highlighting Activity": "ハイライト活動",
    "Less": "少ない",
    "More": "多い",
    "Overview of your reading highlights and collection.": "ハイライトと本棚の概要。",
    "Browse Library": "本棚を見る",
    "Start Daily Review": "今日の復習を始める",
    "Import from Readwise": "Readwiseからインポート",
    "Welcome to FreeWise - your personal highlight manager.": "FreeWiseへようこそ — あなただけのハイライトマネージャ。",
    "Search highlights": "ハイライトを検索",
    # ── Review screen ───────────────────────────────────────────────────
    "Daily Review": "今日の復習",
    "of": "/",
    "Done": "完了",
    "Discard": "破棄",
    "Frequency": "頻度",
    "Edit highlight": "ハイライトを編集",
    "Save": "保存",
    "Cancel": "キャンセル",
    "Page": "ページ",
    "Add a note...": "メモを追加…",
    "Review frequency": "復習頻度",
    "Much less": "とても少なく",
    "Less": "少なく",
    "Normal": "普通",
    "More": "多く",
    "Much more": "とても多く",
    # ── Highlight actions ───────────────────────────────────────────────
    "Favorite": "お気に入り",
    "Unfavorite": "お気に入り解除",
    "Master": "習得済みに",
    "Unmaster": "習得済みを解除",
    "Restore": "復元",
    "Permalink": "パーマリンク",
    "Copy as quote": "引用としてコピー",
    "Add tag": "タグを追加",
    "Remove tag": "タグを削除",
    "Filter library by tag": "タグで本棚を絞り込む",
    # ── Library / book detail ───────────────────────────────────────────
    "Most highlighted": "ハイライト数が多い順",
    "Most books": "本の数が多い順",
    "Name A-Z": "名前順",
    "Recent activity": "最近の活動順",
    "Title": "タイトル",
    "Author": "著者",
    "Last activity": "最終活動",
    "back to books": "本一覧に戻る",
    "View book detail": "本の詳細を見る",
    # ── Settings ────────────────────────────────────────────────────────
    "Daily review count": "1日の復習数",
    "Highlight recency": "ハイライト新しさ",
    "Theme": "テーマ",
    "Light": "ライト",
    "Dark": "ダーク",
    "Auto": "自動",
    "Language": "言語",
    "Save settings": "設定を保存",
    "Settings saved successfully!": "設定を保存しました！",
    "Reset library": "ライブラリをリセット",
    "Backup database": "データベースをバックアップ",
    # ── Common bits ─────────────────────────────────────────────────────
    "shortcuts": "ショートカット",
    "Loading…": "読み込み中…",
    "No results": "結果なし",
    "Are you sure?": "本当によろしいですか？",
    "Confirm": "確認",
    "Yes": "はい",
    "No": "いいえ",
    # ── Echoes copy (PR-E) ──────────────────────────────────────────────
    "On this day": "今日のこの日",
    "Long time no see": "久しぶり",
    "Re-read this": "もう一度読みたい",
    "Read this book again": "この本をもう一度読む",
    "I revisited this": "読み返した",
    "1 year ago": "1年前",
    "{n} years ago": "{n}年前",
    "{n} days since last review": "前回の復習から{n}日",
}


_TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "ja": _JA,
}


def t(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """Translate `key` to `lang`, falling back to the source string.

    The fallback is intentional: English text passes through unchanged
    so a missing translation never crashes a render. Curly-brace
    placeholders (e.g. ``"{n} years ago"``) are left as-is — Jinja
    templates do their own formatting via the standard `format` filter.
    """
    if lang == DEFAULT_LANGUAGE or not key:
        return key
    table = _TRANSLATIONS.get(lang)
    if not table:
        return key
    return table.get(key, key)
