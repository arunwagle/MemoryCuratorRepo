# Quality Scoring Phase Prompt

Design and implement the Quality Scoring phase for the MemoryCurator project.

Do not implement AI-based aesthetic judgment yet. This phase should use deterministic, explainable media-quality signals first, while keeping extension points for future AI scoring modules.

## Context

- This is a generic media curation engine.
- Trip-specific config lives under folders such as `input_data/trips/sample/config/default.yaml`.
- Source media lives under folders such as `input_data/trips/sample/data/rafting`.
- Workflow outputs go under the configured `MemoryCurator/` workflow root.
- Duplicate Detection produces a downstream keep set at:

```text
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

- Quality Scoring should consume the keeper manifest when it exists.
- If the keeper manifest is missing, Quality Scoring must fail with a clear error that tells the user to run the previous phases first.
- Each phase should create a manifest file for the next phase. Do not silently rescan earlier source folders as a fallback.
- Original source media must never be deleted.
- Dry run must not move, delete, rename, or edit source media.
- Execute mode must not move, delete, rename, or edit source media.
- Project-level reset must clean generated workflow outputs. It should also restore legacy reversible moves from older runs if those folders exist.

## Phase Goal

Quality Scoring should identify the strongest photos and videos from the duplicate-cleaned keep set. The selected media must be useful for:

- High-quality photo albums
- Instagram posts, stories, and reels
- Longer 30-60 minute documentary-style trip movies

The phase should:

- Read media from `keeper_manifest.csv`.
- Fail fast if `keeper_manifest.csv` is missing or empty.
- Score photos and videos using deterministic quality metrics.
- Produce purpose-specific suitability scores for albums, Instagram/reels, movie/documentary use, time capsule use, and activity fit.
- Use the configured Activity Profile, such as `rafting`, to preserve technically imperfect but activity-important videos.
- Generate reviewable CSV reports in dry-run mode.
- Select purpose-qualified photos and videos before applying top-percent quota fill.
- In execute mode, finalize CSV reports and manifests only.
- Preserve original relative paths in reports so downstream phases can read media from `input_data`.
- Generate a downstream `quality_manifest.csv` for later phases such as scene detection, album building, reels, and documentary building.
- Support a configurable `preserve_all_videos: yes` mode. When enabled, all duplicate-cleaned videos remain in `quality_manifest.csv` so Video Processing and Selected Timeline can make the finer-grained scene/window decision later. This is useful for trips with many short phone, WhatsApp, GoPro, or tour-company clips where technical quality alone can remove emotionally important source material too early.

For rafting, videos with action, water, rapids, splash, GoPro/POV feel, or strong motion should remain available for downstream phases even if they are shaky or less polished than static clips.

## Commands

Dry run is the default:

```bash
.venv/bin/python -B -m memory_curator_engine quality-scoring
```

Execute mode:

```bash
.venv/bin/python -B -m memory_curator_engine quality-scoring --execute
```

The existing project-level reset command must clean generated phase outputs:

```bash
.venv/bin/python -B -m memory_curator_engine reset --execute
```

## Inputs

Required input:

```text
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

If this file is missing, the command must stop with an error similar to:

```text
Missing upstream manifest: MemoryCurator/02 Duplicate Detection/keeper_manifest.csv.
Run inventory and duplicate-detection first.
```

Each row should provide:

- media_set
- keeper_path
- file_type
- size_bytes
- capture_date
- capture_date_source
- created_date
- modified_date
- width
- height
- duration_seconds

## Outputs

Write reports to:

```text
MemoryCurator/03 Quality Scoring/quality_scores.csv
MemoryCurator/03 Quality Scoring/quality_selection.csv
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

Execute mode should write metadata only. `quality_manifest.csv` should point at the original `input_data` media path.

## Report Columns

`quality_scores.csv` should include every scored input:

- media_set
- original_path
- selected_path
- file_type
- size_bytes
- width
- height
- duration_seconds
- quality_score
- album_score
- instagram_score
- movie_score
- technical_score
- sharpness_score
- exposure_score
- resolution_score
- stability_score
- video_motion_score
- selection_status: selected or not_selected
- selection_reason
- scoring_notes

`quality_selection.csv` should include only selected high-quality media:

- media_set
- original_path
- selected_path
- file_type
- quality_score
- album_score
- instagram_score
- movie_score
- selection_reason

`quality_manifest.csv` is the downstream contract and should include only selected high-quality media:

- media_set
- media_path
- original_path
- file_type
- size_bytes
- width
- height
- duration_seconds
- quality_score
- album_score
- instagram_score
- movie_score
- recommended_uses
- source_phase

In dry run and execute mode, `media_path` should be the original `input_data` path.

## Scoring Signals

Use standard libraries where possible, plus already approved optional media libraries when available.

Photo scoring should consider:

- Resolution: prefer enough pixels for albums and cropping.
- Sharpness: use variance of Laplacian or another explainable edge/detail metric when OpenCV is available.
- Exposure: penalize very dark, very bright, or clipped images.
- Contrast: prefer images with useful tonal variation.
- Orientation and aspect ratio: tag suitability for album spreads, square/social crops, vertical stories, or wide video backgrounds.
- Burst usefulness: avoid over-selecting many nearly identical moments after duplicate detection.
- File integrity: penalize unreadable or metadata-poor files.

Video scoring should consider:

- Resolution: prefer 1080p or better when available.
- Duration: reject extremely short accidental clips unless config allows them.
- Sharpness: sample frames and estimate detail.
- Exposure: sample frames and estimate brightness/clipping.
- Stability: penalize excessive frame-to-frame shake when measurable.
- Motion usefulness: prefer clips with meaningful motion, but avoid chaotic blur.
- Composition utility: tag whether the clip is likely useful as establishing footage, action footage, transition/B-roll, or social reel material using deterministic signals only.
- File integrity: penalize unreadable files.

The first implementation should avoid subjective AI concepts like beauty, faces, smiles, landmarks, or emotion. Those belong in later AI-assisted phases.

Purpose-specific scoring:

- `album_score`: prioritize high-resolution, sharp, well-exposed photos; include a smaller number of strong still frames or thumbnails from videos only if future implementation supports extraction.
- `instagram_score`: prioritize visually crisp media, vertical or square-friendly assets, short energetic videos, and photos that can crop well.
- `movie_score`: prioritize videos with usable duration, stable framing, good exposure, good sharpness, and enough variety for a 30-60 minute documentary-style edit; also allow top still photos as possible montage material.

## Selection Rules

Selection must be configurable.

Recommended default behavior:

- Select items above a minimum quality score.
- Also allow top-percent selection per media set.
- Use the `activity_profile` configured on each `inventory.media_sets.<name>` entry wherever available.
- Write aggregate downstream CSVs plus per-activity review copies under `MemoryCurator/03 Quality Scoring/<media_set>/`.
- Keep separate thresholds for photos and videos.
- Keep separate minimum suitability thresholds for album, Instagram, and movie use.
- Allow minimum and maximum counts per media set.
- Avoid selecting too many files from the same minute or visually similar burst when enough alternatives exist.
- Preserve enough media volume for a 30-60 minute movie, especially videos and strong B-roll.
- Always produce deterministic results with stable path ordering as a tie-breaker.

Example config:

```yaml
modules:
  quality_scoring:
    enabled: yes

quality_scoring:
  dry_run: yes
  activity_profile: default
  input_manifest: MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
  output_dir: MemoryCurator/03 Quality Scoring
  photo_min_score: 65
  video_min_score: 60
  album_min_score: 70
  instagram_min_score: 68
  movie_min_score: 62
  top_percent_per_media_set: 40
  min_selected_per_media_set: 20
  max_selected_per_media_set: 250
  min_video_duration_seconds: 2
  movie_target_minutes_min: 30
  movie_target_minutes_max: 60
  video_sample_positions: [0.1, 0.5, 0.9]
  preserve_all_videos: yes
```

## Media Safety

Dry run must:

- Score all input media.
- Generate reports.
- Show which files would be selected.
- Keep selected paths pointed at `input_data`.
- Not move, delete, rename, or edit source media.

Execute mode must:

- Preflight all selected source paths before writing downstream manifests.
- Never move, delete, rename, or edit source media.
- Write reports with selected paths pointing to `input_data`.
- Leave all files in their current location.

## Reset Compatibility

Quality Scoring itself should not move or copy media. It writes metadata only under:

```text
MemoryCurator/03 Quality Scoring/
```

The project-level reset command must clean generated Quality Scoring metadata and should also remain backward-compatible with older runs that may have copied or moved selected files under:

```text
MemoryCurator/03 Quality Scoring/selected_quality/
```

Those legacy files should be restored to their original project-relative paths when possible. Current implementations must not create new selected-media folders for this phase.

Reset must also clean generated Quality Scoring reports under `MemoryCurator/03 Quality Scoring/`.

## Architecture

- Keep reusable implementation under `memory_curator_engine/scoring/`.
- Reuse common path, config, media, and metadata helpers.
- Keep the phase compatible with:
  - `python3 -m memory_curator_engine quality-scoring`
  - `python3 -m memory_curator_engine quality-scoring --execute`
- Keep scoring metrics explainable and included in reports.
- Structure code so future AI scoring modules can add additional score components later.
- Do not implement AI in this phase.

## Verification

Run:

```bash
.venv/bin/python -B -m compileall -q memory_curator_engine
.venv/bin/python -B -m memory_curator_engine quality-scoring
```

Verify dry run:

- Reports are generated under `MemoryCurator/03 Quality Scoring/`.
- Source media count is unchanged.
- `quality_manifest.csv` contains selected media paths.
- No files are moved.

After reviewing dry-run output, run:

```bash
.venv/bin/python -B -m memory_curator_engine quality-scoring --execute
```

Verify execute mode:

- No selected files are moved.
- `quality_manifest.csv` points to original input media paths.
- Not-selected files remain in place.
- Project-level reset preview shows generated metadata files as cleanable.
