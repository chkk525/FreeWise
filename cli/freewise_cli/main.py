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


def cmd_book_highlights(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_highlights(page=1, page_size=args.limit, book_id=args.book_id)
    if args.json:
        _print_json(body)
        return 0
    print(f"{len(body['results'])} of {body['count']} highlights for book #{args.book_id}")
    print()
    for h in body["results"]:
        _print_highlight_short(h)
    return 0


def cmd_summarize_book(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.summarize_book(
        args.book_id, question=args.question, top_k=args.top_k,
    )
    if args.json:
        _print_json(body)
        return 0
    title = body.get("book_title") or f"book #{body.get('book_id')}"
    print(f"Summary of {title}")
    print()
    print(body.get("answer", "(no answer)"))
    cites = body.get("citations") or []
    if cites:
        print()
        print(f"--- {len(cites)} citation{'s' if len(cites) != 1 else ''} ---")
        for c in cites:
            sim = c.get("similarity", 0.0)
            snippet = (c.get("text") or "").replace("\n", " ").strip()
            if len(snippet) > 100:
                snippet = snippet[:97] + "…"
            print(f"  [#{c['id']:<6} {sim:.3f}]  {snippet}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.ask(
        args.question, top_k=args.top_k,
        generate_model=args.generate_model, embed_model=args.embed_model,
    )
    if args.json:
        _print_json(body)
        return 0
    print(body.get("answer", "(no answer)"))
    cites = body.get("citations") or []
    if cites:
        print()
        print(f"--- {len(cites)} citation{'s' if len(cites) != 1 else ''} ---")
        for c in cites:
            sim = c.get("similarity", 0.0)
            book = c.get("book_title") or "(unbound)"
            snippet = (c.get("text") or "").replace("\n", " ").strip()
            if len(snippet) > 100:
                snippet = snippet[:97] + "…"
            print(f"  [#{c['id']:<6} {sim:.3f}]  {book[:30]:<30}  {snippet}")
    if body.get("truncated"):
        print()
        print("(citations truncated to fit prompt — try lowering --top-k)")
    return 0


def cmd_embed_backfill(args: argparse.Namespace) -> int:
    """Drive the embedding backfill loop until no rows remain or --max is hit.

    Talks to the *running* FreeWise server via a new HTTP endpoint that
    runs one batch and returns a JSON report. We loop client-side so the
    user sees progress and can Ctrl-C cleanly.
    """
    client = _client_from_args(args)
    total_embedded = 0
    total_failed = 0
    iterations = 0
    while True:
        body = client.backfill_embeddings(
            batch_size=args.batch_size, model=args.model,
        )
        iterations += 1
        total_embedded += body["embedded"]
        total_failed += body["failed"]
        remaining = body["remaining"]
        print(
            f"  [iter {iterations:>3}] embedded={body['embedded']:>4} "
            f"skipped={body['skipped']:>4} failed={body['failed']:>4} "
            f"remaining={remaining:>5}"
        )
        if remaining == 0:
            break
        if args.max and total_embedded >= args.max:
            print(f"  reached --max {args.max}; stopping early")
            break
        if body["embedded"] == 0 and body["skipped"] == 0:
            # Nothing to do but failures — bail out so we don't loop forever.
            print("  all remaining rows failed; stopping")
            break
    print()
    print(f"done: embedded {total_embedded}, failed {total_failed}, remaining {remaining}")
    return 1 if total_failed else 0


def cmd_suggest_tags(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.suggest_tags(
        args.highlight_id, neighbors=args.neighbors, limit=args.limit,
    )
    if args.json:
        _print_json(body)
        return 0
    if body["count"] == 0:
        print(
            f"#{args.highlight_id}: no tag suggestions. "
            "Either no embedding for this highlight (run `freewise embed-backfill`) "
            "or its semantic neighbors have no tags yet."
        )
        return 0
    print(f"Top {body['count']} tag suggestion{'s' if body['count'] != 1 else ''} for #{args.highlight_id}:")
    print()
    for r in body["results"]:
        print(f"  [{r['score']:.3f} · seen {r['neighbor_count']}×]  {r['name']}")
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.related_highlights(args.highlight_id, limit=args.limit)
    if args.json:
        _print_json(body)
        return 0
    if body["count"] == 0:
        print(f"#{args.highlight_id}: no related highlights yet — run `freewise embed-backfill` first?")
        return 0
    print(f"Top {body['count']} highlights related to #{args.highlight_id}:")
    print()
    for h in body["results"]:
        sim = h.get("similarity", 0.0)
        score = f"{sim:.3f}"
        title = h.get("title") or "(unbound)"
        snippet = (h.get("text") or "").replace("\n", " ").strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "…"
        print(f"  [{score}]  #{h['id']:<6} {title[:30]:<30}  {snippet}")
    return 0


def cmd_semantic_dupes(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.find_semantic_duplicates(
        threshold=args.threshold, limit=args.limit,
    )
    if args.json:
        _print_json(body)
        return 0
    if body["count"] == 0:
        print(
            "No semantic duplicates found. "
            "If embedded == 0 in `freewise health`, run `freewise embed-backfill` first."
        )
        return 0
    print(f"{body['count']} semantically-similar pair{'s' if body['count'] != 1 else ''} (threshold {args.threshold}):")
    print()
    for pair in body["results"]:
        sim = pair["similarity"]
        a = (pair["a_text"] or "").replace("\n", " ").strip()
        b = (pair["b_text"] or "").replace("\n", " ").strip()
        if len(a) > 70: a = a[:67] + "…"
        if len(b) > 70: b = b[:67] + "…"
        print(f"  [{sim:.3f}]  #{pair['a_id']:<6} {a}")
        print(f"           #{pair['b_id']:<6} {b}")
        print()
    return 0


def cmd_duplicates(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.find_duplicates(
        prefix_chars=args.prefix_chars,
        min_group_size=args.min_group_size,
        limit=args.limit,
    )
    if args.json:
        _print_json(body)
        return 0
    if body["count"] == 0:
        print("No duplicate groups found.")
        return 0
    print(f"{body['count']} duplicate group{'s' if body['count'] != 1 else ''} (sorted by group size desc)")
    print()
    for grp in body["results"]:
        snippet = (grp["prefix"] or "").replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:57] + "…"
        print(f"× {grp['count']}  {snippet}")
        for m in grp["members"]:
            book = m.get("title") or "(unbound)"
            print(f"   #{m['id']:<6}  {book[:30]}")
        print()
    return 0


def cmd_today(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.today_highlight(salt=args.salt)
    if args.json:
        _print_json(h)
        return 0
    print(f"Highlight of the day ({getattr(args, 'salt', None) or 'default'}):")
    print()
    _print_highlight_full(h)
    return 0


def cmd_random(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    h = client.random_highlight(book_id=getattr(args, "book_id", None))
    if args.json:
        _print_json(h)
        return 0
    _print_highlight_full(h)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    import os
    if not os.path.exists(args.path):
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    # Snapshot stats before so we can report deltas.
    stats_before = None
    try:
        stats_before = client.stats()
    except FreewiseError:
        # Stats requires a token; fail soft so users can still import
        # even if they haven't configured a token.
        pass

    print(f"uploading {args.path}…")
    status, body = client.import_file(args.path)
    if status >= 400:
        print(f"import failed (HTTP {status}): {body}", file=sys.stderr)
        return 1

    print(f"import succeeded (HTTP {status})")
    if stats_before is not None:
        try:
            stats_after = client.stats()
            new = stats_after["highlights_total"] - stats_before["highlights_total"]
            print(
                f"  {new:+d} highlight{'s' if new != 1 else ''} "
                f"(was {stats_before['highlights_total']}, now {stats_after['highlights_total']})"
            )
        except FreewiseError:
            pass
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.healthz()
    if args.json:
        _print_json(body)
        return 0
    status = body.get("status", "unknown")
    hl = body.get("highlights") or {}
    ol = body.get("ollama") or {}
    print(f"status:        {status}")
    if "embed_model" in body:
        print(f"embed model:   {body['embed_model']}")
    print(f"active:        {hl.get('active', '?')}")
    print(f"embedded:      {hl.get('embedded', '?')} ({hl.get('embedded_pct', '?')}%)")
    ok = "yes" if ol.get("reachable") else "no"
    # U67: /healthz now exposes host-only (not full url) to avoid leaking
    # internal topology. Stay forward-compatible with both shapes.
    target = ol.get("host") or ol.get("url") or "?"
    print(f"ollama:        {ok} @ {target}")
    # Non-zero exit if degraded so it can drive monitor scripts.
    return 0 if status == "ok" else 1


def cmd_backup(args: argparse.Namespace) -> int:
    """Download an atomic SQLite snapshot.

    Two modes:
      single-file:   --out PATH                (default: cwd freewise-YYYY-MM-DD.sqlite)
      rotating dir:  --to-dir DIR [--retain N] (cron-friendly, prunes oldest)
    """
    import glob
    import os
    from datetime import datetime as _datetime, timezone as _tz

    if args.to_dir:
        if args.out:
            print("--to-dir and --out are mutually exclusive", file=sys.stderr)
            return 2
        os.makedirs(args.to_dir, exist_ok=True)
        # Sub-second granularity in the timestamp prevents two cron
        # invocations within the same second from clobbering each other.
        now_utc = _datetime.now(_tz.utc)
        stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
        out = os.path.join(args.to_dir, f"freewise-{stamp}.sqlite")
    else:
        out = args.out or f"freewise-{_datetime.now(_tz.utc).date().isoformat()}.sqlite"
        if os.path.exists(out) and not args.force:
            print(f"refusing to overwrite existing {out!r} (pass --force)", file=sys.stderr)
            return 2

    client = _client_from_args(args)
    written = client.backup(out)

    pruned: list[str] = []
    if args.to_dir and args.retain and args.retain > 0:
        # List EVERY freewise-*.sqlite in the dir, sort newest-first by
        # mtime (the file we just wrote will be on top), drop everything
        # past the retention window. Glob pattern is bounded to our own
        # filename prefix so we never delete unrelated files.
        candidates = glob.glob(os.path.join(args.to_dir, "freewise-*.sqlite"))
        candidates.sort(key=os.path.getmtime, reverse=True)
        for victim in candidates[args.retain:]:
            try:
                os.unlink(victim)
                pruned.append(victim)
            except OSError as e:
                print(f"warn: could not prune {victim}: {e}", file=sys.stderr)

    if args.json:
        _print_json({"path": out, "bytes": written, "pruned": pruned})
        return 0
    print(f"wrote {written:,} bytes → {out}")
    if pruned:
        print(f"pruned {len(pruned)} old snapshot(s):")
        for p in pruned:
            print(f"  rm {p}")
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


def cmd_tag_rename(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.rename_tag(args.old, args.new)
    if args.json:
        _print_json(body)
        return 0
    print(f"renamed → {body['name']} ({body['highlight_count']} highlight{'s' if body['highlight_count'] != 1 else ''})")
    return 0


def cmd_tag_merge(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.merge_tag(args.src, args.into)
    if args.json:
        _print_json(body)
        return 0
    print(f"merged → {body['name']} ({body['highlight_count']} highlight{'s' if body['highlight_count'] != 1 else ''})")
    return 0


def cmd_author_rename(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.rename_author(args.old, args.new)
    if args.json:
        _print_json(body)
        return 0
    print(f"renamed → {body['name']} ({body['book_count']} book{'s' if body['book_count'] != 1 else ''}, {body['highlight_count']} highlight{'s' if body['highlight_count'] != 1 else ''})")
    return 0


def cmd_tags(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_tag_summary(
        page=1, page_size=args.limit, q=getattr(args, "query", None),
    )
    if args.json:
        _print_json(body)
        return 0
    print(f"{len(body['results'])} of {body['count']} tags (sorted by use)")
    for t in body["results"]:
        print(f"  {t['highlight_count']:>5}  {t['name']}")
    return 0


def cmd_authors(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    body = client.list_authors(
        page=1, page_size=args.limit, q=getattr(args, "query", None),
    )
    if args.json:
        _print_json(body)
        return 0
    print(f"{len(body['results'])} of {body['count']} authors (sorted by highlight count)")
    for a in body["results"]:
        print(f"  {a['highlight_count']:>5} hl · {a['book_count']:>3} book{'s' if a['book_count'] != 1 else ''}  {a['name']}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    if getattr(args, "append", False):
        h = client.append_note(args.highlight_id, args.note)
        msg = "note appended"
    else:
        h = client.patch_highlight(args.highlight_id, note=args.note)
        msg = "note updated"
    if args.json:
        _print_json(h)
        return 0
    print(f"#{h['id']} {msg}")
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

    # tags (summary listing)
    tgs = sub.add_parser("tags", help="List all highlight-level tags with counts.")
    tgs.add_argument("query", nargs="?", help="Optional substring filter.")
    tgs.add_argument("--limit", type=int, default=100)
    tgs.set_defaults(func=cmd_tags)

    # tag list/add/remove/rename/merge
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
    tgrn = tg_sub.add_parser("rename", help="Rename a tag globally.")
    tgrn.add_argument("old")
    tgrn.add_argument("new")
    tgrn.set_defaults(func=cmd_tag_rename)
    tgmg = tg_sub.add_parser("merge", help="Merge a tag into another (links combine, source deleted).")
    tgmg.add_argument("src")
    tgmg.add_argument("into")
    tgmg.set_defaults(func=cmd_tag_merge)

    # author rename
    aurn = sub.add_parser("author", help="Manage authors.")
    aurn_sub = aurn.add_subparsers(dest="author_cmd", required=True, metavar="<subcmd>")
    aurnr = aurn_sub.add_parser("rename", help="Rename an author across every book.")
    aurnr.add_argument("old", help="Existing author name (exact match).")
    aurnr.add_argument("new", help="New author name.")
    aurnr.set_defaults(func=cmd_author_rename)

    # recent
    r = sub.add_parser("recent", help="Most recent highlights.")
    r.add_argument("--limit", type=int, default=10)
    r.set_defaults(func=cmd_recent)

    # show
    sh = sub.add_parser("show", help="Show a single highlight in full.")
    sh.add_argument("highlight_id", type=int)
    sh.set_defaults(func=cmd_show)

    # random
    rd = sub.add_parser("random", help="Pick one random highlight (surprise me).")
    rd.add_argument("--book-id", type=int, help="Limit to one book.")
    rd.set_defaults(func=cmd_random)

    # today (deterministic daily pick)
    td = sub.add_parser("today", help="Stable highlight of the day (same all day).")
    td.add_argument("--salt", help="Optional salt to vary the pick (e.g. 'morning').")
    td.set_defaults(func=cmd_today)

    # duplicates
    dp = sub.add_parser("duplicates", help="Find probable duplicate highlights (e.g. after re-import).")
    dp.add_argument("--prefix-chars", type=int, default=80,
                    help="How many leading chars are used to group (default 80).")
    dp.add_argument("--min-group-size", type=int, default=2,
                    help="Minimum members for a group to be reported (default 2).")
    dp.add_argument("--limit", type=int, default=50,
                    help="Max groups returned (default 50).")
    dp.set_defaults(func=cmd_duplicates)

    # semantic-dupes (embedding-based)
    sd = sub.add_parser("semantic-dupes",
                        help="Find paraphrase / same-idea highlight pairs via embeddings (needs Ollama backfill).")
    sd.add_argument("--threshold", type=float, default=0.92,
                    help="Min cosine similarity to count as duplicate (0.5-1.0, default 0.92).")
    sd.add_argument("--limit", type=int, default=100,
                    help="Max pairs returned (default 100).")
    sd.set_defaults(func=cmd_semantic_dupes)

    # related
    rl = sub.add_parser("related", help="Top-K semantically related highlights (needs embeddings).")
    rl.add_argument("highlight_id", type=int)
    rl.add_argument("--limit", type=int, default=10)
    rl.set_defaults(func=cmd_related)

    # suggest-tags
    sg = sub.add_parser("suggest-tags",
                        help="Suggest tags for a highlight based on its semantic neighbors (needs embeddings).")
    sg.add_argument("highlight_id", type=int)
    sg.add_argument("--neighbors", type=int, default=20,
                    help="How many semantic neighbors to harvest tags from (default 20).")
    sg.add_argument("--limit", type=int, default=5,
                    help="Max suggestions returned (default 5).")
    sg.set_defaults(func=cmd_suggest_tags)

    # ask (RAG)
    ak = sub.add_parser("ask", help="Ask a question about your library (needs Ollama embed + generate).")
    ak.add_argument("question")
    ak.add_argument("--top-k", type=int, default=8, help="How many highlights to cite (default 8).")
    ak.add_argument("--embed-model", help="Override FREEWISE_OLLAMA_EMBED_MODEL.")
    ak.add_argument("--generate-model", help="Override FREEWISE_OLLAMA_GENERATE_MODEL.")
    ak.set_defaults(func=cmd_ask)

    # summarize-book (RAG scoped to one book)
    sb = sub.add_parser("summarize-book", help="LLM summary of one book using its highlights.")
    sb.add_argument("book_id", type=int)
    sb.add_argument("--question", help="Override the default 'summarize key themes' prompt.")
    sb.add_argument("--top-k", type=int, default=12)
    sb.set_defaults(func=cmd_summarize_book)

    # embed-backfill
    eb = sub.add_parser("embed-backfill", help="Generate embeddings for highlights that don't have them yet.")
    eb.add_argument("--batch-size", type=int, default=64, help="How many highlights per batch (default 64).")
    eb.add_argument("--max", type=int, default=0, help="Stop after this many embeddings (0 = no cap).")
    eb.add_argument("--model", help="Override FREEWISE_OLLAMA_EMBED_MODEL.")
    eb.set_defaults(func=cmd_embed_backfill)

    # stats
    st = sub.add_parser("stats", help="Aggregate counts + review-due summary.")
    st.set_defaults(func=cmd_stats)

    # health
    hc = sub.add_parser("health", help="Liveness/readiness probe (status, counts, Ollama).")
    hc.set_defaults(func=cmd_health)

    # backup
    bk = sub.add_parser("backup", help="Download an atomic SQLite snapshot of the database.")
    bk.add_argument("--out", help="Single-file mode output path (default: ./freewise-YYYY-MM-DD.sqlite).")
    bk.add_argument("--force", action="store_true", help="Overwrite an existing file at --out.")
    bk.add_argument("--to-dir", help="Rotating mode: write timestamped snapshot in DIR. Mutually exclusive with --out.")
    bk.add_argument("--retain", type=int, default=0, help="Keep only N most-recent snapshots in --to-dir (0 = no pruning).")
    bk.set_defaults(func=cmd_backup)

    # import
    im = sub.add_parser("import", help="Upload a CSV (Readwise), JSON (Kindle), or HTML (Meebook) file.")
    im.add_argument("path", help="Path to the file to upload. Format detected by extension.")
    im.set_defaults(func=cmd_import)

    # books
    b = sub.add_parser("books", help="List books that have at least one highlight.")
    b.add_argument("--limit", type=int, default=20)
    b.set_defaults(func=cmd_books)

    # book-highlights
    bh = sub.add_parser("book-highlights", help="List highlights for one book.")
    bh.add_argument("book_id", type=int)
    bh.add_argument("--limit", type=int, default=50)
    bh.set_defaults(func=cmd_book_highlights)

    # authors
    au = sub.add_parser("authors", help="List authors with book + highlight counts.")
    au.add_argument("query", nargs="?", help="Optional substring filter on author name.")
    au.add_argument("--limit", type=int, default=50)
    au.set_defaults(func=cmd_authors)

    # note <id> "..." [--append]
    n = sub.add_parser("note", help="Set or append the note on a highlight.")
    n.add_argument("highlight_id", type=int)
    n.add_argument("note")
    n.add_argument("--append", action="store_true",
                   help="Append to the existing note instead of replacing it.")
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
