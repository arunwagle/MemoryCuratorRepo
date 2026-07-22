"""Command line entry points for MemoryCurator."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from memory_curator_engine.common.config import load_config
from memory_curator_engine.common.phase_runner import run_placeholder_phase
from memory_curator_engine.common.phases import PHASES, PHASES_BY_COMMAND
from memory_curator_engine.common.reset import run_reset
from memory_curator_engine.albums.report import run_album_builder
from memory_curator_engine.dedupe.report import run_duplicate_detection, run_keeper_manifest
from memory_curator_engine.documentary.report import run_documentary_builder
from memory_curator_engine.inventory.report import inventory_from_config, run_inventory_jobs
from memory_curator_engine.reels.report import REEL_VARIANTS, run_ranked_reels_by_activity, run_reel_builder, run_selected_timeline_fun_reel
from memory_curator_engine.scoring.report import run_quality_scoring
from memory_curator_engine.selected_timeline.report import run_selected_timeline
from memory_curator_engine.story.report import run_story_builder
from memory_curator_engine.video.report import run_video_processing


SKIP_HELP = "Skip a phase during run-all. Accepts command, config key, phase number, or comma-separated values."

PROMPT_FILES = [
    ("duplicate-detection", "prompts/duplicate_detection_phase_1.md", "Duplicate groups, review queue, keeper manifest"),
    ("quality-scoring", "prompts/quality_scoring_phase.md", "Purpose-specific media scores and quality manifest"),
    ("story-builder", "prompts/story_builder_phase.md", "Activity moments and story manifest"),
    ("album-builder", "prompts/album_builder_phase.md", "Album selection and PDF export design"),
    ("video-processing", "prompts/video_processing_engine_phase.md", "Scenes, clips, frames, audio, transcript, timeline"),
    ("selected-timeline", "prompts/selected_timeline_phase.md", "Master activity timeline selection"),
    ("reel-builder", "prompts/reel_builder_phase.md", "Instagram/highlight reel edit decisions"),
    ("documentary-builder", "prompts/documentary_builder_phase.md", "Long-form story and documentary plan"),
]


def add_include_disabled(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Run this phase even when its module is disabled in config.",
    )


def apply_reel_set_filter(config: dict, sets: list[str] | None) -> dict:
    if not sets:
        return config
    filtered = [item.strip() for item in sets if item.strip()]
    if not filtered:
        return config
    reel_builder = config.setdefault("reel_builder", {})
    if not isinstance(reel_builder, dict):
        raise ValueError("reel_builder config must be a mapping to use --set.")
    reel_builder["media_sets"] = filtered
    return config


def apply_selected_timeline_set_filter(config: dict, sets: list[str] | None) -> dict:
    if not sets:
        return config
    filtered = [item.strip() for item in sets if item.strip()]
    if not filtered:
        return config
    selected_timeline = config.setdefault("selected_timeline", {})
    if not isinstance(selected_timeline, dict):
        raise ValueError("selected_timeline config must be a mapping to use --set.")
    selected_timeline["media_sets"] = filtered
    reel_builder = config.setdefault("reel_builder", {})
    if isinstance(reel_builder, dict):
        reel_builder["media_sets"] = filtered
    return config


def apply_run_all_set_filter(config: dict, sets: list[str] | None) -> dict:
    if not sets:
        return config
    filtered = [item.strip() for item in sets if item.strip()]
    if not filtered:
        return config
    media_sets = config.setdefault("inventory", {}).setdefault("media_sets", {})
    if not isinstance(media_sets, dict):
        raise ValueError("inventory.media_sets must be a mapping to use run-all --set.")
    unknown = sorted(set(filtered) - set(media_sets))
    if unknown:
        raise ValueError(f"Unknown media set(s) for run-all --set: {', '.join(unknown)}")
    selected = set(filtered)
    for name, values in media_sets.items():
        if not isinstance(values, dict):
            continue
        values["enabled"] = "yes" if name in selected else "no"
    selected_timeline = config.setdefault("selected_timeline", {})
    if isinstance(selected_timeline, dict):
        selected_timeline["media_sets"] = filtered
    reel_builder = config.setdefault("reel_builder", {})
    if isinstance(reel_builder, dict):
        reel_builder["media_sets"] = filtered
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Curate and inventory trip media.")
    parser.add_argument(
        "--config",
        default="input_data/trips/sample/config/default.yaml",
        help="Trip YAML configuration file. Default: input_data/trips/sample/config/default.yaml",
    )

    subparsers = parser.add_subparsers(dest="command")
    prompt_parser = subparsers.add_parser("prompt-guide", help="List phase prompts for prompt-only usage.")
    prompt_parser.add_argument("--phase", help="Show one phase prompt path by command name, for example reel-builder.")

    inventory_parser = subparsers.add_parser("inventory", help="Create a CSV media inventory.")
    inventory_parser.add_argument("--input", help="Override the configured inventory input folder.")
    inventory_parser.add_argument("--output", help="Override the configured inventory CSV path.")
    inventory_parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        help="Run one named inventory media set from config. Can be passed more than once.",
    )
    add_include_disabled(inventory_parser)

    reset_parser = subparsers.add_parser("reset", help="Preview or execute a project reset to the configured start state.")
    reset_parser.add_argument(
        "--execute",
        action="store_true",
        help="Restore moved media and remove known generated workflow outputs. Preview is the default.",
    )

    run_all_parser = subparsers.add_parser("run-all", help="Run enabled phases in workflow order.")
    run_all_parser.add_argument("--execute", action="store_true", help="Finalize phases that support dry-run review.")
    run_all_parser.add_argument("--skip", action="append", default=[], help=SKIP_HELP)
    run_all_parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        help="Run one named media set/activity through the workflow. Can be passed more than once.",
    )
    add_include_disabled(run_all_parser)

    for phase in PHASES:
        if phase.command == "inventory":
            continue
        phase_parser = subparsers.add_parser(phase.command, help=f"Run phase {phase.number:02d}: {phase.title}.")
        add_include_disabled(phase_parser)
        if phase.command == "duplicate-detection":
            phase_parser.add_argument(
                "--execute",
                action="store_true",
                help="Finalize duplicate reports and keeper_manifest.csv. No media files are moved.",
            )
            phase_parser.add_argument(
                "--manifest-only",
                action="store_true",
                help="Refresh keeper_manifest.csv from the current keep folders without rewriting duplicate audit reports.",
            )
        if phase.command == "quality-scoring":
            phase_parser.add_argument(
                "--execute",
                action="store_true",
                help="Finalize quality reports and quality_manifest.csv. No media files are moved.",
            )
        if phase.command == "story-builder":
            phase_parser.add_argument("--execute", action="store_true", help="Finalize Story Builder reports and manifests. No media files are moved.")
            phase_parser.add_argument("--ai", action="store_true", help="Use optional OpenAI classification after Python moment grouping.")
            phase_parser.add_argument("--no-ai", action="store_true", help="Force Python-only moment classification.")
        if phase.command == "album-builder":
            phase_parser.add_argument("--execute", action="store_true", help="Generate configured album PDFs. Dry run writes reports only.")
        if phase.command == "video-processing":
            phase_parser.add_argument("--execute", action="store_true", help="Generate configured video artifacts. Dry run writes metadata only.")
            phase_parser.add_argument(
                "--stage",
                choices=[
                    "all",
                    "scene-detection",
                    "clip-segmentation",
                    "clip-scoring",
                    "frame-analysis",
                    "audio-analysis",
                    "transcript",
                    "timeline-builder",
                ],
                default="all",
                help="Run one internal video-processing stage. Default: all.",
            )
        if phase.command == "selected-timeline":
            phase_parser.add_argument("--execute", action="store_true", help="Render master activity timeline videos. Dry run writes plans only.")
            phase_parser.add_argument(
                "--set",
                dest="sets",
                action="append",
                help="Run one named activity from config. Can be passed more than once.",
            )
        if phase.command == "reel-builder":
            phase_parser.add_argument("--execute", action="store_true", help="Render configured reels when rendering is enabled. Dry run writes plans only.")
            phase_parser.add_argument(
                "--set",
                dest="sets",
                action="append",
                help="Run one named reel media set/activity from config. Can be passed more than once.",
            )
            phase_parser.add_argument("--reel-id", help="Override the configured reel id.")
            phase_parser.add_argument("--style", help="Override the configured reel style.")
            phase_parser.add_argument(
                "--variant",
                default=None,
                help=f"Render one variant or all. Choices: all, {', '.join(REEL_VARIANTS)}.",
            )
        if phase.command == "documentary-builder":
            phase_parser.add_argument("--execute", action="store_true", help="Finalize documentary story plans and render the documentary when rendering is enabled.")

    return parser


def phase_skip_tokens(skip_values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in skip_values:
        for token in value.split(","):
            normalized = token.strip().lower()
            if normalized:
                tokens.add(normalized)
    return tokens


def phase_is_skipped(phase_command: str, skip_tokens: set[str]) -> bool:
    phase = PHASES_BY_COMMAND[phase_command]
    return bool(
        {
            phase.command,
            phase.config_key,
            str(phase.number),
            f"{phase.number:02d}",
        }
        & skip_tokens
    )


def print_duplicate_result(result: object) -> None:
    print(
        "[duplicate-detection] "
        f"scanned {result.scanned_count} duplicate-candidate files; "
        f"found {result.duplicate_group_count} groups and {result.duplicate_file_count} duplicate files."
    )
    print(f"[duplicate-detection] wrote {result.duplicate_groups_csv}")
    print(f"[duplicate-detection] wrote {result.duplicates_to_review_csv}")
    print(f"[duplicate-detection] wrote {result.keeper_manifest_csv}")
    if result.dry_run:
        print("[duplicate-detection] dry run: no files were moved.")
    else:
        print("[duplicate-detection] finalized reports and keeper_manifest.csv; no media files were moved.")


def print_quality_result(result: object) -> None:
    print(
        "[quality-scoring] "
        f"scanned {result.scanned_count} media files; "
        f"selected {result.selected_count} high-quality files."
    )
    print(f"[quality-scoring] wrote {result.quality_scores_csv}")
    print(f"[quality-scoring] wrote {result.quality_selection_csv}")
    print(f"[quality-scoring] wrote {result.quality_manifest_csv}")
    if result.dry_run:
        print("[quality-scoring] dry run: no files were moved.")
    else:
        print("[quality-scoring] finalized reports and quality_manifest.csv; no media files were moved.")


def print_story_result(result: object) -> None:
    print(
        "[story-builder] "
        f"grouped {result.asset_count} assets into {result.moment_count} moments; "
        f"AI classification: {'on' if result.ai_enabled else 'off'}."
    )
    print(f"[story-builder] wrote {result.moments_csv}")
    print(f"[story-builder] wrote {result.moments_json}")
    print(f"[story-builder] wrote {result.moment_assets_csv}")
    print(f"[story-builder] wrote {result.story_manifest_csv}")
    print(f"[story-builder] wrote {result.story_review_csv}")
    if result.dry_run:
        print("[story-builder] dry run: reports were refreshed and no files were moved.")
    else:
        print("[story-builder] finalized Story Builder reports and manifests; no media files were moved.")


def print_album_result(result: object) -> None:
    variant_counts = getattr(result, "variant_counts", {})
    selected_summary = ", ".join(f"{name}={count}" for name, count in variant_counts.items())
    if not selected_summary:
        selected_summary = (
            f"small={result.small_count}, standard={result.standard_count}, "
            f"extended={result.extended_count}, enhanced={result.enhanced_count}"
        )
    print(
        "[album-builder] "
        f"scored {result.candidate_count} photo candidates; "
        f"selected {selected_summary}."
    )
    print(f"[album-builder] wrote {result.album_candidates_csv}")
    print(f"[album-builder] wrote {result.album_selection_csv}")
    print(f"[album-builder] wrote {result.album_manifest_csv}")
    print(f"[album-builder] wrote {result.album_report_md}")
    if result.dry_run:
        print("[album-builder] dry run: no PDFs were generated and no photos were copied.")
    else:
        print(f"[album-builder] generated {result.generated_pdf_count} album PDFs; no selected photos were copied.")


def print_video_result(result: object) -> None:
    print(
        "[video-processing] "
        f"processed {result.video_count} videos; "
        f"scenes={result.scene_count}, clips={result.clip_count}, scored_clips={result.scored_clip_count}, "
        f"frames={result.frame_count}, audio_events={result.audio_event_count}, "
        f"transcript_segments={result.transcript_segment_count}, timeline_events={result.timeline_event_count}."
    )
    print(f"[video-processing] stages: {', '.join(result.stages)}")
    print(f"[video-processing] wrote {result.manifest_csv}")
    if result.dry_run:
        print("[video-processing] dry run: no generated media artifacts were created.")
    else:
        print(f"[video-processing] generated {result.generated_media_count} media artifacts.")


def print_reel_result(result: object) -> None:
    print(
        "[reel-builder] "
        f"scored {result.candidate_count} candidate segments; "
        f"selected {result.selected_count} clips for {result.actual_duration_seconds:.1f}s."
    )
    print(f"[reel-builder] wrote {result.reel_candidates_csv}")
    print(f"[reel-builder] wrote {result.reel_selection_csv}")
    print(f"[reel-builder] wrote {result.reel_edit_decisions_csv}")
    print(f"[reel-builder] wrote {result.reel_manifest_csv}")
    print(f"[reel-builder] wrote {result.reel_report_md}")
    if result.dry_run:
        print("[reel-builder] dry run: reel video was not rendered.")
    else:
        print(f"[reel-builder] render status: {result.render_status}; output: {result.rendered_file_path}")


def print_selected_timeline_result(result: object) -> None:
    print(
        "[selected-timeline] "
        f"{result.activity}: scored {result.candidate_count} candidate windows; "
        f"selected {result.selected_count} timeline segments for {result.actual_duration_seconds / 60:.1f} minutes."
    )
    print(f"[selected-timeline] wrote {result.candidates_csv}")
    print(f"[selected-timeline] wrote {result.selected_timeline_csv}")
    print(f"[selected-timeline] wrote {result.edit_decisions_csv}")
    print(f"[selected-timeline] wrote {result.manifest_csv}")
    print(f"[selected-timeline] wrote {result.report_md}")
    print(f"[selected-timeline] cache: {result.cache_entries} segment audits at {result.cache_file}")
    if result.dry_run:
        print("[selected-timeline] dry run: master activity video was not rendered.")
    else:
        print(f"[selected-timeline] render status: {result.render_status}; output: {result.rendered_file_path}")


def print_documentary_result(result: object) -> None:
    print(
        "[documentary-builder] "
        f"planned {result.chapter_count} chapters, {result.story_beat_count} story beats, "
        f"and {result.timeline_event_count} timeline events for {result.actual_duration_seconds / 60:.1f} minutes."
    )
    print(f"[documentary-builder] wrote {result.documentary_story_csv}")
    print(f"[documentary-builder] wrote {result.documentary_chapters_csv}")
    print(f"[documentary-builder] wrote {result.documentary_timeline_csv}")
    print(f"[documentary-builder] wrote {result.documentary_manifest_csv}")
    print(f"[documentary-builder] wrote {result.documentary_treatment_md}")
    if result.dry_run:
        print("[documentary-builder] dry run: planning reports were refreshed and no media was rendered.")
    else:
        print(
            "[documentary-builder] "
            f"render status: {result.render_status}; segments: {result.rendered_segment_count}; "
            f"output: {result.rendered_file_path}; {result.render_message}"
        )


def run_prompt_guide(args: argparse.Namespace, project_root: Path, parser: argparse.ArgumentParser) -> int:
    phase_filter = args.phase.strip().lower() if args.phase else None
    rows = [row for row in PROMPT_FILES if not phase_filter or row[0] == phase_filter]
    if phase_filter and not rows:
        choices = ", ".join(row[0] for row in PROMPT_FILES)
        parser.error(f"Unknown prompt phase: {phase_filter}. Choices: {choices}")

    print("MemoryCurator prompt-only workflow")
    print("Use these prompts with Codex, ChatGPT, or another coding agent when you want the design without running the Python engine.")
    print()
    for command, prompt_path, purpose in rows:
        exists = "yes" if (project_root / prompt_path).exists() else "missing"
        print(f"- {command}: {prompt_path} [{exists}]")
        print(f"  {purpose}")
    print()
    print("Guide: docs/PROMPT_ONLY_WORKFLOW.md")
    return 0


def run_inventory_command(args: argparse.Namespace, config: dict, project_root: Path, parser: argparse.ArgumentParser) -> int:
    if args.input or args.output:
        count, output_csv = inventory_from_config(
            config=config,
            project_root=project_root,
            input_override=args.input,
            output_override=args.output,
        )
        print(f"Wrote {count} media rows to {output_csv}")
        return 0

    try:
        results = run_inventory_jobs(
            config=config,
            project_root=project_root,
            only_names=set(args.sets) if args.sets else None,
            include_disabled=args.include_disabled,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    if not results:
        print("No enabled inventory media sets to run.")
        return 0
    for result in results:
        print(f"[{result.name}] Wrote {result.count} media rows to {result.output_csv}")
    return 0


def run_all_command(args: argparse.Namespace, config: dict, project_root: Path, parser: argparse.ArgumentParser) -> int:
    try:
        config = apply_run_all_set_filter(config, args.sets)
    except ValueError as exc:
        parser.error(str(exc))
    skip_tokens = phase_skip_tokens(args.skip)

    for phase in PHASES:
        if phase_is_skipped(phase.command, skip_tokens):
            print(f"[run-all] skipped phase {phase.number:02d}: {phase.title} ({phase.command})")
            continue

        if phase.command == "inventory":
            inventory_args = argparse.Namespace(input=None, output=None, sets=args.sets, include_disabled=args.include_disabled)
            run_inventory_command(args=inventory_args, config=config, project_root=project_root, parser=parser)
            continue

        if phase.command == "duplicate-detection":
            result = run_duplicate_detection(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            print_duplicate_result(result)
            continue

        if phase.command == "quality-scoring":
            result = run_quality_scoring(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            print_quality_result(result)
            continue

        if phase.command == "story-builder":
            result = run_story_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                no_ai=False,
                force_ai=False,
                execute=args.execute,
            )
            print_story_result(result)
            continue

        if phase.command == "album-builder":
            result = run_album_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            print_album_result(result)
            continue

        if phase.command == "video-processing":
            result = run_video_processing(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
                stage="all",
            )
            print_video_result(result)
            continue

        if phase.command == "selected-timeline":
            results = run_selected_timeline(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            for result in results:
                print_selected_timeline_result(result)
            continue

        if phase.command == "reel-builder":
            results = run_ranked_reels_by_activity(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            for result in results:
                print_reel_result(result)
            continue

        if phase.command == "documentary-builder":
            result = run_documentary_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
            print_documentary_result(result)
            continue

        _, message = run_placeholder_phase(
            config=config,
            project_root=project_root,
            phase=phase,
            include_disabled=args.include_disabled,
        )
        print(message)

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    command = args.command or "inventory"
    project_root = Path.cwd().resolve()

    if command == "prompt-guide":
        return run_prompt_guide(args=args, project_root=project_root, parser=parser)

    config = load_config(project_root / args.config)

    if command == "inventory":
        return run_inventory_command(args=args, config=config, project_root=project_root, parser=parser)

    if command == "run-all":
        try:
            return run_all_command(args=args, config=config, project_root=project_root, parser=parser)
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))

    if command == "reset":
        try:
            result = run_reset(config=config, project_root=project_root, execute=args.execute)
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print(
            "[reset] "
            f"reversible moved files found: {result.review_file_count}; "
            f"restorable: {result.restorable_count}; "
            f"blocked: {result.blocked_count}."
        )
        print(
            "[reset] "
            f"workflow cleanup files found: {result.generated_file_count}; "
            f"generated roots: {', '.join(str(root) for root in result.generated_roots)}"
        )
        if result.dry_run:
            print("[reset] dry run: no files were moved or removed. Re-run with --execute to reset.")
        else:
            print(
                "[reset] "
                f"restored {result.restored_count} media files and removed "
                f"{result.removed_generated_file_count} generated files."
            )
        return 0

    if command == "duplicate-detection":
        if args.manifest_only:
            try:
                result = run_keeper_manifest(
                    config=config,
                    project_root=project_root,
                    include_disabled=args.include_disabled,
                )
            except (FileNotFoundError, ValueError) as exc:
                parser.error(str(exc))
            print(f"[duplicate-detection] scanned {result.scanned_count} keeper files.")
            print(f"[duplicate-detection] wrote {result.keeper_manifest_csv}")
            return 0

        try:
            result = run_duplicate_detection(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            parser.error(str(exc))
        print_duplicate_result(result)
        return 0

    if command == "quality-scoring":
        try:
            result = run_quality_scoring(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_quality_result(result)
        return 0

    if command == "story-builder":
        if args.ai and args.no_ai:
            parser.error("Use either --ai or --no-ai, not both.")
        try:
            result = run_story_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                no_ai=args.no_ai,
                force_ai=args.ai,
                execute=args.execute,
            )
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_story_result(result)
        return 0

    if command == "album-builder":
        try:
            result = run_album_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_album_result(result)
        return 0

    if command == "video-processing":
        try:
            result = run_video_processing(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
                stage=args.stage,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_video_result(result)
        return 0

    if command == "reel-builder":
        try:
            config = apply_reel_set_filter(config, args.sets)
            if args.variant and args.variant.strip().lower().replace("-", "_") == "selected_timeline_fun":
                result = run_selected_timeline_fun_reel(
                    config=config,
                    project_root=project_root,
                    include_disabled=args.include_disabled,
                    execute=args.execute,
                    reel_id=args.reel_id,
                )
                print_reel_result(result)
                return 0
            if args.variant and args.variant.strip().lower() == "all":
                for variant in REEL_VARIANTS:
                    result = run_reel_builder(
                        config=config,
                        project_root=project_root,
                        include_disabled=args.include_disabled,
                        execute=args.execute,
                        reel_id=args.reel_id,
                        style=args.style,
                        variant=variant,
                    )
                    print_reel_result(result)
                return 0
            if not args.variant and not args.reel_id and not args.style:
                results = run_ranked_reels_by_activity(
                    config=config,
                    project_root=project_root,
                    include_disabled=args.include_disabled,
                    execute=args.execute,
                )
                for result in results:
                    print_reel_result(result)
                return 0
            result = run_reel_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
                reel_id=args.reel_id,
                style=args.style,
                variant=args.variant,
            )
        except (subprocess.CalledProcessError, FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_reel_result(result)
        return 0

    if command == "selected-timeline":
        try:
            config = apply_selected_timeline_set_filter(config, args.sets)
            results = run_selected_timeline(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
        except (subprocess.CalledProcessError, FileExistsError, FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        for result in results:
            print_selected_timeline_result(result)
        return 0

    if command == "documentary-builder":
        try:
            result = run_documentary_builder(
                config=config,
                project_root=project_root,
                include_disabled=args.include_disabled,
                execute=args.execute,
            )
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
        print_documentary_result(result)
        return 0

    if command in PHASES_BY_COMMAND:
        _, message = run_placeholder_phase(
            config=config,
            project_root=project_root,
            phase=PHASES_BY_COMMAND[command],
            include_disabled=args.include_disabled,
        )
        print(message)
        return 0

    parser.error(f"Unknown command: {command}")
    return 2
