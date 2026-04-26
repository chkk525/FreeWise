"""freewise CLI entry point.

Designed for shell + Claude Code use. Every subcommand supports ``--json`` for
machine-readable output. Without ``--json``, output is compact human-readable
text suitable for streaming to a terminal or to Claude.

Examples
--------
    freewise auth login --token fw_xxx
    freewise auth status
    freewise search "stoicism" --limit 5
    freewise recent --limit 10
    freewise show 1234
    freewise stats
    freewise note 1234 "this idea matters because…"
    freewise favorite 1234
    freewise unfavorite 1234
    freewise discard 1234
    freewise restore 1234
    freewise add --text "..." --book "Book Title" --author "Author"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from freewise_cli import config
from freewise_cli.client import Client, FreewiseError


def _client_from_args(args: argparse.Namespace) -> Client:
    cfg = config.load()
    url = args.url or cfg.url
    token = args.token or cfg.token
    return Client(url=url, token=token)


# ── Output helpers ─────────────────────────────────────────────────────────


def _print_json(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _print_highlight_short(h: dict) -> None:
    """One-line summary for list views: id, optional star, location, snippet."""
    star = "★ " if h.get("is_favorited") else "  "
    loc = ""
    if h.get("location") is not None:
        loc = f" @{h['location']}"
    title = h.get("title") or "(unbound)"
    snippet = (h.get("text") or "").replace("\n", " ").strip()
    if len(snippet) > 100:
        snippet = snippet[:97] + "…"
    print(f"{star}#{h['id']:<6} {title[:40]:<40}{loc}  {snippet}")


def _print_highlight_full(h: dict) -> None:
    """Full detail block for show/get."""
    print(f"#{h['id']}  {h.get('title') or '(unbound)'}")
    if h.get("author"):
        print(f"  by {h['author']}")
    if h.get("location") is not None:
        loc_unit = f" ({h['location_type']})" if h.get("location_type") else ""
        print(f"  location: {h['location']}{loc_unit}")
    if h.get("highlighted_at"):
        print(f"  highlighted: {h['highlighted_at']}")
    flags = []
    if h.get("is_favorited"): flags.append("favorited")
    if h.get("is_discarded"): flags.append("discarded")
    if h.get("is_mastered"): flags.append("mastered")
    if flags:
        print(f"  flags: {', '.join(flags)}")
    print()
    print(h.get("text") or "")
    if h.get("note"):
        print()
        print("  note:")
        for line in (h["note"]).splitlines():
            print(f"    {line}")


def _print_stats(s: dict) -> None:
    print(f"highlights total:     {s['highlights_total']}")
    print(f"  active:             {s['highlights_active']}")
    print(f"  discarded:          {s['highlights_discarded']}")
    print(f"  favorited:          {s['highlights_favorited']}")
    if "highlights_mastered" in s:
        print(f"  mastered:           {s['highlights_mastered']}")
    print(f"books:                {s['books_total']}")
    print(f"due for review today: {s['review_due_today']}")


# ── Subcommand handlers ────────────────────────────────────────────────────


def cmd_auth_login(args: argparse.Namespace) -> int:
    cfg = config.load()
    url = args.url or cfg.url
    token = args.token
    if not token:
        print("error: --token is required", file=sys.stderr)
        return 2
    # Verify before saving.
    client = Client(url=url, token=token)
    try:
        client.auth_check()
    except FreewiseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    path = config.save(url, token)
    print(f"saved {url} + token to {path}")
    return 0


def cmd_auth_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    url = args.url or cfg.url
    token = args.token or cfg.token
    masked = (token[:8] + "…" + token[-4:]) if token and len(token) > 12 else "(unset)"
    if args.json:
        _print_json({"url": url, "token": masked, "source": cfg.source})
        return 0
    print(f"url:    {url}")
    print(f"token:  {masked}")
    print(f"source: {cfg.source}")
    if not token:
        return 1
    client = Client(url=url, token=token)
    try:
        client.auth_check()
        print("auth:   ok")
        return 0
    except FreewiseError as e:
        print(f"auth:   FAILED ({e})")
        return 1


def cmd_search(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.search(
        args.query, page=1, page_size=args.limit,
        include_discarded=args.include_discarded,
        tag=getattr(args, "tag", None),
    )
    if args.json:
        _print_json(body)
        return 0
    print(f"{body['count']} match{'es' if body['count'] != 1 else ''} for {args.query!r}")
    print()
    for h in body["results"]:
        _print_highlight_short(h)
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_highlights(page=1, page_size=args.limit)
    if args.json:
        _print_json(body)
        return 0
    print(f"{len(body['results'])} of {body['count']} total highlights (newest first)")
    print()
    for h in body["results"]:
        _print_highlight_short(h)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.get_highlight(args.highlight_id)
    if args.json:
        _print_json(h)
        return 0
    _print_highlight_full(h)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    s = client.stats()
    if args.json:
        _print_json(s)
        return 0
    _print_stats(s)
    return 0


def cmd_books(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_books(page=1, page_size=args.limit)
    if args.json:
        _print_json(body)
        return 0
    print(f"{len(body['results'])} of {body['count']} books")
    for b in body["results"]:
        author = f" — {b['author']}" if b.get("author") else ""
        print(f"  #{b['id']:<5} ({b['num_highlights']:>4}) {b['title']}{author}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, note=args.note)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} note updated")
    return 0


def cmd_favorite(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_favorited=True)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} ★ favorited")
    return 0


def cmd_unfavorite(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_favorited=False)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} unfavorited")
    return 0


def cmd_discard(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_discarded=True)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} discarded")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_discarded=False)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} restored")
    return 0


def cmd_master(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_mastered=True)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} mastered (excluded from review)")
    return 0


def cmd_unmaster(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.patch_highlight(args.highlight_id, is_mastered=False)
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} unmastered (back in review queue)")
    return 0


def cmd_tag_list(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_tags(args.highlight_id)
    if args.json:
        _print_json(body)
        return 0
    tags = body.get("tags", [])
    if not tags:
        print(f"#{args.highlight_id}: (no tags)")
    else:
        print(f"#{args.highlight_id}: {', '.join(tags)}")
    return 0


def cmd_tag_add(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.add_tag(args.highlight_id, args.tag)
    if args.json:
        _print_json(body)
        return 0
    print(f"#{args.highlight_id} tags: {', '.join(body.get('tags', []))}")
    return 0


def cmd_tag_remove(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.remove_tag(args.highlight_id, args.tag)
    if args.json:
        _print_json(body)
        return 0
    print(f"#{args.highlight_id} tags: {', '.join(body.get('tags', []))}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body, suggested_name = client.stream_export(
        args.format, book_id=getattr(args, "book_id", None),
    )
    if args.output is None or args.output == "-":
        # Stream to stdout. CSV is text — write to the encoding-aware buffer.
        # Markdown ZIP is binary — write to the underlying buffer.
        if args.format == "csv":
            sys.stdout.write(body.decode("utf-8", errors="replace"))
        else:
            sys.stdout.buffer.write(body)
        return 0
    out_path = args.output
    # If user passed a directory, append the server-suggested filename.
    import os
    if os.path.isdir(out_path):
        out_path = os.path.join(out_path, suggested_name or f"freewise-export.{args.format}")
    with open(out_path, "wb") as f:
        f.write(body)
    print(f"wrote {len(body):,} bytes to {out_path}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.create_highlight(
        text=args.text, title=args.book, author=args.author,
        note=args.note, location=args.location, location_type=args.location_type,
    )
    if args.json:
        _print_json(body)
        return 0
    if body["created"]:
        print(f"created {body['created']} highlight (skipped {body['skipped_duplicates']} duplicate{'s' if body['skipped_duplicates'] != 1 else ''})")
    else:
        print(f"no new highlights (skipped {body['skipped_duplicates']} duplicate{'s' if body['skipped_duplicates'] != 1 else ''})")
    if body.get("errors"):
        for e in body["errors"]:
            print(f"  error: {e}", file=sys.stderr)
        return 1
    return 0


# ── Argument parser ────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="freewise",
        description="Command-line client for FreeWise. Search, read, and manage your highlights.",
    )
    # Global flags so any subcommand can override config.
    p.add_argument("--url", help="Base URL of FreeWise server (overrides FREEWISE_URL / config).")
    p.add_argument("--token", help="API token (overrides FREEWISE_TOKEN / config).")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output.")

    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    # auth
    auth = sub.add_parser("auth", help="Manage saved auth.")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True, metavar="<subcmd>")
    auth_login = auth_sub.add_parser("login", help="Validate and persist an API token.")
    auth_login.set_defaults(func=cmd_auth_login)
    auth_status = auth_sub.add_parser("status", help="Show current url + masked token.")
    auth_status.set_defaults(func=cmd_auth_status)

    # search
    s = sub.add_parser("search", help="Full-text search (text + note).")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--include-discarded", action="store_true")
    s.add_argument("--tag", help="Filter to highlights carrying this tag (case-insensitive).")
    s.set_defaults(func=cmd_search)

    # tag list/add/remove
    tg = sub.add_parser("tag", help="Manage highlight tags.")
    tg_sub = tg.add_subparsers(dest="tag_cmd", required=True, metavar="<subcmd>")
    tgl = tg_sub.add_parser("list", help="List tags on a highlight.")
    tgl.add_argument("highlight_id", type=int)
    tgl.set_defaults(func=cmd_tag_list)
    tga = tg_sub.add_parser("add", help="Attach a tag to a highlight (idempotent).")
    tga.add_argument("highlight_id", type=int)
    tga.add_argument("tag")
    tga.set_defaults(func=cmd_tag_add)
    tgr = tg_sub.add_parser("remove", help="Remove a tag from a highlight (idempotent).")
    tgr.add_argument("highlight_id", type=int)
    tgr.add_argument("tag")
    tgr.set_defaults(func=cmd_tag_remove)

    # recent
    r = sub.add_parser("recent", help="Most recent highlights.")
    r.add_argument("--limit", type=int, default=10)
    r.set_defaults(func=cmd_recent)

    # show
    sh = sub.add_parser("show", help="Show a single highlight in full.")
    sh.add_argument("highlight_id", type=int)
    sh.set_defaults(func=cmd_show)

    # stats
    st = sub.add_parser("stats", help="Aggregate counts + review-due summary.")
    st.set_defaults(func=cmd_stats)

    # books
    b = sub.add_parser("books", help="List books that have at least one highlight.")
    b.add_argument("--limit", type=int, default=20)
    b.set_defaults(func=cmd_books)

    # note <id> "..."
    n = sub.add_parser("note", help="Replace the note on a highlight (use empty string to clear).")
    n.add_argument("highlight_id", type=int)
    n.add_argument("note")
    n.set_defaults(func=cmd_note)

    # favorite / unfavorite / discard / restore
    fav = sub.add_parser("favorite", help="Mark a highlight as favorited.")
    fav.add_argument("highlight_id", type=int)
    fav.set_defaults(func=cmd_favorite)

    unfav = sub.add_parser("unfavorite", help="Remove the favorited flag.")
    unfav.add_argument("highlight_id", type=int)
    unfav.set_defaults(func=cmd_unfavorite)

    dis = sub.add_parser("discard", help="Mark a highlight as discarded.")
    dis.add_argument("highlight_id", type=int)
    dis.set_defaults(func=cmd_discard)

    rest = sub.add_parser("restore", help="Restore a discarded highlight to active.")
    rest.add_argument("highlight_id", type=int)
    rest.set_defaults(func=cmd_restore)

    mas = sub.add_parser("master", help="Mark mastered (excluded from review queue).")
    mas.add_argument("highlight_id", type=int)
    mas.set_defaults(func=cmd_master)

    unmas = sub.add_parser("unmaster", help="Clear the mastered flag.")
    unmas.add_argument("highlight_id", type=int)
    unmas.set_defaults(func=cmd_unmaster)

    # export
    ex = sub.add_parser("export", help="Download CSV / Markdown / atomic-notes export.")
    ex.add_argument(
        "format",
        choices=["csv", "markdown", "md", "atomic", "atomic-notes"],
        help=(
            "csv = Readwise-compatible CSV; markdown/md = one .md per book ZIP; "
            "atomic/atomic-notes = one .md per highlight ZIP (Zettelkasten-style)."
        ),
    )
    ex.add_argument(
        "--book-id", type=int,
        help="(atomic only) Limit to highlights from one book.",
    )
    ex.add_argument(
        "-o", "--output",
        help="Output path. If omitted or '-', stream to stdout. If a directory, "
             "use the server-suggested filename.",
    )
    ex.set_defaults(func=cmd_export)

    # add
    a = sub.add_parser("add", help="Create a new highlight (manual capture).")
    a.add_argument("--text", required=True, help="Highlight text.")
    a.add_argument("--book", help="Book title — created if missing.")
    a.add_argument("--author", help="Book author.")
    a.add_argument("--note", help="Optional note.")
    a.add_argument("--location", type=int, help="Location/page number.")
    a.add_argument("--location-type", help="Location unit (page, order, ...).")
    a.set_defaults(func=cmd_add)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FreewiseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
