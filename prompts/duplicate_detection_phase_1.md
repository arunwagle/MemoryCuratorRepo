# Phase 1 Inventory And Duplicate Detection Prompt

Implement the first working phase of the MemoryCurator project.

Phase 1 includes:

- Inventory generation
- Exact duplicate detection
- Photo near-duplicate detection
- Video near-duplicate detection
- Dry-run reporting
- Execute mode for finalizing duplicate reports and keeper manifests
- Project-level reset support

Do not treat duplicate detection as a later phase for this project. The current goal is to make Phase 1 useful enough to prepare great photo albums, Instagram reels, and documentary-style trip videos.

## Context

- This is a generic media curation engine.
- Trip-specific data and config live under folders such as `input_data/trips/bali/`.
- Example source media folder: `input_data/trips/bali/data/rafting`.
- Example trip config: `input_data/trips/bali/config/default.yaml`.
- Workflow outputs go under `MemoryCurator/`.
- Original source media must never be moved, deleted, renamed, or modified.
- Reset must clean generated workflow outputs. It should also restore legacy reversible moves from older runs if those folders exist.
- Duplicate detection must analyze media content, not filenames.
- The implementation must work for both photos and videos.

## Phase 1 Goals

Create a config-driven Phase 1 pipeline that:

- Reads enabled media sets from the trip YAML config.
- Scans photos and videos from each enabled input folder.
- Generates inventory CSV reports.
- Detects exact duplicates using file content hashes.
- Detects photo near-duplicates using visual similarity.
- Detects video near-duplicates using sampled visual content.
- Chooses the best item to keep in each duplicate group.
- Generates duplicate review CSV reports.
- Generates a keeper manifest for downstream phases.
- Runs in dry-run mode by default.
- Execute mode finalizes CSV reports only; duplicate candidates remain in `input_data`.
- Provides a project-level reset command that previews by default and executes only when explicitly requested.

## Inventory Output

Inventory reports go to the configured output path for each media set, for example:

```text
MemoryCurator/01 Inventory/rafting_inventory.csv
```

Inventory rows should include:

- filename
- relative_path
- file_type
- size_bytes
- capture_date
- capture_date_source
- created_date
- modified_date
- width
- height
- duration_seconds
- metadata_notes

## Duplicate Detection Behavior

Exact duplicate detection:

- Use SHA-256 file content hashing.
- This works for all supported media types.

Photo near-duplicate detection:

- Use visual similarity, not filenames.
- Prefer the installed dependency path:
  - `Pillow`
  - `pillow-heif`
  - `ImageHash` when useful
- Use perceptual visual hashing, currently difference-hash style behavior.
- HEIC photos should decode through `pillow-heif` when available.
- Fall back to macOS `qlmanage` + `sips` when optional libraries are unavailable.
- The photo hash threshold must be configurable.

Video near-duplicate detection:

- Use content-based analysis.
- Prefer OpenCV sampled frames when `opencv-python` is installed.
- Sample frames at configurable positions such as 10%, 50%, and 90%.
- Combine sampled frame visual hashes into a representative video hash.
- Fall back to macOS `qlmanage` thumbnail hashing when OpenCV is unavailable.
- Compare duration and dimensions to avoid obvious false positives.
- The video hash threshold and sample positions must be configurable.
- Exact duplicates can be collapsed to one keeper.
- Video near-duplicates should be reported for review, but the downstream keeper manifest may preserve them when `preserve_video_near_duplicates: yes` because alternate camera angles can be valuable for reels and documentaries.

Best-file selection:

- Prefer higher resolution.
- Prefer longer duration for videos when appropriate.
- Prefer larger file size if resolution/duration are equal.
- Prefer more complete metadata.
- Use stable path ordering as the final deterministic tie-breaker.

## Duplicate Reports

Write duplicate reports to:

```text
MemoryCurator/02 Duplicate Detection/duplicate_groups.csv
MemoryCurator/02 Duplicate Detection/duplicates_to_review.csv
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

The reports should include:

- media_set
- group_id
- action: keep or duplicate
- original_path
- duplicate_path
- file_type
- size_bytes
- width
- height
- duration_seconds
- duplicate_type:
  - exact_hash
  - photo_visual_similarity
  - video_visual_similarity
- similarity_score
- hash_distance
- reason

`keeper_manifest.csv` should include only files selected for downstream processing. It should exclude duplicate candidates and include:

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
- source_phase

## Dry-Run And Media Safety

Default behavior:

```yaml
duplicate_detection:
  dry_run: yes
```

Dry-run mode must:

- Generate reports.
- Pick keep/duplicate candidates.
- Show duplicate candidates and selected keep files.
- Not move, delete, rename, or edit source media.

Execute mode must:

- Finalize CSV reports only. Do not move duplicates.
- Regenerate duplicate CSV reports and `keeper_manifest.csv`.
- Keep all media in `input_data`.
- Ensure duplicate CSV paths point at original input media locations.

## Config Shape

Trip config example:

```yaml
project:
  name: Bali Memory Curator
  trip_slug: bali
  trip_root: input_data/trips/bali
  data_root: input_data/trips/bali/data
  workflow_root: MemoryCurator

inventory:
  media_sets:
    rafting:
      enabled: yes
      input_dir: input_data/trips/bali/data/rafting
      output_csv: MemoryCurator/01 Inventory/rafting_inventory.csv
    atv:
      enabled: no
      input_dir: input_data/trips/bali/data/atv
      output_csv: MemoryCurator/01 Inventory/atv_inventory.csv

modules:
  inventory:
    enabled: yes
  duplicate_detection:
    enabled: yes

duplicate_detection:
  dry_run: yes
  exact_hash: yes
  photo_near_duplicates: yes
  video_near_duplicates: yes
  photo_hash_threshold: 8
  video_hash_threshold: 8
  video_sample_positions: [0.1, 0.5, 0.9]
  output_dir: MemoryCurator/02 Duplicate Detection
  review_dir: MemoryCurator/02 Duplicate Detection/review_duplicates  # legacy reset restore root only
```

## Dependencies

Use `requirements.txt` for optional stronger media analysis dependencies.

The requirements file should use the Databricks PyPI proxy:

```text
--index-url https://pypi-proxy.cloud.databricks.com/simple

Pillow>=10.0
pillow-heif>=0.15
ImageHash>=4.3
opencv-python>=4.9
imageio-ffmpeg>=0.6
moviepy>=2.2
librosa>=0.11
soundfile>=0.14
```

Recommended setup:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B -m memory_curator_engine inventory
.venv/bin/python -B -m memory_curator_engine duplicate-detection
.venv/bin/python -B -m memory_curator_engine duplicate-detection --execute
.venv/bin/python -B -m memory_curator_engine duplicate-detection --manifest-only
```

## Architecture

- Keep reusable implementation under `memory_curator_engine/`.
- Inventory implementation lives under `memory_curator_engine/inventory/`.
- Duplicate detection implementation lives under `memory_curator_engine/dedupe/`.
- Keep phase orchestration compatible with:
  - `python3 -m memory_curator_engine inventory`
  - `python3 -m memory_curator_engine duplicate-detection`
- Reuse common media metadata helpers where possible.
- Keep source media scanning consistent across inventory and duplicate detection.
- Do not implement AI in Phase 1.
- Keep the code modular and testable.

## Verification

Run:

```bash
.venv/bin/python -B -m memory_curator_engine inventory
.venv/bin/python -B -m memory_curator_engine duplicate-detection
```

Verify:

- Inventory CSV is created.
- Duplicate reports are created.
- Source media file count is unchanged.
- Dry-run duplicate detection does not move files.
- Reports identify keep vs duplicate candidates.
- Execute mode finalizes metadata and keeper manifests only; duplicates remain in their original `input_data` locations.

Latest Bali rafting dry-run result after installing dependencies:

- Scanned `226` files.
- Found `23` duplicate/near-duplicate groups.
- Flagged `50` duplicate candidates.
- Kept source media unchanged at `226` files.
