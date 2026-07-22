# MemoryCurator Technical Design

MemoryCurator is a Python media curation engine for trips, events, and activity-based memories. It turns raw photos and videos into structured inventories, duplicate-safe manifests, quality-ranked media, story moments, PDF photo albums, selected activity timelines, Instagram reels, and documentary plans.

The project is intentionally config-driven. The same engine can run for Bali, a future trip, a wedding, a birthday, or any other media collection by changing the trip YAML and activity folders.

## Quickstart

```bash
git clone https://github.com/arunwagle/MemoryCuratorRepo.git
cd MemoryCuratorRepo

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

memory-curator --help
memory-curator prompt-guide
```

Create activity folders under a trip:

```text
input_data/trips/sample/data/beach/
input_data/trips/sample/data/adventure/
```

Copy your own photos/videos into those folders, then run:

```bash
memory-curator --config input_data/trips/sample/config/default.yaml inventory
memory-curator --config input_data/trips/sample/config/default.yaml run-all
memory-curator --config input_data/trips/sample/config/default.yaml run-all --execute
```

Dry runs write reports and edit decisions. `--execute` enables final PDF/video rendering for phases that support final outputs.

## Prompt-Only Option

You can also use MemoryCurator as a prompt/design library without running the Python engine:

```bash
memory-curator prompt-guide
```

The phase prompts live in [prompts](prompts), and the usage guide is [docs/PROMPT_ONLY_WORKFLOW.md](docs/PROMPT_ONLY_WORKFLOW.md). This is useful for people who want Codex, ChatGPT, or another coding agent to implement one phase, port the idea to another language, or customize the architecture for a different media workflow.

## Privacy and Data Safety

MemoryCurator is designed so personal media stays local by default. The repository includes a sample trip config, but your real photos, videos, generated outputs, and private trip files should remain on your machine unless you intentionally publish them.

Important defaults:

- Original media under `input_data/trips/<trip>/data` is ignored by Git.
- Generated media under `input_data/trips/<trip>/curated` is ignored by Git.
- Runtime caches are ignored by Git.
- The sample config under `input_data/trips/sample/config` is tracked for quickstart usage.
- Personal trip configs can contain private paths, activity names, or metadata choices, so review them before sharing.
- Documentation images under `docs/` may be tracked intentionally.

## Architecture Diagram

![MemoryCurator end-to-end flow](docs/MemoryCurator_Flow_Diagram.png)

Editable source: [docs/MemoryCurator_Flow_Diagram.drawio](docs/MemoryCurator_Flow_Diagram.drawio)

## Core Principles

- Originals are protected. Source media under `input_data/trips/<trip>/data/...` is never deleted, moved, or overwritten by normal phases.
- Reports and manifests are first-class outputs. Each phase writes CSV or Markdown files that downstream phases consume.
- Generated media lives under the trip `curated` folder. Rendered PDFs, MP4s, thumbnails, frames, and exports belong under `input_data/trips/<trip>/curated/...`.
- Activity context matters. Rafting, ATV, beach, restaurants, temples, and club scenes should not be scored the same way.
- Dry run first, execute second. Most creative or destructive-looking phases support dry-run reporting before final rendering.
- AI is optional and additive. The current system uses deterministic Python/OpenCV/FFmpeg-style analysis first, with hooks for OpenAI, Whisper, and future vision models.

## Repository Layout

```text
.
├── memory_curator_engine/          # Python package implementing the engine
│   ├── common/                     # Config, paths, activity profiles, media helpers, reset, execution
│   ├── inventory/                  # Phase 01
│   ├── dedupe/                     # Phase 02
│   ├── scoring/                    # Phase 03
│   ├── vision/                     # Future Phase 04 AI/vision modules
│   ├── story/                      # Phase 05
│   ├── albums/                     # Phase 06
│   ├── video/                      # Phase 07
│   ├── selected_timeline/          # Phase 08
│   ├── reels/                      # Phase 09
│   ├── documentary/                # Phase 10
│   └── time_capsule/               # Future Phase 11 modules
├── MemoryCurator/                  # Human-readable workflow reports by phase
├── input_data/
│   └── trips/
│       └── sample/
│           ├── config/default.yaml # Trip-specific configuration
│           ├── data/               # Original source media, grouped by activity
│           └── curated/            # Generated PDFs, videos, thumbnails, frames, exports
├── prompts/                        # Design prompts and phase specs
├── models/                         # Optional local ML models
└── requirements.txt
```

## Installation

Use Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you prefer installing dependencies directly without package metadata:

```bash
pip install -r requirements.txt
```

For Databricks-proxy environments:

```bash
pip install -r requirements-databricks.txt
pip install -e . --no-deps
```

Current optional/advanced libraries include:

- `Pillow`, `pillow-heif` for image loading, HEIC support, orientation handling, and PDF rendering preparation.
- `ImageHash` for stronger perceptual image similarity.
- `opencv-python` for frame sampling, motion analysis, face detection, visual scoring, and video introspection.
- `imageio-ffmpeg` for bundled FFmpeg access when system FFmpeg is unavailable.
- `moviepy` for future higher-level video editing workflows.
- `librosa` and `soundfile` for audio feature extraction.
- `reportlab` for PDF album generation.
- `torch` and `open-clip-torch` for optional OpenCLIP semantic embeddings in Selected Timeline.

## Local Models, OpenCLIP, and Caches

MemoryCurator keeps ML models optional and configuration-driven. The pipeline should still run with deterministic logic when optional AI/ML dependencies are unavailable, but richer semantic filtering is enabled when the libraries and model weights exist.

Current model assets:

- `models/face_detection_yunet_2023mar.onnx`: local OpenCV YuNet face detector used by Album Builder and Selected Timeline face/person eligibility checks.
- OpenCLIP `ViT-B-32` with `pretrained: openai`: optional semantic visual embedding model used by Selected Timeline when `selected_timeline.semantic_similarity.enabled: yes`.

Example semantic configuration:

```yaml
selected_timeline:
  semantic_similarity:
    enabled: yes
    backend: openclip
    model: ViT-B-32
    pretrained: openai
    checkpoint_path: null
    device: auto
    disable_implicit_hf_token: yes
    sample_frames: 3
    threshold: 0.91
    recent_window: 6
    cache_file: semantic_embedding_cache.json
  face_filter:
    reject_person_without_face: yes
    backend: opencv_yunet
    model_path: models/face_detection_yunet_2023mar.onnx
```

How model loading works:

- OpenCV YuNet is stored directly in the repo under `models/`, so no download is needed at runtime for face detection.
- OpenCLIP model weights are managed by the `open_clip`/PyTorch stack. With `model: ViT-B-32` and `pretrained: openai`, the first run may download the checkpoint through the model registry used by `open_clip`, commonly via Hugging Face Hub or OpenCLIP's configured download source depending on package version.
- The code sets `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` when configured, so Hugging Face Hub access does not silently use a personal token.
- If you need fully offline or reproducible model loading, download the checkpoint yourself and set `selected_timeline.semantic_similarity.checkpoint_path` to the local file.

Runtime caches:

- `MemoryCurator/08 Selected Timeline/<activity>/segment_audit_cache.json`: cached OpenCV/frame-audit decisions keyed by source file, time window, activity profile, and audit cache version.
- `MemoryCurator/08 Selected Timeline/<activity>/semantic_embedding_cache.json`: cached OpenCLIP image embeddings keyed by source file identity, time window, model, and pretrained checkpoint.
- `MemoryCurator/07 Video Processing/audio-analysis/cache/*.json`: cached audio analysis windows so reruns do not reprocess the same media.

These caches are safe to delete when changing algorithms. The next run will rebuild them from original media.

## Command Line Usage

Explicit config:

```bash
python3 -m memory_curator_engine --config input_data/trips/sample/config/default.yaml <command>
```

Installed console command:

```bash
memory-curator --config input_data/trips/sample/config/default.yaml <command>
```

If `--config` is omitted, the sample config is used by default. For your own trip, copy `input_data/trips/sample/config/default.yaml`, change `trip_slug`, `trip_root`, activity folders, and activity profiles, then pass the new config with `--config`.

### Common Commands

```bash
# Run one phase
python3 -m memory_curator_engine inventory
python3 -m memory_curator_engine duplicate-detection
python3 -m memory_curator_engine quality-scoring
python3 -m memory_curator_engine story-builder
python3 -m memory_curator_engine album-builder
python3 -m memory_curator_engine video-processing
python3 -m memory_curator_engine selected-timeline
python3 -m memory_curator_engine reel-builder
python3 -m memory_curator_engine documentary-builder

# Execute phases that support final outputs
python3 -m memory_curator_engine duplicate-detection --execute
python3 -m memory_curator_engine quality-scoring --execute
python3 -m memory_curator_engine album-builder --execute
python3 -m memory_curator_engine video-processing --execute
python3 -m memory_curator_engine selected-timeline --execute
python3 -m memory_curator_engine reel-builder --execute
python3 -m memory_curator_engine documentary-builder --execute

# Run the full enabled workflow
python3 -m memory_curator_engine run-all
python3 -m memory_curator_engine run-all --execute

# Run only selected activities
python3 -m memory_curator_engine run-all --set rafting --set atv --execute
python3 -m memory_curator_engine selected-timeline --set rafting --execute
python3 -m memory_curator_engine reel-builder --set atv --execute

# Skip phases
python3 -m memory_curator_engine run-all --skip media-intelligence --skip time-capsule --execute

# Reset generated workflow state
python3 -m memory_curator_engine reset
python3 -m memory_curator_engine reset --execute
```

## Configuration Model

The trip config controls where media comes from, which modules run, how activity scoring works, and where outputs go.

Example trip configuration:

```yaml
project:
  trip_slug: sample
  trip_root: input_data/trips/sample
  data_root: input_data/trips/sample/data
  curated_root: input_data/trips/sample/curated
  workflow_root: MemoryCurator
```

Activities are configured as media sets:

```yaml
inventory:
  media_sets:
    rafting:
      enabled: yes
      activity_name: Rafting
      activity_profile: rafting
      input_dir: input_data/trips/sample/data/rafting
      output_csv: MemoryCurator/01 Inventory/rafting_inventory.csv
```

Each activity can be enabled or disabled with `enabled: yes/no`. This allows the same trip to run for rafting first, then ATV, then all activities.

### Activity Profiles

Activity profiles are the main intelligence layer. They tell downstream phases what each activity is supposed to optimize for.

Example, simplified:

```yaml
activity_profiles:
  rafting:
    optimization_goal: adventure
    maximize: [action, water, rapids, splash, excitement, river, waterfall, group_reactions]
    minimize: [static, waiting, walking, talking, parking, meal]
    required_context: [rafting, river, water, rapid, splash, paddle, raft, helmet]
    reject_context: [atv, quad, temple, restaurant, beach, pool, villa]
    reel_weights:
      activity: 0.45
      adventure: 0.25
      emotion: 0.15
      story: 0.10
      technical: 0.03
      diversity: 0.02
```

This means a rafting reel should favor rapids, splashes, water, action, reactions, and group adventure. A beach reel should favor ocean, people, scenery, swimming, and cinematic shots. A restaurant album should favor friends, food, emotion, and memory.

## Workflow Phases

```text
01 Inventory
02 Duplicate Detection
03 Quality Scoring
04 Media Intelligence
05 Story Builder
06 Album Builder
07 Video Processing
08 Selected Timeline
09 Reel Builder
10 Documentary Builder
11 Time Capsule
```

Phases 04 and 11 are currently placeholders for future AI/semantic expansion.

## Phase 01: Inventory

### Purpose

Inventory scans configured activity folders and records the media facts needed by every downstream phase.

### Inputs

- `input_data/trips/<trip>/data/<activity>/...`
- `inventory.media_sets` in YAML.

### Processing

The inventory phase:

- Recursively scans each enabled activity folder.
- Classifies files as photo or video based on extension.
- Records file name, relative path, type, size, created date, modified date, and capture date.
- Extracts width and height when available.
- Extracts video duration when available.
- Attempts embedded metadata first, then falls back to filesystem dates.
- Uses improved capture chronology for videos so clips from GoPro/iPhone/Meta are ordered by actual capture time when available.

### Outputs

Per activity:

```text
MemoryCurator/01 Inventory/<activity>_inventory.csv
```

Important columns:

- `filename`
- `relative_path`
- `file_type`
- `size_bytes`
- `capture_date`
- `capture_date_source`
- `created_date`
- `modified_date`
- `width`
- `height`
- `duration_seconds`
- `metadata_notes`

### Enhancements

Useful future libraries and techniques:

- `exiftool` or `PyExifTool` for richer photo, QuickTime, GoPro, iPhone, and GPS metadata.
- `pymediainfo` for codec, bitrate, rotation, audio streams, and creation time.
- GPS reverse geocoding for location-aware story building.
- Time zone normalization for trips across countries.
- Camera/person source labeling from device metadata.

## Phase 02: Duplicate Detection

### Purpose

Duplicate Detection removes repeated or near-repeated media from the downstream pipeline without touching originals.

It does not delete or move media. It writes duplicate reports and a `keeper_manifest.csv` that all later phases consume.

### Inputs

- All enabled inventory CSVs from Phase 01.
- Duplicate configuration:
  - `exact_hash`
  - `photo_near_duplicates`
  - `video_near_duplicates`
  - `photo_hash_threshold`
  - `video_hash_threshold`
  - `preserve_video_near_duplicates`

### Processing

Algorithms currently used:

- Exact duplicate detection with SHA-256 file content hashes.
- Photo near-duplicate detection with perceptual difference hashes.
- HEIC/photo support through Pillow and `pillow-heif` when installed.
- Video near-duplicate detection by sampling representative frames and combining frame hashes.
- OpenCV frame extraction for stronger video hashing.
- macOS Quick Look or image conversion fallback when direct decoding fails.
- Hamming distance comparison between perceptual hashes.
- Connected grouping of related duplicates.
- Keeper selection chooses the best candidate in a group and marks others as duplicate candidates.
- Video near-duplicates can be preserved when configured, because similar action-camera, phone, WhatsApp, or tour-company clips can still contain important story differences. Exact/file duplicates are still reported, while visual-similarity video groups can remain available for downstream timeline intelligence.

The current design intentionally avoids filename-only matching.

### Outputs

Root reports:

```text
MemoryCurator/02 Duplicate Detection/duplicate_groups.csv
MemoryCurator/02 Duplicate Detection/duplicates_to_review.csv
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

Activity-scoped copies:

```text
MemoryCurator/02 Duplicate Detection/<activity>/duplicate_groups.csv
MemoryCurator/02 Duplicate Detection/<activity>/duplicates_to_review.csv
MemoryCurator/02 Duplicate Detection/<activity>/keeper_manifest.csv
```

Report meaning:

- `duplicate_groups.csv`: grouped duplicates, selected keeper, duplicate type, similarity score, hash distance, and reason.
- `duplicates_to_review.csv`: human review queue for duplicate candidates.
- `keeper_manifest.csv`: clean handoff manifest for Phase 03.

### Enhancements

Useful future libraries and techniques:

- `ImageHash` pHash, dHash, wHash, and color hash ensembles instead of one visual hash.
- SSIM or LPIPS for higher-quality near-duplicate comparison.
- CLIP/OpenCLIP embeddings for semantic similarity.
- FAISS, Annoy, or ScaNN for fast large-library similarity search.
- Scene-aware video duplicate comparison using keyframes, not only sampled positions.
- Face/person-aware duplicate selection so the keeper favors uncut faces and better expressions.
- LLM or VLM review summaries for "why these look similar".

## Phase 03: Quality Scoring

### Purpose

Quality Scoring decides which keeper media are good enough for albums, reels, documentaries, and time capsules.

This phase requires `keeper_manifest.csv`. It intentionally fails if the upstream manifest is missing, so the pipeline remains deterministic.

### Inputs

```text
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

### Processing

The phase calculates multiple scores:

- `technical_score`: base quality signal.
- `sharpness_score`: image or sampled-frame clarity.
- `exposure_score`: brightness and exposure balance.
- `resolution_score`: dimensions and usable pixel count.
- `stability_score`: video steadiness approximation.
- `video_motion_score`: motion/activity signal from sampled frames.
- `activity_score`: fit against the configured activity profile.
- `album_purpose_score`: people, memory, and photo suitability.
- `reel_purpose_score`: action, motion, activity value, and energy.
- `documentary_purpose_score`: story usefulness and continuity value.
- `time_capsule_purpose_score`: preservation value.

Activity scoring is dynamic. For rafting, water/action/splash cues matter more. For restaurants, people, food, and emotion matter more. For beach, cinematic scenery and people matter more.

Selection combines thresholds and per-activity coverage:

- Minimum score thresholds for photo and video.
- Purpose-specific thresholds for album, Instagram, and movie usage.
- Top percentage per activity.
- Minimum and maximum selected counts per activity.
- Movie runtime preservation so long-form video does not starve.
- Optional `preserve_all_videos` mode, which keeps all duplicate-cleaned videos in `quality_manifest.csv` so Video Processing and Selected Timeline can choose the best scenes/windows later instead of losing short social clips too early.

### Outputs

Root reports:

```text
MemoryCurator/03 Quality Scoring/quality_scores.csv
MemoryCurator/03 Quality Scoring/quality_selection.csv
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

Activity-scoped reports:

```text
MemoryCurator/03 Quality Scoring/<activity>/quality_scores.csv
MemoryCurator/03 Quality Scoring/<activity>/quality_selection.csv
MemoryCurator/03 Quality Scoring/<activity>/quality_manifest.csv
```

`quality_manifest.csv` is the required handoff to Story Builder and Video Processing.

### Enhancements

Useful future libraries and techniques:

- BRISQUE, NIQE, or PIQE no-reference image quality metrics.
- Face quality models for eye openness, blur, expression, and face cutoff detection.
- Video blur and shake scoring with optical flow.
- Audio excitement scoring using speech/music/scream/laughter classifiers.
- CLIP/OpenCLIP activity fit scoring.
- OpenAI or other VLM classification over sampled frames for tags such as "rapid", "tunnel", "water crossing", "sunset", "group selfie".
- Learned ranking from user feedback, for example "photos kept in final album become positive labels".

## Phase 04: Media Intelligence

### Purpose

Media Intelligence is the planned semantic AI layer. It is currently optional and disabled by default.

The goal is to add richer labels that are expensive or impossible to infer from metadata alone:

- Person/face detection.
- Face grouping.
- Emotion and mood tagging.
- Captions and descriptions.
- Object and scene classification.
- OCR and sign detection.
- Landmark and place detection.

### Current Status

The module is configured as a placeholder:

```yaml
media_intelligence:
  face_person_detection:
    enabled: no
  emotion_mood_tagging:
    enabled: no
  captions_descriptions:
    enabled: no
```

### Future Outputs

Suggested outputs:

```text
MemoryCurator/04 Media Intelligence/face_person_manifest.csv
MemoryCurator/04 Media Intelligence/emotion_mood_tags.csv
MemoryCurator/04 Media Intelligence/captions_descriptions.csv
MemoryCurator/04 Media Intelligence/media_intelligence_manifest.csv
```

### Enhancements

Useful future libraries and APIs:

- OpenCV YuNet, Haar cascades, MediaPipe, RetinaFace, or InsightFace for face detection.
- DeepFace or FER for emotion classification.
- YOLOv8/YOLOv10/RT-DETR for objects and activity context.
- OpenCLIP/CLIP for zero-shot tags.
- BLIP, LLaVA, Qwen-VL, GPT-4.1/GPT-5 class vision models, or OpenAI vision APIs for captions.
- FAISS for person or scene embedding search.

## Phase 05: Story Builder

### Purpose

Story Builder converts hundreds or thousands of individual files into human-level moments.

Instead of remembering 395 assets, the system should remember:

- Leaving villa.
- Arriving at rafting center.
- Gear and helmets.
- Walking to the river.
- Launching raft.
- First rapids.
- Big splash.
- Group photo.
- Lunch.
- Drive home.

### Inputs

```text
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

### Processing

The phase:

- Groups media by activity.
- Sorts assets chronologically using capture time.
- Creates temporal clusters using `max_gap_seconds`.
- Merges small moments when configured.
- Splits very large moments when needed.
- Uses activity-specific taxonomies.
- Assigns moment types such as `arrival`, `gear_up`, `launch`, `rapids`, `water_action`, `group_photo`, `meal`, `return_trip`.
- Selects hero photo and hero video candidates.
- Scores moments using quality, activity value, asset count, photo/video mix, and story usefulness.
- Optionally allows AI refinement after Python grouping.

Story Builder currently uses Python classification first to reduce token usage. Optional OpenAI classification can be enabled later for naming, classification, and summarization.

### Outputs

Root reports:

```text
MemoryCurator/05 Story Builder/moments.csv
MemoryCurator/05 Story Builder/moments.json
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/story_review.csv
```

Activity-scoped reports:

```text
MemoryCurator/05 Story Builder/<activity>/moments.csv
MemoryCurator/05 Story Builder/<activity>/moment_assets.csv
MemoryCurator/05 Story Builder/<activity>/story_manifest.csv
MemoryCurator/05 Story Builder/<activity>/story_review.csv
```

### Enhancements

Useful future libraries and techniques:

- LLM moment naming and story summarization.
- VLM-based event classification from representative frames.
- Audio/transcript-aware moment boundaries.
- GPS-aware clustering.
- Multi-camera synchronization by capture time and visual similarity.
- Person-aware moments such as "everyone together", "Arun solo", "friends reacting".
- Feedback loop where user-edited moment titles improve future classification.

## Phase 06: Album Builder

### Purpose

Album Builder creates printable/shareable PDF photo albums from the best photo assets across activities.

The current design creates trip-level albums, not separate albums per activity. Activity sections are preserved in order so the album reads like a trip memory book.

### Inputs

```text
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/moments.csv
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

### Processing

Album Builder:

- Consumes Story Builder moments and Quality Scoring photo candidates.
- Uses folder/activity as the default activity tag.
- Orders photos by activity and capture time.
- Requires faces when configured.
- Excludes photos with detected cutoff faces when configured.
- Applies orientation correction so portrait/landscape images render correctly.
- Uses similarity filtering to avoid repeated near-identical photos.
- Uses burst-window filtering to avoid too many nearly identical shots from the same minute.
- Uses one combined enhanced album by default:
  - `enhanced`: story-ordered trip album across all activities, including all strong eligible photos while avoiding repeated near-identical bursts.
- Additional variants can still be configured later, but the default output is a single complete trip photo book.
- Generates final PDFs only. It does not copy all selected source images into export folders.

Album score is currently weighted as:

```text
final_album_score =
  quality_score * 0.30
+ memory_score  * 0.30
+ story_score   * 0.20
+ people_score  * 0.10
+ diversity_score * 0.10
```

The design intentionally allows a technically imperfect but emotionally strong photo to beat a sharp but boring photo.

### PDF Configuration

Album cover and closing media can be configured:

```yaml
album_builder:
  pdf_export:
    enabled: yes
    title: Some friendships never needed a restart.
    subtitle: Summer 2026
    cover_photo: input_data/trips/sample/data/beach/photos/cover.jpg
    closing_photo: input_data/trips/sample/data/beach/photos/closing.jpg
```

### Outputs

Reports:

```text
MemoryCurator/06 Album Builder/album_candidates.csv
MemoryCurator/06 Album Builder/album_selection.csv
MemoryCurator/06 Album Builder/album_manifest.csv
MemoryCurator/06 Album Builder/album_report.md
```

PDF exports:

```text
input_data/trips/<trip>/curated/06 Album Builder/exports/*.pdf
```

### Enhancements

Useful future libraries and techniques:

- Better face detection with InsightFace, RetinaFace, MediaPipe, or OpenCV YuNet.
- Face recognition so the album balances people.
- Smile/expression/eye-open scoring.
- Aesthetic models such as LAION aesthetic predictor.
- Layout engines for magazine-style pages.
- Optional Canva Connect API integration if programmatic Canva design export is needed.
- HTML/CSS to PDF rendering for richer book layouts.
- LLM-generated section titles, captions, and dedications.
- User feedback loop for "never use this photo" and "always include this person".

## Phase 07: Video Processing

### Purpose

Video Processing is an internal intelligence engine used by Selected Timeline, Reel Builder, and Documentary Builder.

It should understand videos. It should not behave like a manual video editor.

### Inputs

```text
MemoryCurator/03 Quality Scoring/quality_manifest.csv
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/moment_assets.csv
```

### Internal Stages

```text
07.1 scene-detection
07.2 clip-segmentation
07.3 clip-scoring
07.4 frame-analysis
07.5 audio-analysis
07.6 transcript
07.7 timeline-builder
```

### 07.1 Scene Detection

Purpose: split videos into logical scenes.

Current approach:

- Uses duration, frame sampling, visual change, and activity context.
- Creates scene windows with start/end times.
- Writes per-activity and root manifests.

Outputs:

```text
MemoryCurator/07 Video Processing/scene-detection/scene_manifest.csv
MemoryCurator/07 Video Processing/scene-detection/<activity>/scene_manifest.csv
```

Enhancements:

- PySceneDetect adaptive/content detectors.
- TransNetV2 for learned scene boundaries.
- Shot boundary detection using histogram, SSIM, or embeddings.

### 07.2 Clip Segmentation

Purpose: convert scenes into usable clip windows for reels and documentary.

Current approach:

- Creates short reel-friendly clips.
- Creates longer documentary-friendly clips.
- Keeps source paths and planned clip paths.
- Does not need to extract all clips unless configured.

Outputs:

```text
MemoryCurator/07 Video Processing/clip-segmentation/clip_manifest.csv
MemoryCurator/07 Video Processing/clip-segmentation/<activity>/clip_manifest.csv
```

### 07.3 Clip Scoring

Purpose: score each clip for downstream usage.

Scores include:

- `quality_score`
- `action_score`
- `people_score`
- `story_score`
- `audio_score`
- `activity_score`
- `reel_score`
- `documentary_score`
- `time_capsule_score`
- `overall_score`

Outputs:

```text
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/clip-scoring/top_clips.csv
MemoryCurator/07 Video Processing/clip-scoring/<activity>/clip_scores.csv
MemoryCurator/07 Video Processing/clip-scoring/<activity>/top_clips.csv
```

Enhancements:

- Learned clip ranking.
- Multi-object tracking.
- Camera motion analysis.
- Activity-specific classifiers, for example ATV tunnel, water crossing, slope, mud, speed.
- VLM scoring over representative frames.

### 07.4 Frame Analysis

Purpose: inspect representative frames without processing every frame.

Current approach:

- Samples frames at configured intervals.
- Computes brightness and sharpness.
- Assigns rough visual tags and motion context.
- Writes frame metadata for downstream review.

Outputs:

```text
MemoryCurator/07 Video Processing/frame-analysis/frame_manifest.csv
MemoryCurator/07 Video Processing/frame-analysis/<activity>/frame_manifest.csv
```

Enhancements:

- CLIP/OpenCLIP zero-shot tags.
- YOLO object detection.
- OCR for signs.
- Landmark recognition.
- Person and face detection.
- Aesthetic and composition scoring.

### 07.5 Audio Analysis

Purpose: detect audio energy and important sound moments.

Current approach:

- Uses audio windows.
- Detects intensity and event-like sections.
- Caches analysis so repeated runs do not reprocess the same audio unnecessarily.
- Feeds reels and documentary with audio excitement context.

Outputs:

```text
MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
MemoryCurator/07 Video Processing/audio-analysis/<activity>/audio_events.csv
```

Enhancements:

- `librosa` features for onset, tempo, RMS, spectral centroid, and silence.
- Laughter, cheering, water, engine, crowd, and music classifiers.
- Speech/music/noise separation.
- Source separation with Demucs.

### 07.6 Transcript

Purpose: generate searchable speech segments and allow muted phrase filtering.

Current config supports:

```yaml
transcript:
  backend: none | local_whisper | openai
```

Outputs:

```text
MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
MemoryCurator/07 Video Processing/transcript/<activity>/transcript_segments.csv
```

Transcript rows can be used to mute configured phrases such as:

```yaml
mute_phrases:
  - gopro start recording
  - go pro start recording
  - gopro stop recording
  - go pro stop recording
```

Enhancements:

- `faster-whisper` for local transcription.
- OpenAI transcription APIs for hosted transcription.
- Speaker diarization with pyannote.
- Keyword search and chapter markers.

### 07.7 Timeline Builder

Purpose: create a semantic video timeline.

Example:

```text
00:00 Walking to raft
00:35 Laughing
01:10 Rapids
02:20 Splash
03:00 Group reaction
03:40 Calm river
```

Outputs:

```text
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
MemoryCurator/07 Video Processing/timeline-builder/<activity>/video_timeline.csv
MemoryCurator/07 Video Processing/video_processing_manifest.csv
```

Enhancements:

- LLM timeline labeling over frame/audio/transcript rows.
- VLM-based frame descriptions.
- Activity-specific event detectors.
- Chronological multi-camera alignment.

## Phase 08: Selected Timeline

### Purpose

Selected Timeline creates the best activity-level master highlight sequence before reels are rendered.

This phase exists because reels and documentaries should not repeatedly re-solve the same hard problem. First, the system chooses the best timeline segments for an activity. Then Reel Builder compresses those segments into vertical reel variants.

### Inputs

- Video Processing clip scores.
- Video Processing timelines.
- Audio events.
- Transcript segments.
- Activity profiles.

### Processing

Selected Timeline:

- Runs per activity.
- Scores candidate windows from video timeline events.
- Uses activity profile maximize/minimize/reject context rules.
- Audits candidate windows with frame-level introspection.
- Rejects floor/ground-only or visually unimportant starts when activity context does not support them.
- Rejects bad source-orientation windows rather than rotating them during rendering. Clips tagged `bad_orientation`, `unstable_roll`, `weak_close_pov`, `ground_only`, or `setup_surface` are excluded from Selected Timeline.
- Preserves chronological order using embedded camera capture time when available.
- Selects late payoff moments, for example final water-speed ATV action or major rafting/waterfall payoff scenes.
- Reserves early selection slots for high-value memory/social clips from distinct source videos, so short pool, water, group, celebration, restaurant, or Savaya clips are not crowded out by chronological filler.
- Balances normal-speed and speed-ramp candidates for later reel use.
- Caches segment audits so slow inspection is not repeated unnecessarily.
- Uses optional OpenCLIP semantic embeddings to suppress repeated same-layout/same-person scenes and to reject person-focused clips where no usable face is visible.
- Preserves high-confidence pool/water/scenic/people clips for memory/social activities before applying repetition reduction, while still rejecting weak person-focused clips with no useful face or activity context.
- Renders a 16:9 master activity timeline when executed.

The current frame audit uses OpenCV-derived signals:

- Face confidence and face count from YuNet.
- Water, mud, greenery, dark/tunnel, orange/light, gray-floor, and vehicle-like color/shape ratios.
- Edge density and motion/audio context from upstream Video Processing.
- Activity-specific tags such as `water_speed_run`, `mud_water_run`, `lit_tunnel`, `river_scene`, `river_people`, `group_reaction`, and `jungle_trail`.

The current semantic pass uses OpenCLIP:

- Samples representative frames from each selected candidate window.
- Encodes frames with OpenCLIP `ViT-B-32` / `openai`.
- Encodes text prompts for person-focused and scene-focused concepts.
- Uses cosine similarity to identify person-focused clips without faces.
- Uses embedding similarity to suppress repeated neighboring clips with nearly identical visual layout.
- Caches embeddings in `semantic_embedding_cache.json` so reruns are faster.

Important design rule: video renderers do not auto-rotate clips. If a clip only works after rotation, it is treated as unsuitable for the selected timeline or reel and should be rejected upstream.

### Outputs

Per activity:

```text
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_candidates.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_edit_decisions.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_manifest.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_report.md
```

Rendered activity timeline:

```text
input_data/trips/<trip>/curated/08 Selected Timeline/exports/*.mp4
```

### Enhancements

Useful future libraries and techniques:

- Dense frame embeddings with CLIP and FAISS.
- Learned event detectors for tunnel, water crossing, rapids, splash, dancing, food, temple details.
- VLM-based "best part of this video" ranking.
- Better face/body visibility scoring.
- Optical-flow-based excitement scoring.
- Camera horizon and ground/floor rejection models.

## Phase 09: Reel Builder

### Purpose

Reel Builder creates vertical Instagram-style reels per activity.

It does not analyze raw media from scratch. It consumes Selected Timeline and Video Processing outputs.

### Current Variants

Each activity can produce up to two reel outputs:

- `rank_01_instagram_reel`: short reel, configured around 90 seconds.
- `rank_02_full_highlight`: longer highlight reel, configured around 180 seconds.

The full highlight can be skipped for short activities where there is not enough source material.

### Inputs

```text
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
MemoryCurator/07 Video Processing/<stage>/<activity>/*.csv
MemoryCurator/05 Story Builder/<activity>/*.csv
```

### Processing

Reel Builder:

- Runs per activity.
- Keeps scene order chronological.
- Selects from already curated timeline segments.
- Builds a 9:16 vertical edit.
- Uses center crop to fill the screen and avoid top/bottom black bars.
- Uses candidate-level crop anchors where available.
- Mixes normal speed and speed-ramped sections.
- Caps Instagram playback speed to avoid uncomfortable 5x-style motion.
- Uses a configured maximum playback speed around 2.35x for short reels and around 2.75x for full highlights.
- Avoids black transition gaps.
- Supports configurable music placeholders.
- Supports natural audio for configured activities such as rafting and ATV.
- Supports phrase muting to remove action-camera commands like "GoPro stop recording".
- Writes edit decision CSVs before or during rendering.

Natural audio config:

```yaml
reel_builder:
  render:
    music:
      enabled: no
      path: null
      volume: 0.85
    natural_audio:
      enabled_media_sets: [rafting, atv]
      source_audio_volume: 1.6
      mute_phrases:
        - gopro start recording
        - go pro stop recording
      mute_phrase_padding_seconds: 0.45
      mute_action_camera_boundary_seconds: 2.8
```

### Outputs

Per activity and variant:

```text
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_candidates.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_selection.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_edit_decisions.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_manifest.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_report.md
```

Rendered reels:

```text
input_data/trips/<trip>/curated/09 Reel Builder/exports/*.mp4
```

### Enhancements

Useful future libraries and techniques:

- Beat-synced editing to music.
- OpenAI/VLM-based reel critique and auto-regeneration.
- Face-aware crop tracking for vertical video.
- Smart reframing with MediaPipe, YOLO, or object tracking.
- Scene transition models for smoother cuts.
- Automatic soundtrack selection by activity mood.
- User A/B feedback: pick favorite reel, then train future rankings.

## Phase 10: Documentary Builder

### Purpose

Documentary Builder tells the trip story as a long-form memory film.

It should not decide which clips are technically good. That work has already been done by Inventory, Duplicate Detection, Quality Scoring, Story Builder, Album Builder, Video Processing, and Selected Timeline.

The documentary answers:

```text
How do I tell the best story?
```

### Philosophy

The documentary is not a random file dump or a choppy highlight reel. For travel memories, the current preferred mode is:

```text
activity_chronological
```

That means the film follows the real trip/activity order using capture metadata, while each activity section still feels like a documentary chapter with action, people, beauty, natural audio, and continuity.

It should feel closer to:

```text
Waterfall -> ATV -> Rice Field -> Restaurants -> Rafting -> Stay -> Temple -> Beach -> Clubbing
```

The exact order is data-driven by default and can be overridden with `documentary_builder.activity_order` when the trip owner knows the correct itinerary.

### Inputs

```text
MemoryCurator/05 Story Builder/moments.csv
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/06 Album Builder/album_manifest.csv
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
```

### Processing

Documentary Builder:

- Filters all inputs to the enabled activities in the trip config, so stale renamed folders such as an old `savaya` output cannot leak into a new `clubbing` documentary.
- Prefers `MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv` when `documentary_builder.prefer_selected_timeline: yes`.
- Uses Video Processing timeline rows as a fallback/fill source when selected timelines do not provide enough coverage.
- Orders activities with robust chronology based on the median selected-timeline capture timestamp, not the earliest single asset, because mixed GoPro/iPhone/WhatsApp/tour-company files can contain timestamp outliers.
- Preserves chronological order inside each activity chapter using Inventory capture dates, then source path and segment start time as fallbacks.
- Balances activities using configured coverage, target duration, and available selected timeline duration.
- Renders a 16:9 documentary with FFmpeg/imageio-ffmpeg when configured.

Example documentary config:

```yaml
documentary_builder:
  target_duration_minutes: 90
  story_mode: activity_chronological
  activity_order: []
  prefer_selected_timeline: yes
  selected_timeline_min_fraction: 0.55
  coverage:
    min_events_per_activity: 8
  render:
    enabled: yes
```

### Outputs

```text
MemoryCurator/10 Documentary Builder/documentary_story.csv
MemoryCurator/10 Documentary Builder/documentary_chapters.csv
MemoryCurator/10 Documentary Builder/documentary_timeline.csv
MemoryCurator/10 Documentary Builder/documentary_manifest.csv
MemoryCurator/10 Documentary Builder/documentary_treatment.md
```

Rendered documentary:

```text
input_data/trips/<trip>/curated/10 Documentary Builder/exports/*.mp4
```

### Enhancements

Useful future libraries and techniques:

- LLM story treatment generation.
- LLM narration and chapter title generation.
- Voiceover generation.
- Transcript-based emotional beats.
- Music bed selection per chapter.
- Conflict/resolution detection from timeline semantics.
- Documentary critique loop: generate edit, ask model to identify choppy sections, revise.

## Phase 11: Time Capsule

### Purpose

Time Capsule is the long-term preservation layer.

Unlike reels or albums, Time Capsule should optimize for preserving meaning, not just selecting the most beautiful or exciting files.

### Current Status

Placeholder only.

### Future Outputs

Suggested outputs:

```text
MemoryCurator/11 Time Capsule/time_capsule_manifest.csv
MemoryCurator/11 Time Capsule/people_index.csv
MemoryCurator/11 Time Capsule/place_index.csv
MemoryCurator/11 Time Capsule/search_index.json
MemoryCurator/11 Time Capsule/trip_memory_book.md
```

### Enhancements

Useful future libraries and techniques:

- Full semantic search over all media.
- Face/person index.
- Transcript search.
- Location timeline.
- "Ask my trip" RAG interface.
- Long-term archival export with checksums.
- AI-generated memory book with quotes, captions, and reflections.

## Reports and Manifests as Contracts

The pipeline is built around handoff files:

```text
Inventory CSVs
  -> keeper_manifest.csv
  -> quality_manifest.csv
  -> story_manifest.csv + moment_assets.csv
  -> album_manifest.csv
  -> video_timeline.csv + clip_scores.csv
  -> selected_timeline.csv
  -> reel_manifest.csv
  -> documentary_manifest.csv
```

This makes the pipeline inspectable. If a reel misses an important section, inspect:

1. Was the source video included in inventory?
2. Did duplicate detection preserve it?
3. Did quality scoring select it?
4. Did Video Processing score its clips correctly?
5. Did Selected Timeline choose the important segment?
6. Did Reel Builder compress or skip it?

## Dry Run and Execute Behavior

Dry run is the default for many phases. Dry run writes reports but avoids final generated media where appropriate.

`--execute` finalizes phase outputs:

- Duplicate Detection: final reports and keeper manifest. No media moved.
- Quality Scoring: final reports and quality manifest. No media moved.
- Story Builder: final reports and story manifests. No media moved.
- Album Builder: generates PDF albums. Does not copy all selected photos.
- Video Processing: generates configured artifacts where enabled.
- Selected Timeline: renders master activity timeline videos.
- Reel Builder: renders reels.
- Documentary Builder: renders documentary if enabled.

## Reset Behavior

```bash
python3 -m memory_curator_engine reset
python3 -m memory_curator_engine reset --execute
```

Reset previews or removes known generated workflow outputs. It is designed to return the project to a clean generated state while preserving originals.

Original source media under `input_data/trips/<trip>/data` should remain untouched.

## Parallel Execution

The config supports per-phase worker settings:

```yaml
execution:
  parallel: yes
  workers: auto
  phases:
    video_processing:
      parallel: yes
      workers: auto
    reel_builder:
      parallel: yes
      workers: 4
```

This is local worker parallelism, not external multi-agent orchestration. Future product versions can add multi-agent execution for independent activity analysis, but the file contracts should remain the same.

## AI and LLM Extension Strategy

The current project intentionally avoids making AI mandatory. The recommended architecture is:

1. Use deterministic Python and metadata first.
2. Use OpenCV/FFmpeg/audio libraries for low-cost signal extraction.
3. Cache all expensive analysis.
4. Use AI only where it adds semantic understanding.
5. Store AI outputs as CSV/JSON manifests so downstream phases remain reproducible.

Recommended AI extension points:

- Story Builder: LLM moment titles, moment summaries, story arc classification.
- Media Intelligence: VLM captions, object detection, emotion/mood classification.
- Video Processing: VLM labels for sampled frames and timeline rows.
- Selected Timeline: "best segment" ranking from a VLM over candidate frames.
- Reel Builder: AI critique of generated edit decisions.
- Documentary Builder: story treatment, narration, chapter ordering, emotional arc.
- Time Capsule: searchable memory assistant over captions, transcripts, people, and places.

Possible backends:

- `none`: fully local/deterministic.
- `local_whisper`: local transcription.
- `openai`: OpenAI-hosted transcription, LLM, or vision models.
- Future: local VLMs, Ollama-compatible models, CLIP/OpenCLIP, YOLO, InsightFace.

## Adding a New Trip

Create:

```text
input_data/trips/<trip_slug>/
├── config/default.yaml
├── data/
│   ├── activity_1/
│   ├── activity_2/
│   └── activity_3/
└── curated/
```

Then update:

- `project.trip_slug`
- `project.trip_root`
- `project.data_root`
- `project.curated_root`
- `inventory.media_sets`
- `activity_profiles`
- module input/output paths if needed.

Run:

```bash
python3 -m memory_curator_engine --config input_data/trips/<trip_slug>/config/default.yaml run-all
```

## Current Product Roadmap

Near-term:

- Improve frame-level video introspection for all activities.
- Improve selected timeline ranking with learned or AI-assisted classifiers.
- Add configurable music bed support for reels.
- Improve vertical crop tracking around people and action.
- Add better transcript/mute phrase accuracy.
- Add stronger album duplicate diversity and person balancing.

Medium-term:

- Implement Media Intelligence as a real phase.
- Add local and OpenAI vision labeling.
- Add face/person clustering.
- Add semantic search.
- Add documentary narration and chapter generation.
- Add feedback-driven ranking.

Long-term:

- Build MemoryCurator as a generic open-source trip curation engine.
- Support pluggable backends for local AI, OpenAI APIs, and paid media intelligence services.
- Add UI for reviewing duplicate groups, moments, selected timelines, reels, and album pages.
