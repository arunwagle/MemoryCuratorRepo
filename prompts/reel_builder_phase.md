# Reel Builder Phase Prompt

Design and implement the Reel Builder phase for the MemoryCurator project.

## Goal

Create activity-specific vertical 9:16 edits for each enabled activity by selecting from the upstream Selected Timeline and highest-value timeline segments while telling a coherent short story. The default product split is a focused 90-second Instagram reel plus, when the activity has enough source material, a broader 180-second full highlight reel.

Reel Builder should primarily consume outputs from previous phases and turn them into an edit decision list, reel manifests, review reports, and optionally rendered reel files. It may run a bounded segment-level visual audit before final selection when configured, because product-quality reels need to reject mixed, mislabeled, or wrong-activity segments that upstream metadata can miss.

## Design Position

Reel Builder is phase 09:

```text
MemoryCurator/09 Reel Builder/
```

It is a creative assembly phase, not an analysis phase.

Reel Builder should assume Selected Timeline has already removed weak/non-event windows. If a reel starts with floor footage, generic walking, boring close-up raft/vehicle POV, or a filler shot, fix the upstream Selected Timeline eligibility rules rather than adding filename-specific reel exclusions or shuffling chronology.

For adventure activities such as ATV, Selected Timeline should also reject early paved/parking/staging surfaces before Reel Builder runs. A selected-timeline-backed reel can compress selected scenes only if the selected timeline itself contains real activity scenes. The 90-second Instagram reel should choose the strongest subset when needed; the 180-second full highlight should preserve broader selected-timeline coverage with gentler speed ramps.

The relationship should be:

```text
Inventory
  -> Duplicate Detection
  -> Quality Scoring
  -> Story Builder
  -> Video Processing Engine
       -> scene-detection
       -> clip-segmentation
       -> clip-scoring
       -> frame-analysis
       -> audio-analysis
       -> transcript
       -> timeline-builder
  -> Selected Timeline
  -> Reel Builder
  -> Documentary Builder
  -> Time Capsule
```

Reel Builder should ask previous phases:

- What are the best clips?
- What moments matter most?
- What timeline events tell the story?
- Which clips have action, people, reactions, audio energy, or emotional value?
- Which clips are safe to reuse without duplicates or repetition?

It should not reopen videos to perform broad scene detection, audio classification, or transcript inference. That work belongs to Video Processing. A narrow Reel Intelligence audit is allowed: sample a few representative frames from already-proposed candidate segments and validate activity fit before selection.

## Context

- This is a generic media curation engine.
- Trip-specific config lives under folders such as `input_data/trips/sample/config/default.yaml`.
- Source media lives under folders such as `input_data/trips/sample/data/rafting`.
- Metadata and reports go under the configured `MemoryCurator/` workflow root.
- Generated reel media goes under the trip curated root, such as `input_data/trips/sample/curated/09 Reel Builder`.
- Reel reports and edit plans should be organized under activity and rank folders, such as `MemoryCurator/09 Reel Builder/rafting/rank_01_instagram_reel/`.
- Rendered reels should be organized under activity export folders, such as `input_data/trips/sample/curated/09 Reel Builder/exports/rafting/`.
- Original source media must never be deleted, moved, renamed, or edited.
- Reel Builder may read original source videos only for rendering selected segments in execute mode.
- Reel Builder must not perform broad raw-media analysis when rendering. It should only trim, crop, scale, speed-adjust, concatenate, and optionally add captions/audio based on existing metadata and the precomputed Reel Intelligence audit.

## Required Inputs

Reel Builder must require upstream manifests.

Required:

```text
MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
```

Strongly recommended when available:

```text
MemoryCurator/07 Video Processing/clip-segmentation/clip_manifest.csv
MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
MemoryCurator/07 Video Processing/frame-analysis/frame_manifest.csv
MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
MemoryCurator/03 Quality Scoring/quality_manifest.csv
MemoryCurator/02 Duplicate Detection/keeper_manifest.csv
```

If required upstream manifests are missing or empty, fail clearly:

```text
Missing upstream manifest: MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv.
Run video-processing first.
```

Do not silently rescan source folders as a fallback.

`MemoryCurator/08 Selected Timeline/<activity>/selected_timeline.csv` is the preferred source for polished activity reels. Every selected timeline row should already be activity-valid, meaningful, and chronological. Chronology should use Inventory `capture_date` as the primary ordering signal across different cameras, then `created_date`, then `modified_date`, with source folder/name ordering only as a fallback when Inventory data is missing. Reel Builder may speed-ramp, crop, and choose variants from these rows, but it should not rescue an upstream bad shortlist by hardcoding filenames.

When Video Processing writes both aggregate manifests and per-activity manifests, Reel Builder and Selected Timeline must prefer per-activity files whenever they exist:

```text
MemoryCurator/07 Video Processing/clip-scoring/<activity>/clip_scores.csv
MemoryCurator/07 Video Processing/clip-segmentation/<activity>/clip_manifest.csv
MemoryCurator/07 Video Processing/timeline-builder/<activity>/video_timeline.csv
MemoryCurator/07 Video Processing/audio-analysis/<activity>/audio_events.csv
```

This prevents a single-activity rerun from accidentally consuming the last-written aggregate CSV for another activity. Aggregate CSVs remain useful for whole-trip review, but per-activity consumers should be activity-scoped first.

## Core Responsibilities

Reel Builder should:

1. Select the best timeline segments and clips for short-form storytelling.
2. Build a ranked 90-second Instagram reel per activity, plus a 180-second full highlight when the activity has enough meaningful source material.
3. Keep each reel coherent within its activity.
4. Avoid duplicate-looking clips and repeated moments.
5. Balance action, people, reaction, context, and closing shots.
6. Generate edit decision lists that downstream renderers can reproduce.
7. Optionally render reel video files in execute mode.
8. Always produce a pacing mix: most clips stay normal speed for clarity and emotion, while selected action/scenic movement clips use fast bursts up to the configured max speed.

Default ranked outputs:

1. `rank_01_instagram_reel`
2. `rank_02_full_highlight`

## Reel Styles

Support multiple configurable reel styles.

Recommended first styles:

- `highlight`: balanced travel reel with setup, action, people, and closing.
- `action`: faster reel emphasizing high-motion clips, rapids, splashes, ATV motion, jumps, or adventure moments.
- `people`: emphasizes group shots, reactions, candid moments, laughter, and faces when available.
- `story`: clearest beginning-middle-end sequence, less frantic and more chronological.
- `cinematic`: slower pacing, more scenic/context shots, better for documentary teasers.

The implementation should generate the configured ranked outputs per enabled activity, with the default Bali workflow producing:

- `rank_01_instagram_reel`
- `rank_02_full_highlight`

These two outputs should have different jobs. For adventure activities:

- `rank_01_instagram_reel` should be a tight 90-second social edit that chooses the best scenes, preserves Inventory timestamp chronology across cameras, starts directly on meaningful activity, and uses a normal/fast pacing mix.
- `rank_02_full_highlight` should be a 180-second broader activity highlight that keeps more selected-timeline scenes than the Instagram reel, but still uses a max-speed/source-budget cap instead of forcing every row into an over-compressed edit.
- Short activities may produce only `rank_01_instagram_reel` when a full highlight would be redundant.

The 90-second Instagram reel must use a source-footage budget instead of forcing every selected-timeline row into the edit. With `max_playback_speed: 2.35`, a 90-second output can use roughly 210 seconds of source footage. If the selected timeline is longer, keep the strongest opening hook, activity-defining action, people/reaction, and closing scenes, then drop lower-value duplicate/connector clips. Do not exceed the configured max playback speed to hit an exact duration.

The 180-second full highlight must use the same principle with a larger budget. With `max_playback_speed: 2.75`, a 180-second output can use roughly 495 seconds of source footage. If the selected timeline is longer, keep broader coverage across the activity but still drop lower-value repeated rows. Full highlights may land under 180 seconds when the cap prevents healthy compression.

## Story Shape

Every reel should have a simple story arc:

```text
Opening hook
  -> arrival or setup
  -> activity build-up
  -> peak action
  -> people/reaction
  -> closing image or transition
```

For very short reels, the shape can compress:

```text
hook -> peak -> reaction -> closing
```

Recommended timing:

- Opening hook: 1-3 seconds.
- Setup/context: 3-10 seconds.
- Main activity: 50-70% of reel duration.
- Reactions/people: 10-25% of reel duration.
- Closing: 2-5 seconds.

## Activity Intelligence

Reel Builder must be activity-aware. A reel should optimize for the reason the activity happened, not only for generic technical quality.

The project should support an Activity Profile layer in trip config:

```yaml
activity_profiles:
  rafting:
    optimization_goal: adventure
    opening_duration_seconds: 5
    middle_min_fraction: 0.82
    ending_duration_seconds: 5
    maximize: [action, water, rapids, splash, excitement, river, waterfall, group_reactions]
    minimize: [static, waiting, walking, talking, parking, meal]
    reel_weights:
      activity: 0.45
      adventure: 0.25
      emotion: 0.15
      story: 0.10
      technical: 0.03
      diversity: 0.02
    moment_weights:
      arrival: 0.25
      gear_up: 0.20
      walk_to_start: 0.30
      launch: 0.78
      rapids: 1.00
      water_action: 1.00
      splash: 1.00
      group_photo: 0.45
      meal: 0.10

reel_builder:
  target_duration_seconds: 90
  instagram:
    enabled: yes
    duration_seconds: 90
    min_clips: 18
    max_clips: 30
  full_highlight:
    enabled: yes
    duration_seconds: 180
    max_playback_speed: 2.75
    budget_tolerance: 1.0
    max_clips: 55
    max_segments_per_source_video: 8
    skip_if_source_under_seconds: 130
    skip_if_clip_count_under: 16
  activity_profile: rafting
```

For rafting, the reel should behave more like this:

```text
3-5 sec  arrival / context
3-5 sec  walking or getting ready
55-75 sec water adventure, rapids, splash, action POV, river/waterfall context, standing-in-river/group reaction, compressed with selective fast bursts when needed
3-5 sec  celebration or group photo
```

It should not behave like a generic travel slideshow:

```text
arrival -> standing -> river -> selfie -> water -> lunch -> goodbye
```

Different activities should have different profiles:

- Rafting: maximize water, rapids, splash, action, GoPro POV, group reactions; minimize static waiting, walking, and meal footage.
- Waterfall: maximize landscape, beauty, waterfall, swimming, cinematic motion; minimize tickets, parking, and unrelated walking.
- ATV: maximize mud, speed, helmet cam, turns, laughter; minimize waiting, briefing, and parking.
- Beach club / Savaya: maximize DJ, sunset, crowd, dancing, drinks, friends; minimize menus and ordering.
- Shopping: maximize market visuals, products, bargaining, interaction; minimize walking and driving.

The output CSV should expose separate scoring dimensions so a user can understand why a clip was chosen or rejected:

- `adventure_score`
- `cinematic_score`
- `memory_score`
- `emotion_score`
- `activity_score`
- `activity_bucket`
- `activity_reason`
- `visual_tags`
- `activity_confidence`
- `activity_mismatch`
- `speed_factor`
- `audio_decision`
- `audit_reason`

The `activity_bucket` should be one of:

- `opening`
- `middle`
- `ending`

For action activities such as rafting, the selector should reserve only a small amount of time for opening and ending, then spend the majority of the reel in the `middle` bucket.

## Reel Intelligence

Reel Builder should support an optional config-driven intelligence gate:

```yaml
reel_builder:
  intelligence:
    enabled: yes
    backend: opencv
    sample_frames_per_segment: 5
    reject_activity_mismatch: yes
    min_activity_confidence: 42
    speed_ramps: yes
    speed_ramp_fraction: 0.55
    refine_segment_windows: yes
    max_window_candidates: 8
```

The open-source backend should use OpenCV to sample frames from candidate segments and derive visual evidence. It should not hardcode filenames. It should infer reusable visual tags such as:

- `atv_pov`
- `mud_action`
- `water_crossing`
- `tunnel_or_shade`
- `jungle_trail`
- `speed_action`
- `rough_motion`
- `face_visible`
- `people_visible`
- `group_reaction`
- `rafting_like`

For ATV, segments tagged as `rafting_like` or failing activity confidence should be rejected before selection. For other activities, the same mechanism should use their configured `required_context` and `reject_context`. For memory/social/cinematic profiles, local face/person signals should improve eligibility and ranking so friends and group moments are not missed.

Visual tags must be profile-aware. Do not emit ATV-only tags such as `atv_pov` for non-ATV profiles, because those tags can falsely trigger activity rejection for restaurants, temples, beaches, stays, and social/cinematic clips.

Selected Timeline and Reel Builder must also infer generic camera perspective tags from source media names and metadata, such as `action_camera_pov`, `phone_perspective`, `group_camera_perspective`, and `aerial_perspective`. These tags are not hardcoded to one trip; they help prevent one camera family from dominating a reel when another camera captured stronger people, river, waterfall, or context footage.

For rafting and similar water activities, action-camera POV must not be accepted just because it has motion. Reject or heavily down-rank weak close POV when sampled frames show little visible water, no visible people, and mostly raft/legs/vehicle/flat foreground. Useful rafting POV should have actual scene value such as `water_crossing`, `river_scene`, `river_people`, people/reaction evidence, or visible rapids/splash. Phone or group-camera river clips should be promoted when they show travelers standing in the river, waterfall/river context, group reactions, or alternate views of the activity.

When `refine_segment_windows` is enabled, Reel Builder should inspect multiple possible sub-windows inside each candidate timeline event and choose the best one. This prevents clips from starting on weak footage such as the floor, a pause, or a transition when a stronger tunnel, water, slope, or speed moment exists later in the same source video. The chosen sub-window must still stay inside the upstream timeline/clip start and end boundaries.

Future backends can include:

- `open_clip` for open-source semantic frame labels.
- `ultralytics` / YOLO for object-level detection when activity objects matter.
- `openai` for sampled-frame vision reasoning when deterministic labels are not enough.

The interface should remain backend-neutral so the engine can be open-sourced with OpenCV defaults and upgraded with paid AI APIs by config.

Recommended library roles:

- `opencv-python`: active default backend for frame sampling, color/edge heuristics, activity-fit validation, and wrong-activity rejection.
- `imageio-ffmpeg`: reliable FFmpeg discovery/helper library for video tooling.
- `moviepy`: future high-level composition layer for overlays, previews, timeline manipulation, and complex edits when raw FFmpeg commands become too low-level.
- `librosa` and `soundfile`: audio analysis for silence, energy, cheering/laughter candidates, and future beat-aware edits.
- `scenedetect` / PySceneDetect: future stronger scene detection backend with CLI and Python APIs.
- `open_clip_torch`: future open-source semantic frame labels such as tunnel, waterfall, temple, mud, food, crowd, beach, or vehicle.
- `ultralytics`: future object detection backend for person, vehicle, helmet, raft, paddle, stage, food, or other concrete objects.
- `faster-whisper` / `whisper`: future local transcript backend for speech-aware reels and documentary search.
- `openai`: optional paid backend for sampled-frame vision reasoning, captions, and ambiguous semantic classification.

Only add heavy AI/model libraries to `requirements.txt` when their code path is implemented. Keep the default open-source project runnable with the current lightweight deterministic backend.

## Pace and Audio

Reels should mix normal-speed and sped-up clips. Do not speed up every action clip, but do ensure every rendered reel has at least a small number of fast sections when eligible movement/action candidates exist. Use `speed_ramp_fraction` to control the maximum share of eligible action segments that receive speed ramps. Normal-speed clips are important for clarity, faces, place, and emotional memory; sped-up clips create bursts of energy. Avoid fade-to-black between short reel clips; use clean cuts unless a future renderer implements true crossfades without inserting black frames.

For action/adventure reels, source audio should be configurable:

- `audio_mode: mute` to remove camera commands and noisy chatter.
- `audio_mode: keep_source` when natural sound is part of the experience.
- `render.music.path` to add a local music bed over the whole reel.
- `render.natural_audio.enabled_media_sets` to preserve source audio only for activities where the environment matters, such as rafting water sounds or ATV engine/mud sounds.
- `render.natural_audio.mute_phrases` plus `mute_phrase_padding_seconds` and `mute_action_camera_boundary_seconds` to suppress configurable camera commands such as GoPro start/stop recording while keeping the rest of the clip audio. Boundary muting should apply both to source-file edges and selected segment edges for action-camera POV clips.

Selected Timeline master renders should use the same natural-audio configuration as Reel Builder. Even though Reel Builder consumes the Selected Timeline CSV rather than the 16:9 master MP4, the master timeline should be reviewable with the same activity-specific source audio behavior.

When rendering, normalize every segment audio stream to AAC stereo 48 kHz before concatenation. Mixed phone, GoPro, Meta, and downloaded clips can have different channel layouts or sample rates; stream-copy concatenation without normalization can cause audio to play only for the first compatible segment. Muted or failed-audio segments should still render a silent AAC stereo track so timeline and reel audio remain continuous.

Selected Timeline should preserve late payoff moments for adventure and scenic activities. For ATV, this includes final water-speed runs, mud-water runs, tunnels, and fast motion near the tail of the activity. For rafting, this includes final splashes, rapids, river scenes, group reactions, and celebration/context shots. These should be generic profile rules, not filename-specific hacks, and adventure profiles may allow more repeated action-camera water/motion layout coverage than social or album-oriented profiles.

The edit decision CSV must expose `playback_speed`, `source_audio_enabled`, and `music_enabled`.

Optimization goals should differ by downstream phase:

- Album Builder optimizes for people, portraits, memories, and emotion.
- Reel Builder optimizes for energy, motion, action, excitement, and activity fit.
- Documentary Builder optimizes for story, conversations, emotion, and narrative continuity.
- Time Capsule optimizes for completeness and long-term memory preservation.

## Selection Logic

Reel Builder should calculate a reel segment score from existing metadata, but score alone must not determine the final edit order.

The old generic formula is useful as a fallback, but activity-aware reels should use the configured Activity Profile.

Generic fallback formula:

```text
final_reel_score =
  clip_overall_score * 0.30
+ timeline_event_score * 0.20
+ story_score * 0.15
+ action_score * 0.15
+ people_or_reaction_score * 0.10
+ audio_energy_score * 0.05
+ diversity_score * 0.05
```

Important rule:

A technically imperfect but emotionally strong clip can beat a clean but boring clip.

For activity reels, an activity-perfect clip can beat a cleaner generic clip. Example for rafting:

```text
GoPro splash:
  adventure_score: 100
  activity_score: 100
  emotion_score: 95
  final_reel_score: 99

Group selfie:
  adventure_score: 20
  activity_score: 30
  memory_score: 100
  final_reel_score: 58
```

The selfie may be perfect for Album Builder, but not for a rafting Reel Builder output.

Another important rule:

For activity reels, the final selection must follow the actual activity story unless config explicitly requests an energy-first edit. A rafting reel should not start with unrelated travel footage if the creative intent is to begin at the rafting center.

For selected-timeline-backed reels, keep chronological order from the cleaned selected timeline. The correct algorithm is:

1. Upstream Selected Timeline rejects weak/filler/non-event clips.
2. Reel Builder picks a coherent subset while preserving Inventory timestamp chronology across cameras.
3. Reel Builder mixes normal speed with speed bursts for energy.
4. Reel Builder preserves late payoff moments, such as final speed runs, splashes, celebrations, or scenic reveals.
5. Reel Builder uses profile-aware segment lengths: memory/social activities may use short 2-3 second polished clips, while adventure activities should prefer longer action windows.

Recommended activity-story selection:

1. Filter to configured `include_moment_types`.
2. Reserve at least one strong clip for each configured `required_moment_types`.
3. Add configured group/action perspective clips, such as alternate camera views that show the full group.
4. Fill remaining duration with high-scoring candidates in `moment_story_order`, but keep the final edit ordered by activity story, Inventory timestamp/source-media chronology, and segment start time.
5. Apply diversity caps per moment, source video, role, and overlapping source-video windows.
6. For short reels, trim each selected source clip to the strongest sub-window instead of blindly using the whole upstream clip.
7. Validate activity context with generic profile terms such as `required_context`, `reject_context`, and `essence_chapters`; do not rely only on folder names or hardcoded filenames.

The final edit order should not be a shuffled score ranking. A rafting or ATV reel should feel like:

```text
setup / approach -> launch -> action build -> peak action -> group/reaction -> closing
```

Once the reel has entered the main action bucket, avoid jumping backward into static setup footage unless the variant explicitly asks for a non-chronological montage.

### clip_overall_score

Use `clip_scores.csv` from Video Processing.

Prefer clips with:

- Strong overall clip score.
- Good quality score.
- Good action score.
- Good story score.
- Good people score when available.
- Strong visual clarity from existing Video Processing metrics such as sharpness, exposure/brightness, motion, and clip type.

For action activities, visual clarity should not mean "static and sharp." It should mean clear enough to enjoy on Instagram while still favoring motion, energy, water, mud, speed, cheering, or other activity-defining signals.

### timeline_event_score

Use `video_timeline.csv`.

Prefer timeline events that represent:

- Arrival or beginning.
- Setup.
- Main activity.
- Peak action.
- Big splash or reaction.
- Group moment.
- Scenic transition.
- Closing.

### story_score

Use Story Builder moments.

Prefer clips that map to high-value moments:

- Launch.
- First major action.
- Peak action.
- Group photo.
- Funny reaction.
- Meal or closing.

### action_score

Use clip scoring, frame analysis, motion context, and timeline labels.

Reward:

- Rapids.
- Splash.
- Movement.
- Adventure moments.
- Fast cuts with visual interest.

### people_or_reaction_score

Use Media Intelligence if available later. Until then, use:

- Story roles.
- Moment type.
- Timeline labels.
- Audio events such as cheering or laughing candidates.
- Transcript cues when available.

Do not invent people identities unless Media Intelligence provides them.

### audio_energy_score

Use `audio_events.csv`.

Reward:

- Cheering/laughing candidates.
- Loud reaction candidates.
- River/action noise for adventure clips.
- Conversation candidates only when transcript/caption context makes them meaningful.

Penalize:

- Long silence.
- Excessive wind/noise if it is not useful for the reel.

### diversity_score

Prevent the reel from becoming repetitive.

Penalize:

- Multiple clips from the same source video too close together.
- Too many clips from one moment.
- Too many clips with the same role, especially repeated hooks or closings.
- Too many same-looking clips.
- Too many long static shots.
- Reusing duplicate or near-duplicate assets.

Reward:

- Multiple moments.
- Multiple source devices when useful.
- Mix of wide, medium, close, action, people, reaction, and scenic shots.
- Chronological flow unless the configured style prefers energy-first ordering.
- Alternate group/action perspectives that show the travelers together in the activity, even if those files were classified into a less useful moment by timestamp alone.

## Durations

Support configurable target durations:

- 30 seconds.
- 45 seconds.
- 60 seconds.
- 90 seconds for the default Instagram reel.
- 180 seconds for the optional full activity highlight.

Default should be 90 seconds for social reels.

Hard constraints:

- Minimum reel duration: 30 seconds.
- Maximum Instagram reel duration: 90 seconds by default.
- Maximum full highlight duration: 180 seconds by default.
- Final rendered aspect ratio: 9:16.
- Output should be suitable for Instagram Reels.

Clip length guidance:

- Hook clips: 1-3 seconds.
- Action clips: 2-5 seconds.
- Context clips: 2-4 seconds.
- Reaction clips: 1.5-4 seconds.
- Closing clip: 2-5 seconds.

Avoid using too many clips shorter than 1 second unless a fast-cut style is explicitly configured.

## Multi-Activity Reels

The config should support one activity or multiple activities.

Examples:

- Rafting-only reel.
- ATV-only reel.
- Bali adventure day reel using rafting + ATV.
- Full trip highlight reel using multiple activities.

When multiple activities are enabled:

- Do not let one activity dominate unless configured.
- Preserve a coherent flow.
- Use activity labels in the manifest.
- Prefer the best 1-3 moments per activity for shorter reels.
- For 90-second reels, allow broader coverage.
- For 90-second activity reels, do not include every timeline row when doing so requires uncomfortable speed. Select the strongest scenes under the configured source budget and preserve chronological order after selection.

## Aspect Ratio And Cropping

Reel Builder should create a 9:16 vertical plan.

For dry run:

- Generate planned crop behavior only.
- Do not extract frames or render video.

For execute mode:

- Render selected clips into 9:16 using existing video files and selected timestamps.
- Use deterministic crop/scale rules.
- Prefer center crop by default.
- All rendered clips must fill the full 1080x1920 frame. Do not use black padding, top/bottom bars, letterboxing, or blurred background padding for normal reel output.
- Do not auto-rotate source video during rendering. If a clip only works after rotation, reject it upstream in Selected Timeline or exclude it from the reel plan.
- Horizontal clips should be center-cropped or smart-cropped into vertical format. This may crop side content, but it preserves the Instagram reel layout.
- When frame analysis or future Media Intelligence provides subject/people hints, use those hints for smarter crop placement.
- Preserve source quality as much as practical.

The first implementation should use center crop and scale to 1080x1920.

## Seamless Edit Flow

The final reel should feel like one coherent experience, not a disconnected playlist of good clips.

For rafting, prefer this structure:

```text
opening: helmets, walking down stairs, walking to river, or getting ready
middle: rafting launch, rapids, splash, GoPro POV, group/action angle such as DANA
ending: final group shot, celebration, or all-of-us closing moment
```

Rules:

- Avoid starting with unrelated villa/travel footage when activity setup clips exist.
- Avoid jumping back to setup/static footage after rafting action has begun.
- Reserve an ending slot before filling all available time with action clips.
- Include configured group/action perspective clips such as `DANA` when they score well.
- Reduce repeated cuts from the same source video unless the activity profile explicitly allows repetition.
- Preserve natural water/action audio only when the activity config intentionally keeps source audio; otherwise support muted source audio plus a music bed.
- Support per-activity natural audio. Rafting and ATV may preserve source audio because water, engine, mud, cheers, and movement are part of the memory. Use configurable `mute_phrases` from transcript windows when available, plus configurable action-camera boundary muting to suppress GoPro start/stop command chatter without muting the whole clip.
- Avoid selecting overlapping windows from the same source video.
- Use short soft cuts or smooth action cuts in the edit decision list; hard cuts are acceptable only when the adjacent action clips flow naturally.
- In rendered reels, avoid fade-to-black between short clips; use clean cuts unless a future renderer implements real crossfades without inserting black frames.

## Captions And Text Overlays

Text overlays should be optional and config-driven.

Possible overlays:

- Activity title.
- Moment title.
- Location/trip title.
- Short transcript captions when transcript is available.
- Date or day label.

Do not add large blocks of explanatory text.

Default:

- Generate caption metadata.
- Do not burn captions into video unless `render.captions.enabled: yes`.

## Audio And Music

Audio handling should be config-driven.

Default:

- Preserve original clip audio when rendering.
- Do not add copyrighted music automatically.

Supported future options:

- Mute source audio.
- Keep source audio.
- Mix source audio with user-provided music.
- Use only user-provided music.
- Highlight clips with strong natural audio.

If a music track is configured, it must be provided by the user under `input_data` or another configured project path. Do not download music.

## Dry Run And Execute Mode

Dry run is the default.

Dry run must:

- Read upstream metadata.
- Select candidate clips.
- Create reel plans.
- Create edit decision lists.
- Generate CSV and markdown reports.
- Not render video.
- Not copy, move, delete, rename, or edit media.

Execute mode must:

- Re-run the same deterministic selection.
- Write metadata reports.
- Render reel files only when rendering is enabled.
- Write generated reel files under `input_data/trips/<trip_slug>/curated/09 Reel Builder/`.
- Never move, delete, rename, or edit originals.

## Outputs

Write metadata and reports to:

```text
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_candidates.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_selection.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_edit_decisions.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_manifest.csv
MemoryCurator/09 Reel Builder/<activity>/rank_01_instagram_reel/reel_report.md
MemoryCurator/09 Reel Builder/<activity>/rank_02_full_highlight/reel_candidates.csv
MemoryCurator/09 Reel Builder/<activity>/rank_02_full_highlight/reel_selection.csv
MemoryCurator/09 Reel Builder/<activity>/rank_02_full_highlight/reel_edit_decisions.csv
MemoryCurator/09 Reel Builder/<activity>/rank_02_full_highlight/reel_manifest.csv
MemoryCurator/09 Reel Builder/<activity>/rank_02_full_highlight/reel_report.md
```

In execute mode, write rendered reels to:

```text
input_data/trips/<trip_slug>/curated/09 Reel Builder/exports/<activity>/
```

Example:

```text
input_data/trips/sample/curated/09 Reel Builder/exports/rafting/sample_adventure_reel_rank_01_instagram_reel_90s_vertical.mp4
input_data/trips/sample/curated/09 Reel Builder/exports/rafting/sample_adventure_reel_rank_02_full_highlight_180s_vertical.mp4
```

## CSV Schemas

### reel_candidates.csv

Include every eligible segment considered for a reel:

- reel_id
- reel_style
- target_duration_seconds
- media_set
- activity
- moment_id
- moment_title
- timeline_event_id
- timeline_label
- source_media_path
- source_file_type
- source_video_duration_seconds
- segment_start_seconds
- segment_end_seconds
- segment_duration_seconds
- clip_id
- clip_overall_score
- quality_score
- action_score
- story_score
- people_score
- audio_energy_score
- diversity_score
- final_reel_score
- candidate_role: hook, setup, action, reaction, people, scenic, closing, supporting
- selection_status: selected or not_selected
- selection_reason
- exclusion_reason

### reel_selection.csv

Include selected segments only:

- reel_id
- reel_style
- reel_sequence
- media_set
- activity
- moment_id
- moment_title
- timeline_event_id
- source_media_path
- source_start_seconds
- source_end_seconds
- output_start_seconds
- output_end_seconds
- output_duration_seconds
- crop_mode
- crop_anchor
- audio_mode
- caption_text
- selected_role
- final_reel_score
- selection_reason

### reel_edit_decisions.csv

This is the renderer contract:

- reel_id
- edit_sequence
- source_media_path
- source_start_seconds
- source_end_seconds
- output_start_seconds
- output_end_seconds
- output_width
- output_height
- aspect_ratio
- transform: center_crop, smart_crop
- crop_anchor_x
- crop_anchor_y
- source_audio_enabled
- music_enabled
- caption_enabled
- caption_text
- transition_type
- transition_duration_seconds

### reel_manifest.csv

This is the downstream contract:

- reel_id
- trip_slug
- reel_style
- media_sets
- target_duration_seconds
- actual_duration_seconds
- aspect_ratio
- output_width
- output_height
- rendered_file_path
- edit_decision_path
- selection_path
- report_path
- dry_run
- created_at
- render_status: planned, rendered, skipped, failed
- render_reason

## Markdown Report

`reel_report.md` should include:

- Run mode.
- Trip slug.
- Enabled activities/media sets.
- Required upstream manifests used.
- Reel styles generated.
- Target and actual duration.
- Number of candidates.
- Number of selected clips.
- Top selected moments.
- Top excluded clips and why.
- Activity balance.
- Role balance: hook/setup/action/reaction/people/scenic/closing.
- Audio/caption/render settings.
- Rendered output paths, if any.
- Warnings and recommendations.

## Config Shape

Example:

```yaml
modules:
  reel_builder:
    enabled: yes

project:
  trip_slug: sample
  workflow_root: MemoryCurator
  curated_root: input_data/trips/sample/curated

reel_builder:
  dry_run: yes
  input_story_manifest: MemoryCurator/05 Story Builder/story_manifest.csv
  input_moment_assets: MemoryCurator/05 Story Builder/moment_assets.csv
  input_clip_scores: MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv
  input_clip_manifest: MemoryCurator/07 Video Processing/clip-segmentation/clip_manifest.csv
  input_video_timeline: MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv
  input_audio_events: MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv
  input_transcript_segments: MemoryCurator/07 Video Processing/transcript/transcript_segments.csv
  output_dir: MemoryCurator/09 Reel Builder
  curated_dir: input_data/trips/sample/curated/09 Reel Builder
  media_sets: []   # empty means all enabled activities
  reels_per_activity: 2
  target_duration_seconds: 60
  instagram:
    enabled: yes
    duration_seconds: 90
    max_playback_speed: 2.35
    budget_tolerance: 1.02
    min_clips: 18
    max_clips: 30
    max_segments_per_source_video: 4
  full_highlight:
    enabled: yes
    duration_seconds: 180
  selection:
    min_segment_seconds: 1.5
    max_segment_seconds: 5
    min_clips: 12
    max_clips: 28
    chronological: strict
    max_segments_per_moment: 2
    max_segments_per_source_video: 2
    require_opening_hook: yes
    require_closing: yes
    prefer_audio_reactions: yes
    include_moment_types: [arrival, safety_briefing, gear_up, walk_to_start, launch, rapids, splash, group_photo, meal]
    required_moment_types: [arrival, gear_up, walk_to_start, launch, rapids, splash, group_photo]
    moment_story_order: [arrival, safety_briefing, gear_up, walk_to_start, launch, rapids, splash, group_photo, meal]
    group_perspective_patterns: [DANA]
    exclude_source_patterns: []
    group_perspective_min_segments: 1
  render:
    enabled: no
    width: 1080
    height: 1920
    fps: 30
    video_codec: h264
    crop_mode: center_crop
    audio_mode: keep_source
    captions:
      enabled: no
      burn_in: no
    music:
      enabled: no
      path: null
      volume: 0.85
      source_audio_volume: 0.0
      mix_source_audio: yes
  ai:
    enabled: no
    required: no
    model: gpt-5.2-mini
```

## Commands

Dry run is the default:

```bash
.venv/bin/python -B -m memory_curator_engine reel-builder
```

Execute mode writes metadata and may render videos if `render.enabled: yes`:

```bash
.venv/bin/python -B -m memory_curator_engine reel-builder --execute
```

Run a specific reel:

```bash
.venv/bin/python -B -m memory_curator_engine reel-builder --reel-id rafting_highlight_60s
```

Run a specific style:

```bash
.venv/bin/python -B -m memory_curator_engine reel-builder --style highlight
```

## Optional AI

AI is optional and disabled by default.

When enabled, AI may refine:

- Reel title.
- Segment ordering.
- Caption text.
- Opening hook choice.
- Story arc quality.
- Duplicate/repetition warnings.

AI must consume existing metadata rows only. It should not analyze raw media, images, frames, audio, or video.

AI must never be required unless config says:

```yaml
reel_builder:
  ai:
    enabled: yes
    required: yes
```

If AI is enabled but unavailable and `required: no`, continue with deterministic selection and record the reason in `reel_report.md`.

## Architecture

Suggested package:

```text
memory_curator_engine/reels/
  __init__.py
  config.py
  inputs.py
  candidates.py
  scoring.py
  sequencing.py
  edit_decisions.py
  renderer.py
  report.py
```

Reuse common utilities:

- `memory_curator_engine/common/config.py`
- `memory_curator_engine/common/paths.py`
- `memory_curator_engine/common/csv_utils.py`
- `memory_curator_engine/common/media.py`

The renderer should be isolated from selection logic. This keeps dry-run planning fast and makes future render backends easier to add.

## Rendering Guidance

Prefer packaged FFmpeg from `imageio-ffmpeg` when system `ffmpeg` is unavailable.

Rendering should:

- Use the edit decision list as the source of truth.
- Trim selected source segments.
- Convert to 1080x1920 vertical.
- Apply center crop by default.
- Never render standard reel clips with black bars or padding.
- Concatenate selected segments in reel order.
- Preserve source audio by default.
- Fall back to muted rendering for individual source segments with unsupported or malformed audio streams.
- Avoid destructive operations.

If rendering fails for one segment:

- Mark the reel render as failed or partial.
- Keep metadata reports.
- Include the failure reason in `reel_report.md`.

## Acceptance Criteria

- Reel Builder is implemented as phase 09.
- It never performs raw-media analysis.
- It requires Story Builder and Video Processing outputs.
- Missing required manifests fail clearly.
- Dry run creates reel candidate, selection, edit-decision, manifest, and markdown reports.
- Execute mode never moves/deletes/renames/edits originals.
- Rendered reels, if enabled, are written only under `input_data/trips/<trip_slug>/curated/09 Reel Builder/`.
- Selection is deterministic and stable across reruns.
- A 9:16 vertical plan is generated for every selected reel.
- Rendered clips fill the full vertical frame with no black padding.
- Rafting reels follow a coherent activity arc: setup/walk-in, rafting action, final group/celebration ending.
- One or more activities can be included based on config.
- Optional AI consumes metadata only and is disabled by default.
