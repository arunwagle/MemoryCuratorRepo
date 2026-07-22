# Documentary Builder Phase Prompt

Design and implement the Documentary Builder phase for MemoryCurator.

## Core Philosophy

Documentary Builder must never decide whether raw media is good.

That decision belongs to upstream phases:

- Inventory
- Duplicate Detection
- Quality Scoring
- Media Intelligence
- Story Builder
- Album Builder
- Video Processing

Documentary Builder answers one question:

> How do I tell the best story?

Think like a Netflix documentary editor, not a file sorter.

The documentary can use either a classic story arc or a trip/activity chronological structure. For trip memories, the preferred current mode is `activity_chronological`: preserve the real order of activities using capture metadata and selected timeline chronology, while making each activity section feel like a coherent chapter.

The documentary should not feel like:

- a random file dump
- a choppy highlight reel
- generic Day 1 / Day 2 / Day 3 sections with no emotional flow

It should feel like:

- the trip unfolding in the order it was experienced
- detailed activity chapters
- strong action and emotional sections
- calm breathing-room moments
- a closing memory

The audience should feel like they went on the trip.

## Continuity Rule

The documentary must flow continuously. It should not feel like a choppy highlight reel.

Use:

- Longer documentary scenes than reels.
- Same-moment runs when possible.
- Bridge shots between chapters.
- Natural audio for action and emotion.
- Fewer hard cuts inside each chapter.
- Chapter transitions that explain why the story is moving.

## Phase Position

Documentary Builder is phase 10:

```text
MemoryCurator/10 Documentary Builder/
```

It consumes upstream metadata and selected assets. It does not analyze raw media.

Important: the preferred source for video content is `MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv`. Selected Timeline has already inspected candidate video windows, rejected weak/filler clips, preserved activity-specific highlights, and rendered activity master timelines. Documentary Builder should use that as the chapter source when `documentary_builder.prefer_selected_timeline: yes`, then fill with Video Processing timeline rows only when extra coverage is needed.

When filling from Video Processing, never include a raw timeline row that overlaps a selected timeline row from the same source video. Otherwise the documentary will show a broad raw scene and then immediately repeat the selected sub-scene from inside it.

It is both a planning and rendering phase:

- Dry run writes the story plan, chapter plan, timeline, manifest, and treatment.
- Execute mode writes the same metadata and renders the final documentary MP4 when `documentary_builder.render.enabled: yes`.
- Rendered documentary media must live under the trip curated root, not under `MemoryCurator/`.

## Required Inputs

```text
MemoryCurator/05 Story Builder/moments.csv
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
```

Recommended:

```text
MemoryCurator/06 Album Builder/album_manifest.csv
MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
MemoryCurator/04 Media Intelligence/
```

If required upstream manifests are missing, fail clearly and tell the user which phase to run.

## Outputs

```text
MemoryCurator/10 Documentary Builder/documentary_story.csv
MemoryCurator/10 Documentary Builder/documentary_chapters.csv
MemoryCurator/10 Documentary Builder/documentary_timeline.csv
MemoryCurator/10 Documentary Builder/documentary_manifest.csv
MemoryCurator/10 Documentary Builder/documentary_treatment.md
```

Rendered media output:

```text
input_data/trips/<trip_slug>/curated/10 Documentary Builder/exports/<documentary_id>.mp4
```

## Rendering Requirements

The documentary renderer should use FFmpeg, preferring the packaged `imageio-ffmpeg` binary when a system `ffmpeg` is not available.

Rendering should:

- Read only the selected `documentary_timeline.csv` segments.
- Trim selected source segments.
- Normalize output to landscape 1920x1080.
- Encode H.264 video and AAC stereo audio.
- Preserve source audio when available.
- Fall back to muted rendering for individual source segments with unsupported or malformed audio.
- Concatenate normalized segments into the final MP4.
- Never move, delete, rename, or edit originals.

## Duration Rules

Do not invent duration. Planned documentary duration must use the real available source duration from Video Processing timeline rows.

If a clip is shorter than the preferred documentary scene length, keep it short. Do not inflate the planned timeline beyond the real source segment, because the rendered MP4 will stop at the real media duration.

Chapter target duration should be rebalanced when a chapter has limited available source material. Underfilled setup, people, or reflection chapters may donate unused duration to stronger adventure, peak action, and calm beauty chapters.

## Activity Coverage

For a trip-level documentary, every enabled activity with usable Video Processing timeline rows should be represented when `documentary_builder.coverage.min_events_per_activity` is greater than zero.

Coverage should not override basic quality, but it should prevent activities such as ATV, Clubbing/Savaya, restaurants, rice fields, or waterfall from silently disappearing because a few other activities have more footage.

Documentary Builder must filter inputs to currently enabled trip activities. If an activity folder is renamed, such as `Savaya` to `Clubbing`, stale old selected-timeline folders must not leak into the new documentary.

## Chronology Rules

Use robust chronology:

- Prefer selected timeline rows for activity ordering when available.
- Use Inventory capture metadata from embedded camera timestamps where possible.
- Use a median/center selected-timeline timestamp for activity order instead of the earliest single asset, because mixed sources can contain bad outlier dates from GoPro, WhatsApp, copied files, or tour-company media.
- Preserve chronological order inside each activity section.
- Allow `documentary_builder.activity_order` to override automatic ordering when a trip owner knows the real itinerary.
- If capture metadata is missing, fall back to source path and segment start time.

Recommended config:

```yaml
documentary_builder:
  target_duration_minutes: 90
  coverage:
    min_events_per_activity: 8
  story_mode: activity_chronological
  activity_order: []
  prefer_selected_timeline: yes
  selected_timeline_min_fraction: 0.55
  render:
    enabled: yes
    exports_dir: input_data/trips/sample/curated/10 Documentary Builder/exports
    width: 1920
    height: 1080
    fps: 30
    crf: 21
    preset: veryfast
    overwrite_policy: replace
```
