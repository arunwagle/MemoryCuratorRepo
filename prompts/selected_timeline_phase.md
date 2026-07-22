# Selected Timeline Phase Prompt

Design and implement the Selected Timeline phase for MemoryCurator.

## Goal

Create a canonical best timeline for each activity before Reel Builder and Documentary Builder run.

Selected Timeline should answer:

```text
What are the best chronological moments of this activity, and where are the strongest sub-windows inside each source video?
```

It should produce both:

- a reusable `selected_timeline.csv`
- an optional 16:9 master activity video for review and documentary use

## Design Position

Selected Timeline is phase 08:

```text
MemoryCurator/08 Selected Timeline/
```

The workflow becomes:

```text
Inventory
  -> Duplicate Detection
  -> Quality Scoring
  -> Story Builder
  -> Video Processing
  -> Selected Timeline
  -> Reel Builder
  -> Documentary Builder
```

Reel Builder should create vertical style variants from selected timeline intelligence. Documentary Builder should use selected timelines as activity chapter sources.

## Philosophy

Do not hardcode file names.

Use:

- activity folder/media set
- activity profile
- source chronology from Inventory `capture_date`, then filesystem fallback dates, then filename fallback
- timeline events
- clip scores
- frame-audit visual tags
- local face/person visibility signals when the activity profile values friends, people, groups, memory, or emotion
- audio energy
- motion and clarity
- source audio, when the activity benefits from natural ambient sound
- optional CLIP/OpenCLIP visual embeddings for semantic similarity across separate clips

For ATV, the selected timeline should naturally discover mud, lit tunnels, shaded tunnels, slopes, turns, jungle trails, muddy-water runs, water-speed runs, rough motion, speed, and good POV windows. For rafting, it should prioritize rapids, splash, river action, GoPro POV, and group reactions. For beach, stay, restaurants, Savaya, temple, rice-field, and other memory/social/cinematic activities, it should preserve clips with visible friends/groups when they match the activity profile.

## Outputs

```text
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_candidates.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_edit_decisions.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_manifest.csv
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline_report.md
input_data/trips/<trip>/curated/08 Selected Timeline/exports/<activity>/<trip>_<activity>_selected_timeline_master_16x9.mp4
```

## Rules

- Never move, delete, rename, or edit original media.
- Preserve activity chronology using Inventory `capture_date` across cameras before falling back to `created_date`, `modified_date`, or filename order.
- Preserve first-chronological-wins behavior after filtering. Do not hide bad openings by reordering; reject weak segments before they enter Selected Timeline.
- Select multiple strong sub-windows from long source videos when they contain different important events.
- Reject wrong-activity leakage using activity profiles and visual audit tags.
- Reject weak/non-story event windows such as floor-only footage, pause/transition footage, or plain POV ground footage that lacks an activity-defining event.
- Reject clips whose sampled frames appear sideways, rolled, or otherwise not properly oriented for the source video. Do not auto-rotate video clips during Selected Timeline or Reel rendering; bad orientation is a selection-quality failure, not a render fix.
- For action/adventure profiles, reject early paved/parking/staging surfaces such as ATV setup-area clips. These can look visually busy but are not the reason the activity happened.
- Use activity-profile meaningful-event gates before selection. For ATV, plain `atv_pov` or `mud_action` is not enough by itself; the segment should also show a real event such as water crossing, muddy-water run, tunnel/shade, lit tunnel, speed, rough motion, jungle trail, slope/turn, or another activity-defining signal.
- Apply the same principle to other activities: rafting must show rafting/river/rapids/splash/action/reaction value; waterfall must show waterfall/water/scenic/swimming value; temple/ricefield/beach/restaurant/Savaya/stay should show configured activity profile value rather than generic shaky walking or filler.
- Make low-level visual tags profile-aware. ATV-specific tags such as `atv_pov` must not be emitted for restaurant, temple, beach, Savaya, stay, rice-field, or waterfall clips just because edges/colors look similar. False activity tags can wrongly trigger `reject_context`.
- Use generic face/person detection as an eligibility and ranking signal for profiles that value friends, people, groups, celebration, memory, emotion, or cinematic social moments.
- If a clip is person-focused but no face is detected, reject it from Selected Timeline unless it contains a strong activity-defining event such as rapids, tunnel, speed action, water crossing, or a high-confidence memory/social scene such as pool, water, scenic, landscape, celebration, or group context for profiles like stay, beach, restaurants, or Savaya. When OpenCLIP is enabled, classify person-focused no-face clips by comparing sampled frames against generic human-subject prompts such as single person standing in water, person walking outdoors, or person posing in a landscape versus scenic/background prompts.
- Suppress repeated same-layout selections from one source video. If several windows show essentially the same person/layout, keep the strongest one or two and free space for other source videos and friends.
- Suppress repeated same-face/same-background selections across neighboring chosen clips, even when they come from different short videos. Keep the first chronological strong clip and preserve rare/high-value event tags. For memory/social profiles, preserve high-confidence pool/water/scenic/people clips before applying repetition reduction so short WhatsApp/social videos are not removed too early.
- When enabled, use CLIP/OpenCLIP embeddings over representative sampled frames to identify semantically similar clips with similar people, background, composition, or scene layout. Cache embeddings per activity using source path, file size, modified time, selected time window, model, and pretrained checkpoint so reruns are fast.
- Preserve rare per-source events such as lit tunnels and separated water-speed runs even when another window from the same video has a slightly higher technical score. For memory/social activities, reserve early slots for strong clips from distinct source videos before chronological filler consumes the timeline budget.
- Render master videos in 16:9 by default.
- Preserve source audio in the master timeline by default, with configurable muting/filtering inherited from the shared render layer when phrases or action-camera edges should be suppressed.
- Keep speed at 1x in the master timeline; Reel Builder can create speed-ramped vertical variants later.
- Persist segment-audit cache per activity so reruns do not re-inspect the same source windows.
- Use profile-aware minimum segment lengths. Adventure activities should keep substantial event windows; memory/social/cinematic activities can keep polished 2-3 second snippets when that is the natural source footage.

## Selection Philosophy

Selected Timeline is not just a chronological list of technically acceptable clips. It is the activity's semantic shortlist. Downstream modules should be able to trust that every row is useful for a reel, documentary chapter, or activity review.

The algorithm should therefore:

1. Build and inspect candidate windows.
2. Reject wrong-activity, ground-only, filler, or generic non-event windows.
3. Preserve rare events per source video.
4. Select the best remaining windows.
5. Apply a generic visual-diversity pass that compares recent visual/background signatures and removes low-value repetitions.
6. Sort the selected result chronologically by source media and source time.

Do not hardcode filenames. If a specific clip looks bad, improve the generic event gate, frame audit, activity profile, or scoring rule that allowed it.

## Configuration

```yaml
modules:
  selected_timeline:
    enabled: yes

selected_timeline:
  target_duration_seconds: 780
  min_segment_seconds: 4
  max_segment_seconds: 12
  max_clips: 125
  max_segments_per_source_video: 6
  windows_per_clip: 3
  max_window_candidates: 14
  activity_overrides:
    stay:
      target_duration_seconds: 240
      max_clips: 55
      max_segments_per_source_video: 8
      min_segment_seconds: 2
      max_segment_seconds: 14
  output_dir: MemoryCurator/08 Selected Timeline
  exports_dir: input_data/trips/bali/curated/08 Selected Timeline/exports
  render:
    enabled: yes
    width: 1920
    height: 1080
    fps: 30
    crop_mode: center_crop
    audio_mode: keep_source
    source_audio_volume: 1.0
  diversity_filter:
    enabled: yes
    max_similar_visual_runs: 2
    similar_tag_overlap_threshold: 0.72
    min_duration_fraction: 0.45
    preserve_score_threshold: 92
    preserve_high_value_tags:
      - water_speed_run
      - mud_water_run
      - lit_tunnel
      - splash
      - rapids
      - waterfall
      - architecture
      - food
      - dancing
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
    face_score_threshold: 0.45
    preserve_activity_events: yes
    person_focus_min_score: 0.27
    person_focus_margin: 0.04
```

## Commands

```bash
.venv/bin/python -B -m memory_curator_engine selected-timeline
.venv/bin/python -B -m memory_curator_engine selected-timeline --set atv
.venv/bin/python -B -m memory_curator_engine selected-timeline --set atv --execute
```
