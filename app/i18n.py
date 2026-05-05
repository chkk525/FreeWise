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
    # ── Library / book detail ───────────────────────────────────────────
    "Filter": "絞り込み",
    "Clear filters": "絞り込みをクリア",
    "All authors": "すべての著者",
    "All tags": "すべてのタグ",
    "Filtering by query": "検索中",
    "Filtering by author": "著者で絞り込み中",
    "Filtering by tag": "タグで絞り込み中",
    "books": "冊",
    "highlights": "件",
    "highlight": "件",
    "Showing": "表示中",
    "Insights": "統計",
    "Avg length": "平均文字数",
    "chars": "文字",
    "First highlighted": "最初のハイライト",
    "Last highlighted": "最後のハイライト",
    "Last reviewed": "最後の復習",
    "Total reviews": "復習回数",
    "Review progress": "復習の進捗",
    "Continue reviewing": "このまま復習を続ける",
    "All highlights reviewed": "この本のハイライトを全て復習しました",
    "No highlights yet": "まだハイライトがありません",
    "Import some highlights": "ハイライトをインポートする",
    "View on book": "本のページで開く",
    "back to library": "本棚に戻る",
    # ── Review screen ───────────────────────────────────────────────────
    "Today's review queue is empty": "今日の復習キューは空です",
    "Come back tomorrow": "また明日来てください",
    "Skip to review": "復習へ移動",
    "Star (toggle favorite)": "お気に入りを切り替え",
    "Toggle favorite": "お気に入りを切り替え",
    "Edit highlight (e or Enter)": "ハイライトを編集 (e or Enter)",
    "Discard (d)": "破棄 (d)",
    "Done (j or Space)": "完了 (j or Space)",
    "Done — next": "完了 — 次へ",
    "Mark this highlight reviewed and continue": "このハイライトを完了として次に進む",
    # ── Highlight row tooltips + toasts ─────────────────────────────────
    "Open permalink (shareable URL for this highlight)": "パーマリンクを開く（共有可能URL）",
    "Open permalink": "パーマリンクを開く",
    "Copy as quote (text + author/title)": "引用としてコピー（本文＋著者/タイトル）",
    "Quote copied": "引用をコピーしました",
    "Copy blocked — check clipboard permissions": "コピーがブロックされました — 権限を確認してください",
    "Mark mastered (excluded from review)": "習得済みに（復習対象外）",
    "Unmark mastered (return to review queue)": "習得済みを解除（復習キューに戻す）",
    "Mastered — excluded from review": "習得済み — 復習対象外",
    "Unmastered — back in review": "習得済み解除 — 復習対象に戻りました",
    "Restore highlight": "ハイライトを復元",
    "Discard highlight": "ハイライトを破棄",
    "Restored": "復元しました",
    "Tag added": "タグを追加しました",
    "Tag removed": "タグを削除しました",
    "Type a tag name first": "先にタグ名を入力してください",
    "Date unknown": "日付不明",
    "See all highlights tagged": "このタグのすべてのハイライトを見る",
    "Added to “read again”": "「もう一度読みたい」に追加",
    "Removed from “read again”": "「もう一度読みたい」から削除",

    # ── Edit highlight form ─────────────────────────────────────────────
    "Editing Highlight": "ハイライトを編集中",
    # ── Settings labels + descriptions ──────────────────────────────────
    "Customize FreeWise to match your reading habits.": "あなたの読書スタイルに合わせて FreeWise をカスタマイズ。",
    "Number of highlights to review per day": "1日に復習するハイライトの数",
    "How many highlights to surface in your daily review (1-15).": "毎日の復習で取り上げるハイライト数 (1〜15)。",
    "Recency weighting": "新しさの重み",
    "0 = prefer older highlights · 5 = neutral · 10 = prefer newer highlights": "0 = 古いものを優先 ・ 5 = 中立 ・ 10 = 新しいものを優先",
    "Choose your preferred visual theme": "見た目のテーマを選択",
    "UI language. Untranslated strings fall back to English.": "UIの言語。未訳文字列は英語にフォールバックします。",
    "Backup": "バックアップ",
    "Download a SQLite snapshot of your library.": "ライブラリの SQLite スナップショットをダウンロード。",
    "Export": "エクスポート",
    "CSV (Readwise-compatible)": "CSV (Readwise互換)",
    "Markdown (Obsidian / Logseq vault)": "Markdown (Obsidian / Logseq ボールト)",
    "Atomic notes (one .md per highlight)": "原子メモ (ハイライト毎に1ファイル)",
    "Notion-flavored Markdown": "Notion風 Markdown",
    "Danger zone": "危険ゾーン",
    "Permanently delete all data and reset to defaults.": "すべてのデータを完全に削除して初期化。",
    "I understand, reset everything": "理解した上でリセット",
    # ── Search ──────────────────────────────────────────────────────────
    "Search results": "検索結果",
    "No results found for": "見つかりませんでした:",
    "Try a different keyword": "別のキーワードを試してください",
    "result": "件",
    "results": "件",
    # ── Empty states ────────────────────────────────────────────────────
    "Nothing here yet.": "まだ何もありません。",
    "Import your first highlight": "最初のハイライトをインポート",
    # ── Common buttons ──────────────────────────────────────────────────
    "Close": "閉じる",
    "Continue": "続ける",
    "Back": "戻る",
    "Next": "次へ",
    "Previous": "前へ",
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
    "Normal": "普通",
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

    # ── Review screen extras (PR-F) ─────────────────────────────────────
    "Daily Review - FreeWise": "今日の復習 - FreeWise",
    "Library - FreeWise": "ライブラリ - FreeWise",
    "Settings - FreeWise": "設定 - FreeWise",
    "Import some highlights from Readwise, Kindle, Meebook, or a custom CSV to start your review streak.": "Readwise・Kindle・Meebook・カスタム CSV からハイライトをインポートして復習の連続記録を始めましょう。",
    "Import highlights from Readwise, Kindle, Meebook, or a custom CSV to get started!": "Readwise・Kindle・Meebook・カスタム CSV からハイライトをインポートして始めましょう！",
    "Import highlights": "ハイライトをインポート",
    "Import Highlights": "ハイライトをインポート",
    "All Done!": "完了！",
    "No highlights available for review today. Great job staying on top of things!": "今日復習できるハイライトはありません。お疲れさまです！",
    "Back to Dashboard": "ダッシュボードに戻る",
    "Favorite (f)": "お気に入り (f)",
    "Unfavorite (f)": "お気に入り解除 (f)",
    "Favorite this highlight": "このハイライトをお気に入りに追加",
    "Unfavorite this highlight": "このハイライトのお気に入りを解除",
    "Discard this highlight (keyboard: d)": "このハイライトを破棄 (キー: d)",
    "Mark this highlight reviewed and continue (keyboard: j or Space)": "このハイライトを完了として次へ (キー: j または スペース)",
    "Change review frequency": "復習頻度を変更",
    "Show keyboard shortcuts": "ショートカット一覧を表示",
    # ── Library screen ──────────────────────────────────────────────────
    "Browse your collection of": "ライブラリ全体",
    "book.": "冊。",
    "books.": "冊。",
    "view authors": "著者一覧を見る",
    "Search books": "本を検索",
    "Search book title or author…": "タイトル・著者で検索…",
    "Clear search": "検索をクリア",
    "Clear author filter": "著者の絞り込みを解除",
    "active highlights": "アクティブなハイライト",
    "favorited": "お気に入り",
    "mastered": "習得済み",
    "discarded": "破棄済み",
    "last": "最終",
    "Show only books by": "この著者のみ表示",
    "Your library is empty": "ライブラリは空です",
    "Last Highlighted At": "最終ハイライト日時",
    # ── Settings screen ─────────────────────────────────────────────────
    "Daily Review Count": "1日の復習数",
    "Number of highlights to show in your daily review session": "毎日の復習で取り上げるハイライト数",
    "Highlight Recency": "ハイライトの新しさ",
    "Bias daily review toward older or more recent highlights": "古い／新しいハイライトへの偏りを調整",
    "Older": "古い",
    "Neutral": "中立",
    "Newer": "新しい",
    "(System)": "(システム)",
    "API & Integrations": "API と外部連携",
    "API Tokens": "API トークン",
    "Create + revoke bearer tokens for the Readwise-compatible": "Readwise 互換の",
    "endpoints. Use these to wire up the": "エンドポイント用のトークンを発行・取り消し。",
    "Chrome extension or any third-party highlight client.": "Chrome 拡張やサードパーティのハイライトクライアントで使えます。",
    "Manage API tokens": "API トークンを管理",
    "Export Data": "データのエクスポート",
    "Download CSV Export": "CSV をダウンロード",
    "Download all your highlights and metadata as a CSV file. The export includes highlight text, notes, ": "すべてのハイライトとメタデータを CSV としてダウンロード。本文・メモ・",
    "book information, tags, favorite/discard status, and timestamps.": "書籍情報・タグ・お気に入り／破棄状態・タイムスタンプを含みます。",
    "Exporting your highlights...": "ハイライトをエクスポート中…",
    "Please wait while we generate your CSV file": "CSV ファイルの生成中です。少々お待ちください",
    "Preparing export...": "エクスポートの準備中…",
    "Preparing your CSV…": "CSV を準備中…",
    "Download started — check your browser downloads.": "ダウンロードを開始しました — ブラウザのダウンロード一覧を確認してください。",
    "Download Markdown ZIP": "Markdown ZIP をダウンロード",
    "Download Atomic Notes ZIP": "原子メモ ZIP をダウンロード",
    "Download Notion ZIP": "Notion ZIP をダウンロード",
    "Database Backup": "データベースのバックアップ",
    "Download a consistent SQLite snapshot of the entire FreeWise database — useful before risky operations or to keep an off-site backup.": "FreeWise データベース全体の SQLite スナップショットをダウンロード。重要な操作の前や外部バックアップに便利です。",
    "Download .db snapshot": ".db スナップショットをダウンロード",
    "Add highlights before exporting data.": "エクスポートするにはまずハイライトを追加してください。",
    "Danger Zone": "危険ゾーン",
    "Reset Entire Library": "ライブラリ全体をリセット",
    "Permanently erase all highlights, books, tags, and review history. Application settings will also be reset to their defaults.": "すべてのハイライト・本・タグ・復習履歴を完全に削除します。アプリ設定も初期化されます。",
    "This will permanently delete all highlights, books, tags, and review history. There is no going back and no way to recover your data.": "すべてのハイライト・本・タグ・復習履歴を完全に削除します。元には戻せず、データを復元する方法もありません。",
    "Are you absolutely sure?": "本当によろしいですか？",
    "Type": "入力",
    "below to enable the destroy button.": "を入力すると削除ボタンが有効になります。",
    "Type RESET to confirm": "確認のため RESET と入力",
    "Yes, delete everything": "はい、すべて削除",
    # ── Highlight edit form (PR-F) ──────────────────────────────────────
    "Cancel (Esc)": "キャンセル (Esc)",
    "Save (Enter)": "保存 (Enter)",
    "by": "著者:",
    # ── Common labels ───────────────────────────────────────────────────
    "Browse your collection of {n} books.": "ライブラリには {n} 冊あります。",
    "Browse your collection of {n} book.": "ライブラリには {n} 冊あります。",
    # ── Toast verbs (past-tense for confirmation) ──────────────────────
    # NOTE: "Discarded" is already mapped to 破棄済み as a status label;
    # for toast context we accept the same translation rather than
    # overriding it with a verb form.
    "Favorited": "お気に入りに追加しました",
    "Unfavorited": "お気に入りを解除しました",
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
