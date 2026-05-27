#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from image_factory.config import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_PROVIDER,
    DEFAULT_QUALITY,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SIZE,
)
from image_factory.io import write_json
from image_factory.repository import IntentRepository
from image_factory.providers import ApiDisabledError, ProviderUnsupportedError
from image_factory.references import refs_to_compressed_data_uris, select_reference_images
from image_factory.prompt_doc_runs import (
    build_prompt_plan,
    existing_image_paths,
    find_latest_prompt_html,
    generate_until_target,
    infer_output_naming,
    next_sequence_number,
    parse_prompt_doc_html,
    resolve_effective_size,
    resolve_prompt_source,
)
from image_factory.results import extension_for_format
from image_factory.task_queue import DEFAULT_QUEUE_DB, cancel_exhausted_tasks, cancel_stale_tasks, enqueue_tasks, init_db, queue_summary, queued_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read an embedded prompt HTML doc and generate images until the target count exists. "
            "By default this only writes a manifest; pass --execute --allow-api to enqueue tasks "
            "and run concurrent workers."
        )
    )
    parser.add_argument(
        "--html",
        nargs="+",
        required=True,
        help="Prompt doc HTML path(s). Multiple docs are enqueued together and processed by a single worker pool.",
    )
    parser.add_argument("--target-count", type=int, default=0, help="Required number of images. 0 = match document variant count (or 4 if no variants).")
    parser.add_argument("--output-dir", type=Path, help="Output directory. Defaults to outputs/prompt_docs/<prefix>.")
    parser.add_argument("--series", default="", help="Stable big-theme filename part, for example mygo.")
    parser.add_argument("--doc-date", default="", help="Filename date in YYYYMMDD format. Defaults to the doc date or today.")
    parser.add_argument("--topic", default="", help="Short small-topic filename part, for example outdoor_daily.")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Image generation provider. Currently supported: openai.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--size", default=DEFAULT_SIZE, help="Output image size. Default is 2160x3840.")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, help="Output image quality. Default is high.")
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help=(
            "Provider request timeout per API call. "
            "Use <=0 to disable the client timeout."
        ),
    )
    parser.add_argument(
        "--prompt-source",
        choices=("auto", "main", "variants"),
        default="auto",
        help=(
            "Which prompt blocks to send to the API. "
            "auto uses storyboard/variant prompts when present, otherwise the main prompt."
        ),
    )
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--manifest", type=Path, help="Manifest JSON path. Defaults to <output-dir>/manifest.json.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call the image generation API. Defaults to SQLite queue + concurrent workers.",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="With --execute, bypass the queue and use the legacy single-process direct path.",
    )
    parser.add_argument(
        "--fallback-to-plan-on-api-error",
        action="store_true",
        help=(
            "When retryable provider errors persist, write a fallback_planned manifest "
            "and exit without pretending images were generated."
        ),
    )
    parser.add_argument(
        "--allow-api",
        action="store_true",
        help="Required safety confirmation for real provider API calls.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Custom DALL-E compatible API base URL. "
            "Defaults to IMAGE_FACTORY_API_BASE_URL from .env, "
            "or the OpenAI default if neither is set."
        ),
    )
    parser.add_argument(
        "--aspect-ratio",
        default=None,
        help=f"Preferred aspect ratio (e.g. 16:9, 1:1, 3:4). Defaults to {DEFAULT_ASPECT_RATIO}.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing images in output directory and regenerate from scratch.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Explicitly resume an incomplete planned/partial run in the base output directory instead of starting a new run directory.",
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Parse the prompt doc and write tasks to the SQLite queue instead of generating images.",
    )
    parser.add_argument(
        "--queue-db",
        type=Path,
        default=None,
        help="SQLite queue database path. Defaults to outputs/task_queue.db.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=0,
        help="Limit concurrent queue workers when --execute uses the default queue path (0 = all keys).",
    )
    return parser.parse_args()


def resolve_html_path(value: str) -> Path:
    if value == "latest":
        import sys
        print(
            "[warning] --html latest is deprecated for production use. "
            "It picks the most recently modified *_embedded.html by filesystem timestamp, "
            "which may NOT match the current request. Pass an explicit --html path instead.\n"
            "  Available docs: ls prompts/docs/*_embedded.html",
            file=sys.stderr,
        )
        return find_latest_prompt_html(ROOT / "prompts" / "docs")
    return Path(value)


def resolve_output_dir(
    base_dir: Path,
    prefix: str,
    extension: str,
    *,
    force: bool = False,
    resume: bool = False,
    queue_db: Path | None = None,
) -> Path:
    if force or resume:
        return base_dir
    run = 1
    while True:
        candidate = base_dir if run == 1 else base_dir.with_name(f"{base_dir.name}_r{run}")
        has_disk_images = bool(existing_image_paths(candidate, prefix, extension))
        has_queue_tasks = bool(queued_paths(queue_db, str(candidate))) if queue_db else False
        if not has_disk_images and not has_queue_tasks:
            return candidate
        run += 1


def _run_enqueue(args: argparse.Namespace, html_path: Path) -> dict:
    """Parse a prompt doc and write its plan entries as pending tasks into the SQLite queue."""
    doc = parse_prompt_doc_html(html_path)
    resolved_source = resolve_prompt_source(doc, args.prompt_source)
    naming = infer_output_naming(
        html_path, doc.theme,
        series=args.series, date=args.doc_date, topic=args.topic,
    )
    effective_aspect_ratio = args.aspect_ratio or doc.aspect_ratio
    effective_size, _size_source = resolve_effective_size(args.size, effective_aspect_ratio)
    extension = extension_for_format(args.output_format)
    base_dir = (args.output_dir or ROOT / "outputs" / "prompt_docs" / naming.prefix).resolve()
    db_path = args.queue_db or DEFAULT_QUEUE_DB
    init_db(db_path)
    cancelled = cancel_stale_tasks(db_path, max_claimed_seconds=int(DEFAULT_REQUEST_TIMEOUT_SECONDS) * 3)
    if cancelled:
        print(f"[enqueue] auto-cancelled {cancelled} stale claimed task(s) "
              f"(>{int(DEFAULT_REQUEST_TIMEOUT_SECONDS) * 3}s)")
    exhausted = cancel_exhausted_tasks(db_path)
    if exhausted:
        print(f"[enqueue] permanently failed {exhausted} exhausted task(s)")
    output_dir = resolve_output_dir(
        base_dir,
        naming.prefix,
        extension,
        force=args.force,
        resume=args.resume,
        queue_db=db_path,
    )
    if output_dir != base_dir:
        print(f"[auto] using new run directory: {output_dir}")
    elif args.resume:
        print(f"[resume] continuing batch in {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve target_count=0 → match document variant count (fallback 4)
    if args.target_count <= 0:
        args.target_count = len(doc.variants) if doc.variants else 4

    # Dedup: merge disk files and queue entries to determine actual existing count
    disk_paths = set() if args.force else set(existing_image_paths(output_dir, naming.prefix, extension))
    queue_paths = {Path(p) for p in queued_paths(db_path, str(output_dir))}
    occupied = disk_paths | queue_paths
    existing_count = len(occupied)
    remaining = max(0, args.target_count - existing_count)

    if remaining <= 0:
        print(f"[enqueue] Target {args.target_count} already met "
              f"(disk={len(disk_paths)}, queue={len(queue_paths)}, union={existing_count}). Nothing to enqueue.")
        summary = queue_summary(db_path, str(output_dir))
        return {
            "count": 0,
            "db_path": db_path,
            "output_dir": output_dir,
            "summary": summary,
        }

    start = max(1, next_sequence_number(list(occupied), naming.prefix))
    plan = build_prompt_plan(
        doc, resolved_source, output_dir, naming.prefix, extension, start, remaining,
    )

    # size and aspect_ratio are mutually exclusive per DALL-E spec;
    # match the legacy generate_until_target behaviour
    enqueue_size = "" if effective_aspect_ratio else effective_size
    enqueue_aspect_ratio = effective_aspect_ratio if effective_aspect_ratio else ""

    refs_json = ""
    if doc.character:
        refs = select_reference_images(
            character=doc.character,
            specs_dir=ROOT / "specs",
            context=doc.theme,
        )
        if refs:
            ref_paths = [ref["path"] for ref in refs]
            refs_json = json.dumps(ref_paths)
            print(f"[refs] enqueued {len(ref_paths)} reference paths for {doc.character}")

    count = enqueue_tasks(
        db_path=db_path,
        plan_entries=plan,
        prompt_doc_path=str(html_path),
        theme=doc.theme,
        character=doc.character,
        model=args.model,
        provider=args.provider,
        size=enqueue_size,
        quality=args.quality,
        output_format=args.output_format,
        aspect_ratio=enqueue_aspect_ratio,
        base_url=args.base_url or "",
        enqueue_source=f"{naming.prefix}",
        reference_images=refs_json,
    )
    repo = IntentRepository(db_path)
    manifest = repo.manifest(str(output_dir))
    if manifest:
        manifest["available_variant_count"] = len(doc.variants) if doc.variants else manifest.get("available_variant_count", 0)
        write_json(output_dir / "manifest.json", manifest)

    summary = queue_summary(db_path, str(output_dir))
    print(f"[enqueue] {count} task(s) written to {db_path}")
    print(f"  Output dir:  {output_dir}")
    print(f"  Queue state: {summary['done']} done, {summary['pending']} pending, "
          f"{summary['claimed']} claimed, {summary['failed']} failed")
    print(f"  Run workers: python3 scripts/run_image_workers.py")
    return {
        "count": count,
        "db_path": db_path,
        "output_dir": output_dir,
        "summary": summary,
    }


def _run_concurrent_execute(args: argparse.Namespace, html_paths: list[Path]) -> None:
    """Enqueue prompt docs and immediately drain with worker concurrency.

    Multiple HTML docs are enqueued first, then a single worker pool processes
    all tasks together — achieving cross-batch pipelining.

    When the API is not available (ApiDisabledError), automatically falls back to
    writing a planned manifest so the caller always gets a usable result.
    """
    from image_factory.providers.openai import assert_api_enabled

    try:
        assert_api_enabled(allow_api=args.allow_api)
    except ApiDisabledError:
        print("[fallback] API not available, writing planned manifest instead")
        for hp in html_paths:
            _plan_only(args, hp)
        raise SystemExit(
            "API is disabled. A planned manifest has been written. "
            "Configure IMAGE_FACTORY_API_ENABLED=1 and API keys in .env to enable execution."
        )

    results = []
    for html_path in html_paths:
        result = _run_enqueue(args, html_path)
        results.append(result)

    total_enqueued = sum(r["count"] for r in results)
    if total_enqueued == 0:
        print("[pipeline] all tasks already satisfied, nothing to process")
        return

    # Use the shared queue db from the first result; all docs enqueue to the same db
    db_path = results[0]["db_path"]
    from run_image_workers import run_workers

    worker_result = run_workers(
        queue_db=db_path,
        max_workers=args.max_workers,
        base_url=args.base_url,
    )
    if worker_result.get("error"):
        raise SystemExit(worker_result["error"])


def _plan_only(args: argparse.Namespace, html_path: Path) -> None:
    """Write a planned manifest without calling any image generation API."""
    manifest = generate_until_target(
        html_path,
        target_count=args.target_count,
        output_dir=args.output_dir,
        series=args.series,
        date=args.doc_date,
        topic=args.topic,
        provider=args.provider,
        model=args.model,
        size=args.size,
        quality=args.quality,
        output_format=args.output_format,
        max_attempts=args.max_attempts,
        execute=False,
        allow_api=False,
        manifest_path=args.manifest,
        base_url=args.base_url,
        aspect_ratio=args.aspect_ratio,
        force=args.force,
        resume=args.resume,
        prompt_source="auto",
        request_timeout_seconds=args.request_timeout_seconds if args.request_timeout_seconds > 0 else None,
        fallback_to_plan_on_api_error=False,
    )
    print(f"Prompt doc: {manifest['prompt_doc']}")
    print(f"Theme: {manifest['theme']}")
    print(f"Output dir: {manifest['output_dir']}")
    print(f"File prefix: {manifest['file_prefix']}")
    print(f"Size: {manifest['size']} ({manifest.get('size_source', 'requested_size')})")
    print(f"Status: {manifest['status']}")
    print(f"Existing/target: {manifest['existing_count']}/{manifest['target_count']}")
    print(f"Manifest: {manifest['manifest_path']}")
    if manifest.get("planned_paths"):
        print("Planned paths:")
        prompt_plan = {item["path"]: item for item in manifest.get("prompt_plan", [])}
        for path in manifest["planned_paths"]:
            item = prompt_plan.get(path, {})
            suffix = f" [{item.get('prompt_title')}]" if item else ""
            print(f"- {path}{suffix}")


def main() -> None:
    args = parse_args()
    html_paths = [resolve_html_path(h) for h in args.html]

    if args.enqueue:
        for html_path in html_paths:
            _run_enqueue(args, html_path)
        return

    if args.execute and not args.direct:
        if args.manifest:
            raise SystemExit("--manifest is only supported with --direct; queued runs write <output-dir>/manifest.json")
        try:
            _run_concurrent_execute(args, html_paths)
        except ProviderUnsupportedError as exc:
            raise SystemExit(str(exc)) from exc
        return

    # Legacy --direct path: single HTML doc only
    html_path = html_paths[0]
    image_urls: list[str] | None = None
    if args.execute:
        doc = parse_prompt_doc_html(html_path)
        if doc.character:
            refs = select_reference_images(
                character=doc.character,
                specs_dir=ROOT / "specs",
                context=doc.theme,
            )
            if refs:
                image_urls = refs_to_compressed_data_uris(refs)
                print(f"[refs] resolved {len(image_urls)} reference image(s) for {doc.character}")

    try:
        manifest = generate_until_target(
            html_path,
            target_count=args.target_count,
            output_dir=args.output_dir,
            series=args.series,
            date=args.doc_date,
            topic=args.topic,
            provider=args.provider,
            model=args.model,
            size=args.size,
            quality=args.quality,
            output_format=args.output_format,
            max_attempts=args.max_attempts,
            execute=args.execute,
            allow_api=args.allow_api,
            manifest_path=args.manifest,
            base_url=args.base_url,
            aspect_ratio=args.aspect_ratio,
            image_urls=image_urls,
            force=args.force,
            resume=args.resume,
            prompt_source=args.prompt_source,
            request_timeout_seconds=args.request_timeout_seconds if args.request_timeout_seconds > 0 else None,
            fallback_to_plan_on_api_error=args.fallback_to_plan_on_api_error,
        )
    except (ApiDisabledError, ProviderUnsupportedError) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Prompt doc: {manifest['prompt_doc']}")
    print(f"Theme: {manifest['theme']}")
    print(f"Output dir: {manifest['output_dir']}")
    print(f"File prefix: {manifest['file_prefix']}")
    print(f"Prompt source: {manifest['prompt_source']} ({manifest['available_variant_count']} variants available)")
    print(f"Size: {manifest['size']} ({manifest.get('size_source', 'requested_size')})")
    print(f"Status: {manifest['status']}")
    print(f"Existing/target: {manifest['existing_count']}/{manifest['target_count']}")
    print(f"Manifest: {manifest['manifest_path']}")
    if manifest.get("planned_paths"):
        print("Planned paths:")
        prompt_plan = {item["path"]: item for item in manifest.get("prompt_plan", [])}
        for path in manifest["planned_paths"]:
            item = prompt_plan.get(path, {})
            suffix = f" [{item.get('prompt_title')}]" if item else ""
            print(f"- {path}{suffix}")
    if manifest.get("generated"):
        print("Generated paths:")
        for item in manifest["generated"]:
            print(f"- {item['path']}")
    if manifest.get("fallback_reason"):
        print(f"Fallback reason: {manifest['fallback_reason']}")

    if args.execute and manifest["status"] != "complete" and not (
        args.fallback_to_plan_on_api_error and manifest["status"] == "fallback_planned"
    ):
        raise SystemExit(
            f"Generated set is incomplete after {manifest['max_attempts']} attempts: "
            f"{manifest['existing_count']}/{manifest['target_count']}"
        )


if __name__ == "__main__":
    main()
