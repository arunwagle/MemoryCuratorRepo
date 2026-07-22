# Video Processing Engine Phase Prompt

Design and implement the Video Processing Engine for the MemoryCurator project.

This phase should not be treated as a single monolithic video module. It should be an internal semantic video pipeline used by downstream creative phases such as Reel Builder, Documentary Builder, Time Capsule, and Media Intelligence.

## Design Position

Video Processing is phase 07:

```text
MemoryCurator/07 Video Processing/
```

It should create structured understanding of videos. It should not behave like Adobe Premiere, and it should not focus on modifying footage.

No stabilization module should be included.

Reason:

- GoPro footage is already stabilized.
- Meta glasses footage is already stabilized.
- iPhone footage is already stabilized.
- This project is AI Media Curation, not manual post-production.
- The engine should understand media so later phases can make better creative decisions.

The relationship should be:

```text
Album Builder
        |
        v
Video Processing Engine
        |
        +-- Scene Detection
        +-- Clip Segmentation
        +-- Clip Scoring
        +-- Frame Analysis
        +-- Audio Analysis
        +-- Transcript Extraction
        +-- Timeline Builder
        |
        v
Reel Builder
        |
        v
Documentary Builder
```

More precisely, Video Processing should consume Story Builder and Quality Scoring outputs, then produce reusable video intelligence for:

- Reel Builder
- Documentary Builder
- Time Capsule
- Media Intelligence
- Search and review tools

## Folder Structure

Use this internal folder structure:

```text
MemoryCurator/07 Video Processing/
  scene-detection/
  clip-segmentation/
  clip-scoring/
  frame-analysis/
  audio-analysis/
  transcript/
  timeline-builder/
```

Generated media artifacts such as thumbnails, extracted clips, waveform images, or representative frames must go under the trip curated root:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/
```

Metadata, manifests, summaries, and reports go under:

```text
MemoryCurator/07 Video Processing/
```

Each stage must write aggregate CSVs for downstream contracts and activity-specific copies for review and per-activity consumers. Example:

```text
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/clip-scoring/rafting/clip_scores.csv
MemoryCurator/07 Video Processing/clip-scoring/atv/clip_scores.csv
```

Clip scoring must use the activity profile configured for each media set when available, such as `inventory.media_sets.rafting.activity_profile: rafting`.

Original source media must never be moved, deleted, renamed, or edited.

## Core Rule

Downstream creative builders should not re-analyze raw videos.

They should consume Video Processing outputs:

- Reel Builder asks for top clips.
- Documentary Builder asks for story-rich timeline sections.
- Time Capsule asks for meaningful audio/conversation/memory moments.
- Media Intelligence can consume frame-analysis outputs.

## Required Inputs

Required:

```text
MemoryCurator/03 Quality Scoring/quality_manifest.csv
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/moment_assets.csv
```

If a required upstream file is missing or empty, fail clearly:

```text
Missing upstream manifest: MemoryCurator/05 Story Builder/moment_assets.csv.
Run story-builder first.
```

Expected video rows should include:

- media_set
- media_path
- original_path
- file_type
- duration_seconds
- quality_score
- instagram_score
- movie_score
- moment_id
- role

Only video assets should be processed by this engine.

## Phase Commands

Run full dry run:

```bash
.venv/bin/python -B -m memory_curator_engine video-processing
```

Run full execute:

```bash
.venv/bin/python -B -m memory_curator_engine video-processing --execute
```

Run a single internal stage:

```bash
.venv/bin/python -B -m memory_curator_engine video-processing --stage scene-detection
.venv/bin/python -B -m memory_curator_engine video-processing --stage clip-segmentation
.venv/bin/python -B -m memory_curator_engine video-processing --stage clip-scoring
.venv/bin/python -B -m memory_curator_engine video-processing --stage frame-analysis
.venv/bin/python -B -m memory_curator_engine video-processing --stage audio-analysis
.venv/bin/python -B -m memory_curator_engine video-processing --stage transcript
.venv/bin/python -B -m memory_curator_engine video-processing --stage timeline-builder
```

Dry run should generate metadata and planned output paths without extracting clips or thumbnails unless configured to allow lightweight previews.

Execute mode may create generated media artifacts under the curated root.

## 07.1 Scene Detection

### Purpose

Split long videos into logical scenes.

Example:

```text
12-minute GoPro
  -> Walking
  -> River
  -> Raft
  -> Rapids
  -> Finish
```

Scene Detection should find larger semantic sections, not short social clips.

### Inputs

- Video assets from Story Builder / Quality Scoring manifests.
- Existing metadata: duration, quality scores, moment ids.
- Optional representative frames if already generated.

### Outputs

Metadata:

```text
MemoryCurator/07 Video Processing/scene-detection/scene_manifest.csv
MemoryCurator/07 Video Processing/scene-detection/scene_summary.md
```

Generated media:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/scene-detection/scene_thumbnails/
```

### `scene_manifest.csv` Columns

- media_set
- video_path
- original_path
- moment_id
- scene_id
- scene_index
- start_seconds
- end_seconds
- duration_seconds
- thumbnail_path
- scene_label
- confidence
- detection_method
- source_phase

### Implementation Notes

Use deterministic/local methods first:

- Detect shot or scene boundaries using OpenCV frame-difference thresholds.
- Use sampled frames rather than every frame.
- Cache/reuse per-video frame metrics inside a run so scene detection, clip scoring, and frame analysis do not resample the same video repeatedly.
- Fall back to coarse fixed-window segmentation when frame analysis is unavailable.

Optional AI can label scenes more richly, but it must not be required and must be disabled by default.

## 07.2 Clip Segmentation

### Purpose

Create candidate short clips from scenes.

Scene Detection finds:

```text
River
```

Clip Segmentation extracts candidate segments:

```text
Clip 1: 00:30-00:52
Clip 2: 01:10-01:28
Clip 3: 02:05-02:45
```

These clips should be usable by Reel Builder and Documentary Builder.

### Outputs

Metadata:

```text
MemoryCurator/07 Video Processing/clip-segmentation/clip_manifest.csv
MemoryCurator/07 Video Processing/clip-segmentation/clip_summary.md
```

Generated media in execute mode:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/clip-segmentation/clips/
```

### `clip_manifest.csv` Columns

- media_set
- video_path
- original_path
- moment_id
- scene_id
- clip_id
- clip_index
- start_seconds
- end_seconds
- duration_seconds
- planned_clip_path
- clip_path
- clip_type
- segmentation_reason
- source_phase

### Clip Types

- hero_candidate
- action
- reaction
- transition
- b_roll
- conversation
- establishing
- closing
- unknown

### Implementation Notes

Default candidate clip durations should be configurable:

- Reel clips: 5-20 seconds.
- Documentary clips: 15-90 seconds.
- Conversation clips: allow longer ranges when transcript/audio says it matters.

Execute mode may extract clips if `ffmpeg` is available. If `ffmpeg` is unavailable, write planned clip paths and clear extraction status.

## 07.3 Clip Scoring

### Purpose

Score every candidate clip so downstream builders can simply ask for the best clips.

Example:

```text
Clip:
  Quality: 95
  Action: 98
  People: 100
  Story: 94
  Overall: 97
```

Then Reel Builder can ask:

```text
Give me the top 12 clips.
```

### Outputs

```text
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/clip-scoring/top_clips.csv
MemoryCurator/07 Video Processing/clip-scoring/clip_scoring_summary.md
```

### `clip_scores.csv` Columns

- media_set
- clip_id
- video_path
- clip_path
- moment_id
- scene_id
- start_seconds
- end_seconds
- duration_seconds
- quality_score
- action_score
- people_score
- story_score
- audio_score
- activity_score
- activity_bucket
- reel_score
- documentary_score
- time_capsule_score
- overall_score
- recommended_uses
- scoring_reason
- source_phase

### Scoring Dimensions

Clip Scoring should consider:

- Technical quality from Quality Scoring.
- Motion/action from frame differences.
- Story importance from Story Builder moment type.
- People score from Media Intelligence if available.
- Audio value from Audio Analysis if available.
- Transcript value from Transcript if available.
- Duration suitability for reels and documentary.
- Activity Profile fit from trip config, such as rafting action/water/rapids/splash/GoPro/reaction signals.
- Diversity across moments and source videos.

For rafting, clip scoring should promote high-motion water/adventure clips for `reel_score` and `overall_score` even when technical quality is imperfect. The goal is to preserve the essence of the activity for Reel Builder and Documentary Builder.

Recommended uses:

- reel
- documentary
- time_capsule
- b_roll
- transition
- archive_only

## 07.4 Frame Analysis

### Purpose

Analyze representative frames, not every frame.

Recommended sampling:

- Every 1 second for short videos.
- Every 2-5 seconds for long videos.
- Keyframes from scene boundaries.
- Clip start/middle/end frames.

### Extract Tags

Frame Analysis should identify deterministic and future-AI-ready visual concepts:

- landscape
- people
- food
- beach
- ATV
- river
- temple
- vehicle
- indoor
- outdoor
- water
- action
- group
- selfie
- low_light
- blurry

In the first implementation, use deterministic metadata and image statistics where possible. Future AI can enrich tags.

### Outputs

Metadata:

```text
MemoryCurator/07 Video Processing/frame-analysis/frame_manifest.csv
MemoryCurator/07 Video Processing/frame-analysis/frame_tags.csv
MemoryCurator/07 Video Processing/frame-analysis/frame_analysis_summary.md
```

Generated media:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/frame-analysis/frames/
```

### `frame_manifest.csv` Columns

- media_set
- video_path
- moment_id
- scene_id
- clip_id
- frame_id
- timestamp_seconds
- frame_path
- width
- height
- brightness_score
- sharpness_score
- motion_context
- tags
- source_phase

## 07.5 Audio Analysis

### Purpose

Audio is important for memory.

Find:

- laughing
- cheering
- applause
- river noise
- music
- silence
- conversation
- crowd noise
- engine noise
- wind noise

This helps Time Capsule preserve meaningful sounds and conversations.

### Outputs

```text
MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
MemoryCurator/07 Video Processing/audio-analysis/audio_summary.md
```

Optional generated media:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/audio-analysis/waveforms/
```

### `audio_events.csv` Columns

- media_set
- video_path
- moment_id
- event_id
- start_seconds
- end_seconds
- duration_seconds
- audio_event_type
- intensity_score
- confidence
- detection_method
- notes
- source_phase

### Implementation Notes

Use deterministic signal features first. The implemented stack should prefer packaged FFmpeg from `imageio-ffmpeg`, then use Librosa/NumPy signal analysis:

- RMS loudness.
- Silence detection.
- Peaks/spikes.
- Audio energy changes.
- Zero-crossing rate.
- Spectral centroid.
- Conversation, cheering/laughing, loud reaction, river/action noise, wind/high-frequency noise, ambient audio, and silence/quiet candidates.

Audio analysis must use a per-video cache so reruns do not decode the same audio again. Cache identity should include source path, file size, modified time, duration, audio window seconds, and cache version.

Cache path:

```text
input_data/trips/<trip_slug>/curated/07 Video Processing/audio-analysis/cache/
```

Future AI/audio classifiers can improve event labeling, but the deterministic implementation should already produce useful signal-based audio event rows.

## 07.6 Transcript Extraction

### Purpose

Generate searchable captions, transcripts, and timestamps.

Example use:

```text
Show me where someone says "engineering".
```

### Tooling

Use Whisper or an equivalent transcription backend when configured.

This should be optional because transcription can be expensive and slow.

If no transcription backend is configured:

- Skip transcript extraction.
- Write a clear status report.
- Do not fail the whole Video Processing pipeline unless config marks transcript as required.

### Outputs

```text
MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
MemoryCurator/07 Video Processing/transcript/transcript_full_text.md
MemoryCurator/07 Video Processing/transcript/transcript_summary.md
```

### `transcript_segments.csv` Columns

- media_set
- video_path
- moment_id
- segment_id
- start_seconds
- end_seconds
- duration_seconds
- text
- language
- confidence
- speaker_label
- keywords
- source_phase

## 07.7 Timeline Builder

### Purpose

Timeline Builder creates the semantic layer for videos.

Example:

```text
00:00 Walking
00:35 Laughing
01:10 Rapids
02:20 Splash
03:00 Group
03:40 Calm River
```

Reel Builder should not analyze videos. It should consume the timeline.

Documentary Builder should also consume the timeline.

### Required Inputs

Timeline Builder should consume whichever upstream internal stage outputs are available:

- Scene Detection
- Clip Segmentation
- Clip Scoring
- Frame Analysis
- Audio Analysis
- Transcript Extraction
- Story Builder moments

### Outputs

```text
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.json
MemoryCurator/07 Video Processing/timeline-builder/timeline_summary.md
MemoryCurator/07 Video Processing/video_processing_manifest.csv
```

### `video_timeline.csv` Columns

- media_set
- video_path
- moment_id
- timeline_event_id
- event_index
- start_seconds
- end_seconds
- duration_seconds
- event_type
- event_label
- scene_id
- clip_id
- audio_event_id
- transcript_segment_id
- frame_ids
- story_importance_score
- reel_value_score
- documentary_value_score
- time_capsule_value_score
- notes
- source_phase

### `video_processing_manifest.csv`

This is the downstream contract for Reel Builder, Documentary Builder, and Time Capsule.

Columns:

- media_set
- video_path
- moment_id
- scene_manifest_path
- clip_manifest_path
- clip_scores_path
- frame_manifest_path
- audio_events_path
- transcript_segments_path
- timeline_path
- processing_status
- source_phase

## Config Shape

Trip config example:

```yaml
modules:
  video_processing:
    enabled: yes

project:
  curated_root: input_data/trips/sample/curated

video_processing:
  dry_run: yes
  input_quality_manifest: MemoryCurator/03 Quality Scoring/quality_manifest.csv
  input_story_manifest: MemoryCurator/05 Story Builder/story_manifest.csv
  input_moment_assets: MemoryCurator/05 Story Builder/moment_assets.csv
  output_dir: MemoryCurator/07 Video Processing
  curated_dir: input_data/trips/sample/curated/07 Video Processing
  overwrite_policy: fail
  stages:
    scene_detection:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/scene-detection
      thumbnails_dir: input_data/trips/sample/curated/07 Video Processing/scene-detection/scene_thumbnails
      target_scene_seconds: 45
      thumbnail_on_execute: no
    clip_segmentation:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/clip-segmentation
      clips_dir: input_data/trips/sample/curated/07 Video Processing/clip-segmentation/clips
      extract_on_execute: no
      reel_clip_seconds: 12
      documentary_clip_seconds: 45
    clip_scoring:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/clip-scoring
      top_clip_count: 24
    frame_analysis:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/frame-analysis
      frames_dir: input_data/trips/sample/curated/07 Video Processing/frame-analysis/frames
      sample_every_seconds: 5
      extract_on_execute: no
    audio_analysis:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/audio-analysis
      waveforms_dir: input_data/trips/sample/curated/07 Video Processing/audio-analysis/waveforms
      waveform_on_execute: no
      cache_enabled: yes
      window_seconds: 5
    transcript:
      enabled: yes
      required: no
      backend: none  # none | local_whisper | openai
      local_model: base
      model: gpt-4o-transcribe
      output_dir: MemoryCurator/07 Video Processing/transcript
      audio_dir: input_data/trips/sample/curated/07 Video Processing/transcript/audio
    timeline_builder:
      enabled: yes
      output_dir: MemoryCurator/07 Video Processing/timeline-builder
      ai:
        enabled: no
        required: no
        model: gpt-5.2-mini
        endpoint: https://api.openai.com/v1/responses
```

## Execution Rules

Dry run:

- Validate inputs.
- Build metadata and planned output paths.
- Do not extract clips, frames, thumbnails, waveforms, or transcripts unless explicitly configured for preview generation.
- Never move/delete/edit originals.

Execute:

- May generate thumbnails, frames, clips, waveforms, and transcripts under curated root.
- Must keep all metadata under `MemoryCurator/07 Video Processing/`.
- Must never move/delete/edit originals.
- Must never overwrite existing different generated files unless config allows it.

## Implementation Notes

Recommended package:

```text
memory_curator_engine/video/
  __init__.py
  report.py
  scene_detection.py
  clip_segmentation.py
  clip_scoring.py
  frame_analysis.py
  audio_analysis.py
  transcript.py
  timeline_builder.py
```

Use the dependencies from `requirements.txt`:

- OpenCV for frame sampling and shot/scene changes.
- `imageio-ffmpeg` for a packaged FFmpeg binary when system `ffmpeg` is unavailable.
- MoviePy for future higher-level clip operations.
- Librosa, SoundFile, SciPy, and NumPy for audio signal analysis.
- Whisper for transcripts when configured.

Use standard-library fallbacks where possible:

- Coarse time-window segmentation.
- Metadata-only scoring.
- Planned output paths without media extraction.

The requirements file should include:

```text
Pillow>=10.0
pillow-heif>=0.15
ImageHash>=4.3
opencv-python>=4.9
imageio-ffmpeg>=0.6
moviepy>=2.2
librosa>=0.11
soundfile>=0.14
```

## Acceptance Criteria

- Video Processing is implemented as an internal pipeline, not one monolithic module.
- Stabilization is not included.
- Missing Story/Quality manifests fail clearly.
- Each internal stage can run individually.
- Full phase can run stages in dependency order.
- Dry run generates metadata and planned paths without media extraction.
- Scene Detection uses OpenCV frame-difference detection when available and reports the detection method.
- Frame Analysis writes real brightness, sharpness, motion context, and visual tags when OpenCV is available.
- Audio Analysis uses packaged FFmpeg plus Librosa signal features when available and reports the detection method.
- Audio Analysis caches per-video results and reports cache hits/writes in `audio_summary.md`.
- Transcript supports config-driven `backend: none | local_whisper | openai`.
- Timeline Builder can optionally refine event labels with AI, but AI is disabled by default and must never be required unless config says so.
- Execute mode writes generated media only under `input_data/trips/<trip_slug>/curated/07 Video Processing/`.
- Original videos are never moved, deleted, renamed, or edited.
- `video_processing_manifest.csv` is generated as the downstream contract.
- Reel Builder and Documentary Builder can consume the timeline and clip scores without re-analyzing videos.
