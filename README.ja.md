# FreeWise

🌐 [English](README.md) · **日本語**

[![テスト: 885 / 50 / 31 通過](https://img.shields.io/badge/tests-966%20passing-brightgreen)](#テスト)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: CC0](https://img.shields.io/badge/license-CC0-green)
![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![PWA](https://img.shields.io/badge/PWA-installable-purple?logo=pwa)
![MCP-ready](https://img.shields.io/badge/MCP-30%20tools-orange)

> **セルフホストのハイライト・ライブラリ — Readwise が *ほぼ* 実現してくれる「自分の読書を所有する」体験を、サブスクもデータ販売もロックインもなしで。**

FreeWise は、Readwise の「毎日のレビュー」体験を FastAPI + SQLite + HTMX で再実装したもの。さらに全文検索・RAG（「自分のライブラリに質問する」）・Kindle スクレイプ・HTML/CLI/MCP の三面展開・任意の Web 選択を保存できる Chrome 拡張までセットになっています。**シングルユーザー、シングルバイナリ、SQLite 1ファイル** — ノートPC、$50 の VPS、自宅 NAS、どこでも動かせる設計です。

このリポジトリは [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise) の [`chkk525`](https://github.com/chkk525) **フォーク** です。upstream は CRUD/インポート/レビューの土台、本フォークは [このフォークで追加されたもの](#このフォークで追加されたもの) に書いてあるすべてを上乗せしています。**PR は本フォーク内で完結 — upstream には絶対に出しません**。

---

## 目次

1. [こんな人に向いている](#こんな人に向いている)
2. [クイックスタート（3コマンド）](#クイックスタート3コマンド)
3. [このフォークで追加されたもの](#このフォークで追加されたもの)
4. [サーフェスツアー](#サーフェスツアー)
   - [Web UI](#web-ui)
   - [REST API（`/api/v2`）](#rest-apiapiv2)
   - [`freewise` CLI](#freewise-cli)
   - [`freewise-mcp` MCP サーバー](#freewise-mcp-mcp-サーバー)
   - [Chrome 拡張](#chrome-拡張)
5. [設定リファレンス](#設定リファレンス)
6. [運用](#運用)
7. [開発](#開発)
8. [トラブルシューティング](#トラブルシューティング)
9. [ロードマップ](#ロードマップ)
10. [コントリビューション](#コントリビューション)
11. [ライセンス](#ライセンス)

---

## こんな人に向いている

| あなたが… | …そして FreeWise が提供するもの |
|---|---|
| 本・記事・論文の重い読者 | ハイライトが行方不明にならない、検索可能・タグ付け可能・**永続的**な保管庫。 |
| Readwise の月8ドルに疲れた人 | 同じ毎日レビューループ、FTS5 全文検索、OG 画像カード、メールダイジェスト — Docker 1コンテナでセルフホスト。 |
| Claude Code / LLM いじり好き | アシスタントが直接ライブラリを読み書き・推論できる **30 ツールの MCP サーバー**。 |
| プライバシー重視の読者 | 埋め込み・検索・LLM RAG はすべて Ollama でローカル実行。第三者にハイライトは渡しません。 |
| Web ベースの Kindle エクスポートが嫌いな Kindle 派 | Chrome 拡張 + Playwright スクレイパ + 手動インポート — 3経路全部冪等。 |

**向いていない** ケース：リアルタイムマルチデバイス同期、マルチユーザー権限、ホスト型 SaaS UI、無料枠付きモバイルアプリが必要な場合。FreeWise は意図的にシングルユーザー・シングルテナントです。

---

## クイックスタート（3コマンド）

> **要件**：[Docker](https://docs.docker.com/get-docker/) と [Docker Compose](https://docs.docker.com/compose/install/)。Linux・macOS・QNAP Container Station で動作確認済み。

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise
docker compose up -d --build
```

→ ブラウザで **http://localhost:8063** を開くと空のダッシュボードが表示されます。

**ゴール**：次の 5 分以内に以下を達成できる状態を目指します。

1. ✅ 既存のハイライトをインポート（Readwise CSV、Kindle JSON、または Chrome 拡張でリアルタイム）。
2. ✅ そのうち 1 つを日本語 / 英語 / 混在文字列で検索できる。
3. ✅ ダッシュボードのデイリーレビューカードで 1 つお気に入り登録。

うまくいかない場合は [トラブルシューティング](#トラブルシューティング) へ。

### オプション：AI 機能を有効化

```bash
docker compose exec ollama ollama pull nomic-embed-text  # 埋め込み
docker compose exec ollama ollama pull llama3.2          # チャット / RAG
```

その後 `freewise embed-backfill` を 1 回実行してライブラリ全体をベクトル化。これで `/highlights/ui/ask` と「関連ハイライト」サーフェスが点灯します。

### オプション：メールダイジェストを有効化

`.env` に SMTP 認証情報を追加：

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<Gmail App Password>
SMTP_FROM=FreeWise <you@gmail.com>
SMTP_TO=you@gmail.com
```

dry-run プレビュー：`freewise digest`。スケジュール：

```cron
0 8 * * *  freewise digest --send
```

---

## このフォークで追加されたもの

ユーザーがやりたいこと別にグルーピング。upstream `wardeiling/FreeWise` は CRUD の土台。以下は本フォーク独自です。

### 1. 過去に読んだものを見つける

- **FTS5 トライグラム検索** — 英語・日本語・中文・混在表記すべてに対応、MeCab 不要。初回起動時に自動バックフィル。FTS5 が無い環境では LIKE フォールバック。
- **`<mark>` ハイライト付きスニペット** — `/highlights/ui/search` と `/api/v2/highlights/search` の両方。sentinel-then-escape の XSS-safe レンダリング。
- **複合フィルタ検索** — `?q=` + `?tag=` + `?favorited_only=true` + `?has_note=true` を組み合わせ。クエリなしでフィルタだけのブラウズも可。
- **著者 / タグ / 本のピボット** — 各ハイライトから著者インデックス・タグ詳細・本詳細ページへリンク。

### 2. 毎日のレビュー習慣を作る

- **デイリーレビューカード** — 重み付きランダム抽出（新しい・低マスタリーを優先）。
- **ストリークカウンター** + ダッシュボードの 30 日 GitHub 風ヒートマップ。
- **デイリーダイジェストページ** `/digest/today` — 1 日中同じピック、深夜にローテート。
- **アクティビティタイムライン** `/highlights/ui/activity` — favorite / discard / master 等のアクション履歴を新しい順に、日付グルーピング、動詞でフィルタ可。
- **冷えた本ウィジェット** — ダッシュボードに「最も触っていない 5 冊」を表示。長尾のインポートが腐らないように。

### 3. ライブラリに質問する（RAG）

- **埋め込み基盤** — ハイライト単位の `nomic-embed-text` ベクトル、コサイン検索、numpy のチャンク行列積（25k × 768 を約 50ms で処理）。
- **`/highlights/ui/ask`** — ライブラリ全体に対する質問応答、根拠ハイライトへの引用リンク付き。
- **本単位の要約** — 当該本のハイライトだけを使った LLM 要約。本詳細ページから実行可能。
- **タグ提案** — 埋め込み近傍ベース、HTMX で承認/却下。
- **意味的近重複検出** + UI ページでワンクリック discard。
- **関連ハイライト** `/highlights/ui/h/{id}/related` — Top-K コサイン類似。

### 4. インポートと整理

- **複数フォーマット対応インポート** — Readwise CSV、Kindle JSON（Amazon エクスポート形式）、Meebook HTML、カスタム CSV。CLI は拡張子で自動判定。
- **Kindle スクレイパ** — `read.amazon.com` を Playwright ヘッドレスでスクレイプ、ASIN 重複排除、Webhook 通知、毎日 cron 実行。ダッシュボードの **「今すぐスクレイプ」ボタン** でオンデマンド起動も（[`freewise-qnap-kindle`](https://github.com/chkk525/freewise-qnap-kindle) 姉妹リポジトリに本体）。
- **Chrome 拡張** — 任意の Web 選択を右クリック → `/api/v2/highlights/` に保存。MV3、永続ストレージ、最近の保存履歴付き。詳細は [Chrome 拡張](#chrome-拡張)。
- **タグの rename / merge / オートコンプリート** — 一括操作 + ネイティブ `<datalist>` サジェスト。
- **著者の全本一括 rename** — 表記揺れ・全角空白などのタイポを 1 ショットで統一。
- **ノートへの append** — アトミックな concat（8191 字キャップ）。
- **ダッシュボードのクイックキャプチャ textarea**。
- **完全一致 + 意味的重複ファインダー** — 一括クリーンナップ UI 付き。

### 5. ハイライトをシェアする

- **Open Graph + Twitter Card メタ** — 各ハイライト permalink にリッチプレビュー（Slack、iMessage、X すべて対応）。
- **引用カード OG 画像** `/highlights/ui/h/{id}/quote.png` — 1200×630 の PNG、本文 + 著者/書名アトリビューション、Pillow でオンデマンド生成。
- **絞り込みエクスポート** — `?tag=…&book_id=…&author=…&favorited_only=true&active_only=true` で `/export/csv` `/export/markdown.zip` を絞れる。
- **Markdown エクスポート** — Obsidian / Logseq / Notion 風味、本ごとに 1 `.md`、Zettelkasten 用の atomic-notes モードもあり。

### 6. 驚きなく運用する

- **`/healthz`** — カウント + Ollama 到達性。
- **`/metrics`** — Prometheus exposition（7 ゲージ）。
- **アトミック SQLite バックアップ** — `sqlite3.backup()` 使用。トークン認証 `/api/v2/admin/backup` と `freewise backup --to-dir DIR --retain N` で cron 用ローテーション。
- **IP 別レートリミッタ** + **セキュリティヘッダ** + **トークン prefix 表示付きハッシュ化 API トークン**。
- **forward-only マイグレーション** — Alembic なし、`app/db.py` が `PRAGMA table_info` で内省して冪等にカラム追加。SQLite が DROP NOT NULL できないケースは table-rebuild。
- **HTMX defer-load** — 重いダッシュボードウィジェット（重複グループスキャン、タグ付け率、on-this-day）はメインページが返ってから後追いロード。

### 7. 初日からマルチサーフェス

| サーフェス | 提供物 | 操作方法 |
|---|---|---|
| **Web UI** | デイリーレビュー、ダッシュボード、ライブラリ、検索、アクティビティ、ask、設定 | ブラウザで `:8063` |
| **REST API** | トークン認証 `/api/v2`（適切なところは Readwise 形式） | `Authorization: Token <raw>` |
| **CLI** | read / write / discovery / RAG / ops を 32 サブコマンドで網羅 | `freewise <cmd>` |
| **MCP** | Claude Code / Claude Desktop が読み書き可能な 30 ツール | stdio アダプタ |
| **Chrome 拡張** | Web 選択を右クリック → 保存 | `chrome://extensions` → `extensions/chrome/` をロード |

---

## サーフェスツアー

### Web UI

| パス | 内容 |
|---|---|
| `/dashboard/ui` | 統計、デイリーレビュー CTA、7 日間のアクティビティ sparkline → タイムラインへ、冷えた本ウィジェット、タグクラウド、埋め込みカバレッジ |
| `/highlights/ui/review` | デイリーレビューキュー。`j`/`Space` 次へ、`s`/`f` favorite、`x`/`d`/`#` discard。 |
| `/highlights/ui/search` | `<mark>` スニペット付き FTS5 検索、ファセットフィルタ、一括アクションバー。 |
| `/highlights/ui/activity` | 全アクション（favorite/discard/master/...）の新しい順タイムライン。どこからでも `g v`。 |
| `/highlights/ui/ask` | ライブラリへの RAG 質問応答、根拠ハイライト引用付き。埋め込みが必要。 |
| `/highlights/ui/h/{id}` | ハイライト permalink（OG リッチ）— `/quote.png` でソーシャルカード。 |
| `/highlights/ui/duplicates` | 完全一致重複グループ + 一括 discard。 |
| `/highlights/ui/duplicates/semantic` | コサイン類似ペアにワンクリック discard。 |
| `/library/ui` | 表紙画像付きの本グリッド、著者で絞り込み可。 |
| `/library/ui/book/{id}` | 本詳細 + 統計パネル + LLM 要約アクション。 |
| `/library/ui/authors` | 著者インデックス、本数 / ハイライト数でソート。 |
| `/digest/today` | 安定したデイリーダイジェスト（今日のピック、サンプル、on-this-day）。 |
| `/import/ui` | 複数フォーマット対応のインポート UI。 |
| `/import/api-token` | セルフサービスでの API トークン発行。 |
| `/settings/ui` | テーマ切替、デイリーレビュー件数、バックアップ、エクスポート。 |

**キーボードショートカット**：Gmail スタイル、`g` の後にレター。`g d` ダッシュボード / `g l` ライブラリ / `g r` レビュー / `g f` favorites / `g x` discarded / `g m` mastered / `g a` ask / `g u` duplicates / `g v` activity / `g i` import / `g s` settings / `g t` API トークン。どこからでも `?` でヘルプモーダル。

### REST API（`/api/v2`）

認証：`Authorization: Token <raw>`（Readwise 慣行、**`Bearer` ではない**）。トークンは `/import/api-token` で発行。

#### Highlights

| Method | Path | 内容 |
|---|---|---|
| `GET`    | `/api/v2/auth/` | トークン検証（成功時 204）。 |
| `GET`    | `/api/v2/highlights/` | ページネーション一覧。フィルタ：`book_id`, `favorited`, `discarded`, `mastered`。 |
| `POST`   | `/api/v2/highlights/` | バルク作成（Readwise 形ボディ）。 |
| `GET`    | `/api/v2/highlights/search` | `<mark>` スニペット付き FTS5 検索。フィルタ：`tag`, `include_discarded`, `favorited`, `mastered`。 |
| `GET`    | `/api/v2/highlights/random` | ランダム 1 件（`?book_id=` で絞り込み）。 |
| `GET`    | `/api/v2/highlights/today` | 安定した今日のハイライト（1 日中同じ）。 |
| `GET`    | `/api/v2/highlights/duplicates` | 完全一致重複グループ。 |
| `GET`    | `/api/v2/highlights/duplicates/semantic` | コサイン類似ペア。 |
| `GET`    | `/api/v2/highlights/{id}` | 詳細（タグ + 関連が有る場合は類似度付き）。 |
| `PATCH`  | `/api/v2/highlights/{id}` | note / favorite / discard / mastered を更新。 |
| `POST`   | `/api/v2/highlights/{id}/note/append` | アトミックな note 追記。 |
| `GET`    | `/api/v2/highlights/{id}/related` | Top-K 意味的類似（埋め込み必要）。 |
| `GET`    | `/api/v2/highlights/{id}/suggest-tags` | 埋め込み近傍ベースのタグ提案。 |
| `GET`    | `/api/v2/highlights/{id}/tags` | タグ列挙。 |
| `POST`   | `/api/v2/highlights/{id}/tags` | タグ付与（冪等）。 |
| `DELETE` | `/api/v2/highlights/{id}/tags/{name}` | タグ除去。 |

#### Discovery

| Method | Path | 内容 |
|---|---|---|
| `GET`  | `/api/v2/books/` | 本一覧。フィルタ：`author`、`q`（タイトル or 著者の部分一致）。 |
| `GET`  | `/api/v2/authors` | 著者の distinct 一覧（`?q=` 部分一致）。 |
| `GET`  | `/api/v2/tags` | タグの distinct 一覧。 |
| `GET`  | `/api/v2/stats` | カウント + レビュー残量。 |
| `POST` | `/api/v2/tags/{name}/rename` | グローバルなタグ rename。 |
| `POST` | `/api/v2/tags/{name}/merge` | タグを別タグへマージ。 |
| `POST` | `/api/v2/authors/rename` | 全本横断で著者を rename。 |

#### AI

| Method | Path | 内容 |
|---|---|---|
| `POST` | `/api/v2/ask` | ライブラリ全体への RAG。 |
| `POST` | `/api/v2/books/{id}/summarize` | 1 冊の LLM 要約。 |
| `POST` | `/api/v2/embeddings/backfill` | 埋め込みバッチ実行（CLI ドライバ）。 |

#### ログと運用

| Method | Path | 内容 |
|---|---|---|
| `GET`  | `/api/v2/review-log` | 新しい順アクションログ。`action`, `since` でフィルタ。 |
| `POST` | `/api/v2/admin/digest/send` | メールダイジェストを今すぐ送信。 |
| `GET`  | `/api/v2/admin/backup` | アトミック SQLite スナップショットをストリーム。 |
| `POST` | `/api/v2/kindle` | Kindle JSON 取り込みエンドポイント（スクレイパが利用）。 |

スキーマ詳細は [`docs/USAGE.md`](docs/USAGE.md)。ページネーションは Readwise の `count`/`next`/`previous` envelope に従います。

### `freewise` CLI

```bash
pip install -e cli/                    # または: uv pip install -e cli/
freewise auth login --url https://your-host --token <fw_…>
```

設定は `~/.config/freewise/config.toml` から読み、フォールバックで `FREEWISE_URL` / `FREEWISE_TOKEN` 環境変数。

| グループ | コマンド |
|---|---|
| **Auth** | `auth login` · `auth status` |
| **Read** | `search` · `recent` · `show` · `random` · `today` · `books` · `book-highlights` · `authors` · `tags` · `stats` · `health` |
| **Write** | `add` · `note` · `favorite` · `unfavorite` · `discard` · `restore` · `master` · `unmaster` · `tag {add,remove,list,rename,merge}` · `author rename` |
| **Discovery** | `duplicates` · `semantic-dupes` · `related` · `suggest-tags` |
| **AI** | `ask` · `summarize-book` · `embed-backfill` |
| **Ops** | `backup` · `digest` · `import` · `export {csv,markdown,atomic,notion}` |

**Read 系コマンドに搭載されたフィルタフラグ**（tri-state）：

- `freewise recent --favorited` / `--no-favorited`（`--discarded`、`--mastered` も同様）
- `freewise search "stoicism" --favorited --tag philosophy`
- `freewise books --author "橘玲"` または `freewise books --q stoic`

任意のコマンドに `--json` を付けると構造化出力でパイプできます。

### `freewise-mcp` MCP サーバー

```bash
pip install -e mcp/                    # または: uv pip install -e mcp/
```

`~/.claude.json` に追加：

```json
{
  "mcpServers": {
    "freewise": {
      "type": "stdio",
      "command": "freewise-mcp",
      "env": {
        "FREEWISE_URL": "https://your-host",
        "FREEWISE_TOKEN": "fw_…"
      }
    }
  }
}
```

Claude Code を再起動すると 30 ツールが追加されます：

| Read | Write | Discovery | AI | Ops |
|---|---|---|---|---|
| `freewise_search` | `freewise_set_note` | `freewise_books` | `freewise_ask` | `freewise_stats` |
| `freewise_recent` | `freewise_append_note` | `freewise_book_highlights` | `freewise_summarize_book` | `freewise_health` |
| `freewise_show` | `freewise_favorite` | `freewise_authors` | `freewise_related` | `freewise_backup` |
| `freewise_today` | `freewise_discard` | `freewise_tags` | `freewise_suggest_tags` | |
| `freewise_random` | `freewise_master` | `freewise_tag_list` | `freewise_semantic_dupes` | |
| | `freewise_add` | `freewise_duplicates` | | |
| | `freewise_tag_add` / `_remove` | | | |
| | `freewise_tag_rename` / `_merge` | | | |
| | `freewise_author_rename` | | | |

### Chrome 拡張

任意の Web 選択を右クリック → 「FreeWise に保存」 → `/api/v2/highlights/` に POST。MV3、リモートコードなし、トークンとベース URL は `chrome.storage.local` のみに保存（`sync` には絶対入れない — Google にトークンが見えるため）。

```bash
# 1. chrome://extensions → デベロッパーモード ON → パッケージ化されていない拡張機能を読み込む
# 2. extensions/chrome/ フォルダを選択
# 3. アイコンをクリック → ベース URL + API トークンを入力 → Save
```

**自動 E2E テスト** が同梱されています。`:8064` で FreeWise を新規起動し、テスト用 ApiToken を発行、本物の Chromium に拡張をロードして popup 設定 + 右クリック → POST → 検索の全フローを検証：

```bash
bash extensions/chrome/e2e/run.sh
```

---

## 設定リファレンス

すべて環境変数。`.env` と `.env.qnap` は gitignore 済み — シークレットはここへ。

| 変数 | デフォルト | 役割 |
|---|---|---|
| `FREEWISE_DB_URL` | `sqlite:///./db/freewise.db` | SQLAlchemy URL。アプリと CLI のローカル DB スクリプト両方が利用。 |
| `FREEWISE_URL` | `http://localhost:8063` | （CLI/MCP のみ）サーバーのベース URL。 |
| `FREEWISE_TOKEN` | unset | （CLI/MCP のみ）API トークン（生）。 |
| `FREEWISE_OLLAMA_URL` | `http://localhost:11434` | Ollama のベース URL。 |
| `FREEWISE_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | 埋め込みモデル。変更には再埋め込みが必要なので注意。 |
| `FREEWISE_OLLAMA_GENERATE_MODEL` | `llama3.2` | チャット / RAG モデル。 |
| `KINDLE_IMPORTS_DIR` | unset | 設定すると、ここに置かれた JSON/CSV を watcher が自動取込。 |
| `KINDLE_SCRAPE_CMD` | unset | ダッシュボードの「今すぐスクレイプ」ボタンが叩くコマンド。未設定時はボタン非表示。 |
| `KINDLE_SCRAPE_STATE_FILE` | `/tmp/freewise-kindle-scrape.json` | スクレイプボタンの state ファイル。 |
| `SMTP_HOST` / `_PORT` / `_USER` / `_PASS` / `_FROM` / `_TO` | unset | メールダイジェスト設定。どれかが欠けるとダイジェストは静かに無効化。 |

---

## 運用

### よく使う Docker コマンド

| 用途 | コマンド |
|---|---|
| 起動（初回 / 更新後） | `docker compose up -d --build` |
| 起動（リビルドなし） | `docker compose up -d` |
| 停止（データ保持） | `docker compose down` |
| 停止 + **全データ消去** | `docker compose down -v` |
| ログ追跡 | `docker compose logs -f freewise` |
| アプリのみ再起動 | `docker compose restart freewise` |

### 更新

```bash
git pull
docker compose up -d --build
```

forward-only マイグレーションが起動時に自動実行されます。FTS5 やカラムが欠けている場合は冪等にリビルド。

### バックアップ

最も綺麗なのはアプリ内エンドポイント（`sqlite3.backup()` を使用 — 書き込み中でもアトミック）：

```bash
freewise backup --to-dir ./backups --retain 7
# → ./backups/freewise-2026-05-04T22-26-00-123456.sqlite
```

または raw `curl`：

```bash
curl -H "Authorization: Token $FREEWISE_TOKEN" \
  https://your-host/api/v2/admin/backup -o freewise-$(date +%F).sqlite
```

アプリ停止時のフォールバックとして、ボリューム tar も依然有効：

```bash
docker run --rm \
  -v freewise-db:/data \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/freewise-db-backup.tar.gz -C /data .
```

### ボリューム

| Volume | マウント先 | 内容 |
|---|---|---|
| `freewise-db` | `/srv/freewise/db` | SQLite DB（FTS5 インデックス・埋め込み込み） |
| `freewise-covers` | `/srv/freewise/app/static/uploads/covers` | アップロードされた表紙画像 |

### 可観測性

- `GET /healthz` — JSON 形式の liveness probe（DB 到達 + 設定があれば Ollama）
- `GET /metrics` — Prometheus exposition：`freewise_highlights_total`、`_active`、`_favorited`、`_mastered`、`_books_total`、`_embeddings_count`、`_embedding_coverage`、`freewise_up`
- `crw-cloudflared` サイドカーが、メンテナの QNAP デプロイ用 Cloudflare トンネルを処理。

---

## 開発

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise

uv sync                                      # .venv に全依存を作成
uv run uvicorn app.main:app --reload         # http://localhost:8000

# 別シェルで Tailwind:
npm install
npm run build:css                            # 一回ビルド
npm run watch:css                            # watch モード
```

### テスト

3 つの独立スイート — それぞれ自分の in-process FastAPI app を立ち上げるため、コレクションを共有できません：

| スイート | テスト数 | 実行 |
|---|---|---|
| Server | 885 | `uv run pytest tests/` |
| CLI | 50 | `uv run pytest cli/tests/` |
| MCP | 31 | `uv run pytest mcp/tests/` |
| Chrome E2E | 3 | `bash extensions/chrome/e2e/run.sh` |
| **合計** | **969** | `scripts/test_all.sh`（3 つの Python スイートを順次実行） |

### プロジェクト構成

```
app/
├── main.py                       # FastAPI エントリ + lifespan
├── db.py                         # エンジン + forward-only マイグレーション + FTS5 設定
├── models.py                     # SQLModel ORM (Highlight, Book, Tag, ApiToken, ReviewLog, ...)
├── api_v2/                       # トークン認証 /api/v2/* エンドポイント
├── importers/                    # インポートパイプライン (Kindle JSON, Readwise CSV, ...)
├── middleware/                   # Starlette ミドルウェア
├── routers/                      # HTML ルート (dashboard, library, highlights, digest, ...)
├── services/                     # cold_books, review_log, search_snippet, embeddings,
│                                 # rag, digest, email, quote_card, kindle_*, book_stats
├── template_filters.py           # カスタム Jinja フィルタ
├── templates/                    # Jinja2 HTML
└── static/                       # コンパイル済 CSS, JS, アップロード表紙

cli/                              # `freewise` CLI（独立パッケージ、独自テスト、独自 uv.lock）
mcp/                              # 30 ツールの MCP stdio サーバー

extensions/
├── chrome/                       # MV3 Chrome 拡張
│   └── e2e/                      # 拡張用 Playwright E2E
└── kindle-importer/              # Kindle ハイライト抽出用の旧 MV3 拡張

scrapers/
└── kindle/                       # Playwright フォールバックスクレイパ（姉妹リポジトリ）

shared/                           # Python と TS で共有するセレクタ + JSON Schema

docs/
├── USAGE.md                      # CLI / API / MCP の全コマンドリファレンス
├── SEMANTIC_SETUP.md             # Ollama インストール + 初回バックフィル
├── KINDLE_JSON_SCHEMA.md         # Kindle スクレイパとの契約
└── KINDLE_BROWSER_EXTENSION.md   # MV3 拡張のアーキテクチャ・インストール・エラーマトリクス

tests/                            # サーバー pytest スイート
CHANGELOG.md                      # テーマ別変更履歴
Dockerfile                        # マルチステージ Node → Python プロダクションイメージ
docker-compose.yml                # シングルサービス構成
```

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| **既知の語で検索ヒット 0** | FTS5 インデックスが古いか欠けている。 | 再起動 — lifespan で再構築されます。`/healthz` でカラム件数を確認できます。 |
| **`/api/v2/highlights/?favorited=true` が全件返る** | PR #9 以前のビルドです。 | `git pull && docker compose up -d --build`。 |
| **`freewise auth login` が 401** | トークンに空白があるか、`Bearer` を使った。 | `/import/api-token` で再発行。CLI は空白を strip しますが、raw curl は `Authorization: Token <raw>` 必須。 |
| **`/highlights/ui/ask` が「埋め込みなし」** | バックフィルを実行していない。 | `freewise embed-backfill --batch-size 64` — 冪等・再開可能。 |
| **Chrome 拡張で「FreeWise: HTTP 401」** | ベース URL かトークンが間違っている。 | 拡張アイコン → Test connection で確認。 |
| **メールダイジェストが届かないが `freewise digest` の dry-run は成功** | SMTP 環境変数のどれかが欠けている。 | `docker compose exec freewise env \| grep SMTP` で確認。どれかが欠けるとダイジェストは fail closed（無音）。 |
| **`docker compose down -v` でハイライトが消えた** | `-v` フラグは設計通りに名前付きボリュームを削除します。 | `freewise backup` のスナップショットから復元。**`down -v` の前は必ずバックアップ**。 |
| **Kindle スクレイパの取得件数が 0** | Amazon がセレクタを変更したか、セッション cookie が失効。 | [`freewise-qnap-kindle`](https://github.com/chkk525/freewise-qnap-kindle) のセットアップフローで再認証。 |
| **同じ著者が微妙に異なる表記で複数現れる** | ソースデータの全角/半角空白や末尾タイポ。 | `freewise author rename "old" "new"` で正規表記へ統合。 |

それ以外は `docker compose logs -f freewise` で `ERROR` を grep してください。たいていの問題はそこに見えています。

---

## ロードマップ

**確認済み wishlist**（自律実装可能 — UX 再設計を伴わない）：

- [ ] PWA 完全オフラインモード（Service Worker + IndexedDB キャッシュ）。
- [ ] 差分 Kindle スクレイプ（前回以降に変更があった本だけ）。
- [ ] 本詳細ページに PDF / EPUB の添付表示。
- [ ] Notion 双方向同期（「Currently reading」状態）。

**ユーザー判断が必要な大物**：

- A3 — メールダイジェスト本文のリデザイン（HTML モックアップ待ち）。
- A7 — マルチデバイスでの既読状態（「シングルユーザー」不変条件を破る可能性）。

シップ済みのタイムラインは [`CHANGELOG.md`](CHANGELOG.md) を参照。

---

## コントリビューション

シングルユーザーフォークなので、バグ報告は Issue で歓迎しますが、**ここからの PR は upstream にはマージされません**。upstream への貢献は本家 [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise) で。

このフォークをさらにフォークするのは大歓迎 — CC0 です。Conventional Commits（`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`）を推奨。新機能にはテストを期待します（スイートは速く、3 つで合計約 15 秒の 969 テスト）。

---

## 謝辞

[`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise) の上に構築 — CRUD/インポート/レビューの土台はそのままです。本フォークが追加したのは検索・AI/RAG・マルチサーフェス（CLI + MCP + 拡張）・Kindle スクレイプ・運用レイヤ。

[Readwise](https://readwise.io) からインスピレーションを得ました — デイリーレビューループが機能することを証明してくれて感謝。これはそれをサブスクで借りずに自己ホストしたい人のための答えです。

---

## ライセンス

[CC0](LICENSE) — upstream と同じ。持ち帰り、フォーク、ポート、販売、すべて自由。
