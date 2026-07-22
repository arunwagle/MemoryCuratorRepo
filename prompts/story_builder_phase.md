# Story Builder Phase Prompt

Design and implement the Story Builder phase for the MemoryCurator project.

Implement Story Builder with Python-first moment classification. The first pass should build deterministic candidate moments and classify them against an activity-specific taxonomy using timestamps, filenames, media mix, metadata, and quality scores. OpenAI should be an optional refinement step for ambiguous moments or richer titles/moods, not the default path.

## Design Position

Story Builder should remain its own top-level phase:

```text
MemoryCurator/05 Story Builder/
```

Do not move Story Builder inside Video Processing.

Reason:

- Story moments are useful for albums, reels, documentary videos, and time capsules.
- Video Processing should consume the Story Builder output to perform scene detection, clip segmentation, clip scoring, frame analysis, audio analysis, transcript extraction, and timeline building.
- Album Builder should also consume the same story moments for photo sequencing and page grouping.
- Reel Builder and Documentary Builder should use moments as narrative units rather than raw files.

The relationship should be:

```text
Quality Scoring -> Story Builder -> Album Builder
                              -> Video Processing -> Reel Builder
                                                  -> Documentary Builder
                              -> Time Capsule
```

## Context

- This is a generic media curation engine.
- Trip-specific config lives under folders such as `input_data/trips/bali/config/default.yaml`.
- Workflow outputs go under the configured `MemoryCurator/` workflow root.
- Each phase must consume an upstream manifest and generate a manifest for the next phase.
- Story Builder consumes the quality-selected media manifest:

```text
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

- Media Intelligence is optional and may be skipped.
- If Media Intelligence outputs exist, Story Builder can enrich moments with people, mood, captions, and descriptions.
- If Media Intelligence is skipped, Story Builder must still work using timestamps, filenames, metadata, quality scores, purpose scores, activity scores, and media types.
- Story Builder must use the configured Activity Profile. For rafting, high-action/water/GoPro/POV clips should be allowed to classify as `rapids`, `water_action`, or `splash` even when timestamp or title hints would otherwise classify them as transition footage.
- Python classification is the default path and should not use tokens.
- OpenAI classification is optional and requires `OPENAI_API_KEY` only when enabled.
- A `--ai` option may be provided to request LLM refinement.
- Original source media must never be deleted.
- Dry run must not move, delete, rename, or edit source media.

## Mental Model

The user does not remember hundreds of individual files. The user remembers moments.

Example raw assets:

- 300 photos
- 40 GoPro videos
- 25 Meta videos
- 30 iPhone videos

Example remembered moments:

- Leaving Villa
- Coffee Stop
- Arriving at Rafting Center
- Safety Briefing
- Putting on Helmets
- Walking to River
- Launching Raft
- First Rapids
- Big Splash
- Group Photo
- Lunch
- Drive Home

Story Builder turns individual media assets into a reviewable Moment database.

## Phase Goal

Create a config-driven Story Builder that:

- Reads `quality_manifest.csv`.
- Fails fast if `quality_manifest.csv` is missing or empty.
- Optionally reads Media Intelligence enrichment files if present.
- Groups media into moments using deterministic signals.
- Uses Python heuristics to classify candidate moments into activity-specific moment types.
- Optionally uses OpenAI to refine classifications, titles, moods, and notes.
- Scores moments for album, reel, documentary, and time capsule usefulness.
- Selects hero photo and hero video per moment when available.
- Generates reviewable CSV and JSON outputs.
- Generates `story_manifest.csv` as the downstream phase contract.
- Does not move media files in the first implementation unless a later design explicitly asks for curated moment folders.

## Commands

Dry run is the default:

```bash
.venv/bin/python -B -m memory_curator_engine story-builder
```

Optional OpenAI refinement:

```bash
export OPENAI_API_KEY="..."
.venv/bin/python -B -m memory_curator_engine story-builder --ai
```

## Required Input

Required:

```text
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

If this file is missing or empty, Story Builder must stop with a clear error:

```text
Missing upstream manifest: MemoryCurator/03 Quality Scoring/quality_manifest.csv.
Run quality-scoring first.
```

Expected quality manifest fields:

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

Optional enrichment inputs:

```text
MemoryCurator/04 Media Intelligence/...
```

Optional enrichment can include:

- detected people/person IDs
- mood or emotion tags
- captions/descriptions
- landmarks or objects
- transcript snippets

If optional enrichment files are missing, Story Builder must continue without them.

## Outputs

Write outputs to:

```text
MemoryCurator/05 Story Builder/moments.csv
MemoryCurator/05 Story Builder/moments.json
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/story_review.csv
```

`story_manifest.csv` is the downstream contract. Later phases should read this instead of re-grouping raw media.

## Moment Model

Each moment should have a stable ID and enough information for downstream builders.

Example:

```json
{
  "id": "rafting_008",
  "title": "First Rapids",
  "activity": "Rafting",
  "start_time": "10:32",
  "end_time": "10:39",
  "people": ["Arun", "Sunil", "Arindam", "Santosh"],
  "assets": [
    "IMG001.jpg",
    "IMG002.jpg",
    "GOPR0102.mp4",
    "META008.mp4"
  ],
  "hero_photo": "IMG001.jpg",
  "hero_video": "GOPR0102.mp4",
  "mood": "Excitement",
  "score": 97
}
```

The implementation may leave fields blank or deterministic when AI/enrichment is unavailable:

- people: empty list or person IDs if available
- mood: inferred only from deterministic tags or blank/unknown
- title: deterministic generated title such as `Rafting Moment 008`, unless configured title hints exist

## Grouping Logic

Moment grouping should be deterministic and reviewable.

Recommended grouping signals:

- media_set/activity
- capture timestamp
- time gaps between assets
- file source/device hints from filenames such as GoPro, Meta, iPhone when available
- media type mix
- quality score concentration
- optional Media Intelligence tags when available

Default grouping approach:

- Sort assets by capture timestamp.
- Group independently per media set/activity; never merge moments across activities.
- Use `inventory.media_sets.<name>.activity_name` and `activity_profile` for moment IDs, titles, taxonomy, and scoring.
- Start a new moment when the time gap exceeds a configurable threshold.
- Use a shorter threshold for action-heavy activities and a longer threshold for travel/waiting segments.
- Allow minimum and maximum moment duration.
- Merge tiny adjacent moments when they have too few assets and are close in time.
- Split very large moments when they exceed maximum duration or asset count.

Example config:

```yaml
modules:
  story_builder:
    enabled: yes

story_builder:
  dry_run: yes
  input_manifest: MemoryCurator/03 Quality Scoring/quality_manifest.csv
  output_dir: MemoryCurator/05 Story Builder
  activity_name: Trip
  moment_id_prefix: moment
  max_gap_seconds: 300
  action_gap_seconds: 120
  min_assets_per_moment: 2
  max_assets_per_moment: 40
  min_moment_duration_seconds: 15
  max_moment_duration_seconds: 900
  merge_small_moments: yes
  activities:
    rafting:
      target_moment_count: 12
      title_hints:
        - Arriving at Rafting Center
        - Putting on Helmets
        - Walking to River
        - Launching Raft
        - First Rapids
        - Big Splash
        - Group Photo
    beach:
      title_hints:
        - Arriving at the Beach
        - Ocean Views
        - Beach Walk
        - Sunset Moments
```

## Moment Scoring

Each moment should receive:

- `moment_score`
- `album_score`
- `reel_score`
- `documentary_score`
- `time_capsule_score`

Scoring should consider:

- average and max quality score
- presence of a hero photo
- presence of a hero video
- variety of assets
- video duration available for documentary use
- Instagram/reel suitability from Quality Scoring
- album suitability from Quality Scoring
- activity fit and purpose scores from Quality Scoring
- chronological importance
- optional people/mood/caption tags when available

No subjective AI judgment should be used in the first implementation.

## Hero Selection

Hero photo:

- Prefer selected photos with high `album_score`.
- Prefer sharp, well-exposed, high-resolution photos.
- Prefer assets near the middle of the moment when there are multiple similar files.

Hero video:

- Prefer selected videos with high `movie_score`.
- Prefer stable videos with useful duration.
- Prefer action-rich clips for adventure moments.
- Avoid extremely short videos unless no better video exists.

## Output Schemas

`moments.csv`:

- moment_id
- media_set
- activity
- title
- start_time
- end_time
- duration_seconds
- asset_count
- photo_count
- video_count
- hero_photo
- hero_video
- people
- mood
- moment_score
- album_score
- reel_score
- documentary_score
- time_capsule_score
- notes

`moment_assets.csv`:

- moment_id
- media_set
- media_path
- original_path
- file_type
- captured_at
- duration_seconds
- quality_score
- album_score
- instagram_score
- movie_score
- role: hero_photo, hero_video, supporting, b_roll, montage

`story_manifest.csv`:

- moment_id
- media_set
- activity
- title
- start_time
- end_time
- hero_photo
- hero_video
- asset_count
- photo_count
- video_count
- moment_score
- album_score
- reel_score
- documentary_score
- time_capsule_score
- source_phase

`story_review.csv`:

- moment_id
- title
- start_time
- end_time
- asset_count
- hero_photo
- hero_video
- review_status
- review_notes

`moments.json`:

- Full nested moment representation.
- Include moment metadata plus ordered asset list.
- Suitable for future UI review or AI narrative modules.

## Optional AI Moment Classification

Use OpenAI only after deterministic grouping and Python classification. This should be optional so routine runs do not spend tokens.

For each candidate moment, send:

- activity name
- allowed moment taxonomy
- deterministic title fallback
- start and end time
- photo/video counts
- hero photo/video paths
- ordered asset summaries including filenames, media type, capture time, duration, quality scores, and recommended uses

The model should return structured JSON:

- title
- moment_type
- mood
- confidence
- notes

The returned `moment_type` must be one of the configured taxonomy values or `other`. If OpenAI returns a type outside the taxonomy, normalize it to `other`.

If `--ai` or `story_builder.ai.enabled: yes` is used and `story_builder.ai.required: yes`, then missing `OPENAI_API_KEY` should fail clearly:

```text
OPENAI_API_KEY is required for AI Story Builder. Set it or run story-builder without --ai.
```

## Naming And Title Strategy

First implementation:

- Use configured `activity_name`.
- Use configured `moment_id_prefix`.
- Generate deterministic IDs such as `rafting_001`, `rafting_002`.
- Use `title_hints` in chronological order when the number of detected moments is close to the number of hints.
- Otherwise generate titles like:
  - `Rafting Moment 001`
  - `Rafting Moment 002`

OpenAI enhancement:

- Generate richer titles from the moment taxonomy, filenames, timing, quality metadata, captions, detected scenes, transcripts, and user-provided names when available.

## Phase Optionality

Story Builder itself should be configurable:

```yaml
modules:
  story_builder:
    enabled: yes
```

When running:

```bash
.venv/bin/python -B -m memory_curator_engine run-all --skip story-builder
```

the phase should be skipped and downstream phases that require `story_manifest.csv` should fail clearly unless they are also skipped.

## Reset Compatibility

The first implementation should be report/manifest only and should not move media files.

Project-level reset should clean:

```text
MemoryCurator/05 Story Builder/
```

as part of workflow-root cleanup.

## Architecture

- Keep reusable implementation under `memory_curator_engine/story/`.
- Reuse common path, config, media, and CSV helpers.
- Use OpenAI for activity-specific moment classification.
- Keep grouping and scoring deterministic.
- Make the moment model extensible for future AI enrichment.
- Keep phase compatible with:
  - `.venv/bin/python -B -m memory_curator_engine story-builder`
  - `.venv/bin/python -B -m memory_curator_engine run-all --skip media-intelligence`

## Verification

Run:

```bash
.venv/bin/python -B -m compileall -q memory_curator_engine
.venv/bin/python -B -m memory_curator_engine story-builder --no-ai
```

Verify:

- Missing `OPENAI_API_KEY` fails clearly when AI is enabled.
- Missing `quality_manifest.csv` fails clearly.
- Reports are generated under `MemoryCurator/05 Story Builder/`.
- `story_manifest.csv` exists and contains moment rows.
- `moment_assets.csv` maps every selected media asset to a moment.
- `moments.json` contains full nested moment data.
- No media files are moved.
