# Album Builder Phase Prompt

Design and implement the Album Builder phase for the MemoryCurator project.

Album Builder creates curated trip photo albums across all enabled activities by selecting the strongest photos from Story Builder moments, removing redundant near-duplicates, ordering the photos as a story, and exporting final enhanced PDF books by default.

## Design Position

Album Builder is a top-level phase:

```text
MemoryCurator/06 Album Builder/
```

It consumes Story Builder outputs and creates photo-album-specific outputs. It should not replace Story Builder, Quality Scoring, Duplicate Detection, or Media Intelligence.

The relationship should be:

```text
Quality Scoring -> Story Builder -> Album Builder
                              -> Video Processing -> Reel Builder
                                                  -> Documentary Builder
                              -> Time Capsule
```

## Context

- This is a generic media curation engine.
- Trip-specific config lives under folders such as `input_data/trips/<trip_slug>/config/default.yaml`.
- Source media lives under folders such as `input_data/trips/<trip_slug>/data/<activity>`.
- Metadata and reports go under the configured `MemoryCurator/` workflow root.
- Generated album artifacts go under the trip `input_data` curated root, such as `input_data/trips/<trip_slug>/curated`.
- Original source media must never be deleted, moved, renamed, or edited.
- Phases before Album Builder write metadata only and keep media in `input_data`.
- Album Builder must not copy selected source photos into export folders.
- Album Builder must never move originals. CSV reports should point to original `input_data` photo paths.
- Album activity tags should default to the source folder/media set. Use `inventory.media_sets.<media_set>.activity_name` for album page titles.
- Avoid subtags in album page titles for now. Use activity titles such as `Temple`, `Beach`, `Rafting`, or `Savaya`, not titles such as `Entering Savaya`.
- Sort album output by configured activity order, then by capture time inside each activity.
- Execute mode should generate final album artifacts such as PDFs only.
- Dry run must not copy, move, delete, rename, or edit media.
- Each phase should create a manifest file for the next phase. Do not silently rescan earlier source folders as a fallback.

## Required Inputs

Album Builder must require Story Builder outputs.

Required:

```text
MemoryCurator/05 Story Builder/story_manifest.csv
MemoryCurator/05 Story Builder/moment_assets.csv
MemoryCurator/03 Quality Scoring/quality_manifest.csv
```

If a required upstream manifest is missing or empty, Album Builder must fail clearly:

```text
Missing upstream manifest: MemoryCurator/05 Story Builder/moment_assets.csv.
Run story-builder first.
```

Expected `moment_assets.csv` fields:

- moment_id
- moment_title
- moment_type
- media_set
- media_path
- file_type
- asset_role
- quality_score
- album_score
- instagram_score
- movie_score

Expected `quality_manifest.csv` fields:

- media_set
- media_path
- original_path
- file_type
- width
- height
- duration_seconds
- quality_score
- album_score
- recommended_uses

Optional enrichment inputs:

```text
MemoryCurator/04 Media Intelligence/
```

If Media Intelligence outputs exist, Album Builder may use people, faces, captions, mood, landmarks, or emotion tags. If they do not exist, Album Builder must still work using quality scores, moment structure, metadata, filenames, and deterministic diversity rules.

## Phase Goal

Album Builder should:

- Select the best photos for each activity.
- Pick strongest hero photos.
- Pick best group photos.
- Pick best action photos.
- Pick best candid or funny photos when detectable.
- Avoid duplicates and near-duplicates.
- Respect Story Builder moments.
- Build a story-ordered album sequence.
- Create enabled album variants from config. The default should be one complete enhanced trip album.
- Generate final enabled album PDFs only when executed.
- Generate an enhanced album PDF that includes all strong eligible photos while avoiding repeated bursts.
- Support additional optional variants later, but do not split the default output into separate story and people albums.
- Generate CSV and markdown reports.
- Generate `album_manifest.csv` as the downstream contract.
- Keep Canva and page-flip viewers as future optional publishing backends, not current requirements.

## Album Variants

The phase should produce enabled album variants from config. The recommended default is one enhanced album:

- Enhanced album: chronological trip story with balanced activity coverage, people moments, candids, group photos, and all strong eligible photos in one book.

The exact target sizes and overlap rules should be config-driven. Recommended defaults:

```yaml
album_builder:
  variants:
    enhanced:
      enabled: yes
      strategy: visual_story
      min_photos: 70
      target_photos: 160
      max_photos: 10000
      include_all_good: yes
```

If there are not enough high-quality photos for a requested variant, Album Builder should produce the best available set and report the shortage clearly.

## Selection Responsibilities

Album Builder must balance technical quality with emotional and story value.

Important rule:

A technically imperfect but emotionally strong photo can beat a sharp but boring photo.

Hard eligibility rule:

Photos must contain at least one detected face to be selected for an album. If no face is detected, the photo must remain in the candidate report with an exclusion reason and must not appear in enhanced PDFs.

Photos with detected faces too close to the image edge should be excluded by default because likely cut-off faces make poor album pages. Write `face_cutoff_count` and the exclusion reason to `album_candidates.csv`.

Near-duplicate filtering must be algorithmic, not filename-specific. Compute a perceptual visual hash for each candidate photo and suppress photos that are visually too close to already selected photos from the same activity. Enhanced variants should include strong eligible photos, but they must not include repeated burst shots or near-identical compositions.

PDF rendering should correct sideways images algorithmically. EXIF orientation is not always reliable, so the renderer should optionally compare face-detection confidence across rotations and rotate only when the corrected orientation scores clearly better than the original.

Use this final score:

```text
final_album_score =
  quality_score * 0.30
+ memory_score * 0.30
+ story_score * 0.20
+ people_score * 0.10
+ diversity_score * 0.10
```

All score components should be written to reports for review.

### quality_score

Use the existing `album_score` and `quality_score` from Quality Scoring.

Suggested deterministic blend:

```text
quality_score = album_score * 0.70 + quality_score * 0.30
```

### memory_score

Memory score estimates whether the photo is likely to matter emotionally.

When Media Intelligence exists, use:

- Detected people count.
- Known/tracked people.
- Smiles or positive emotion.
- Captions that indicate celebration, reaction, group, funny, surprise, or achievement.
- Face clarity.

Without Media Intelligence, estimate using:

- Story asset role such as `hero_photo`.
- Moment type importance.
- Photos near key moments such as launch, rapids, splash, group photo, meal, or closing.
- Filename/time proximity to selected videos or other high-scoring photos.
- Group-photo-like aspect and resolution heuristics when possible.

### story_score

Story score should reward photos that help the album flow.

Prefer photos that represent:

- Opening or arrival.
- Setup and preparation.
- Main activity.
- Action peak.
- Reactions.
- Group shots.
- Closing or transition.

Each important moment should contribute photos when usable candidates exist. Enhanced albums may allow more than compact albums, but still suppress near-duplicates.

No moment should dominate the album unless it is exceptional and configured to allow it.

### people_score

When Media Intelligence exists, people score should reward:

- Clear faces.
- Important people.
- Group diversity.
- Balanced representation across people.

Without Media Intelligence, keep this score neutral rather than inventing identity claims.

When local deterministic face detection is enabled, write `face_count` to the candidate report. Use it as a hard filter before album selection and as an input to `people_score`; do not infer identities.

### diversity_score

Diversity score should reduce repetition.

Penalize:

- Near-duplicate photos.
- Burst sequences with many similar frames.
- Too many photos from the same minute.
- Too many photos from the same moment.
- Too many same-looking wide shots or same-looking selfies.

Reward:

- Mix of wide, medium, close, candid, action, group, and detail shots.
- Mix of portrait and landscape photos when useful.
- Coverage across the full activity timeline.

## Moment Rules

Album Builder must respect Story Builder moments.

Recommended constraints:

- Every important moment should contribute at least 1 photo if a usable photo exists.
- Small album: 1-2 photos per important moment.
- Standard album: 1-3 photos per important moment.
- Extended album: 2-6 photos per important moment.
- Moment quota can expand when a moment has exceptional scores or is the main activity peak.
- Moment quota should shrink for transition moments unless they are emotionally or narratively important.
- The phase should never select all photos from a single strong moment while ignoring the rest of the story.

## Story Ordering

Album order should follow Story Builder order first, then sequence photos within each moment.

Preferred album arc:

1. Opening / arrival.
2. Setup.
3. Main activity.
4. Reactions.
5. Group shots.
6. Closing / transition.

Within a moment, order photos as:

1. Establishing or hero photo.
2. Setup/detail photo.
3. Action or peak photo.
4. Reaction/candid/group photo.

The output sequence must be deterministic and stable across reruns.

For trip-level albums:

- Group selected photos by configured activity/media-set order.
- Sort photos by capture time inside each activity.
- Do not mix activities on the same PDF page when avoidable.
- Use the activity name as the page title.

## PDF Book Export

Album Builder should support a local PDF album export without requiring Canva.

The PDF export should feel like a designed travel photo book, not a plain report. It should use Album Builder selections and Story Builder moments as the source of truth.

Implemented output:

```text
input_data/trips/<trip_slug>/curated/06 Album Builder/exports/<trip_slug>_<album_size>_album.pdf
```

The PDF exporter should be config-driven and optional:

```yaml
album_builder:
  pdf_export:
    enabled: yes
    page_size: landscape_a4
    title: Some friendships never needed a restart.
    subtitle: <Trip Name> 2026
    style: travel_scrapbook
    cover_photo: auto
    closing_photo: auto
```

### Cover Page Design

The first page should be a designed cover page inspired by a travel scrapbook / journal aesthetic.

Visual direction:

- Layered map background.
- Torn paper / textured paper shapes.
- Warm beige, tan, kraft-paper, cream, and muted teal accents.
- Handwritten or typewriter-style title treatment.
- Small travel illustrations such as camera, plane, map line, passport stamp, or ticket shapes.
- A real selected trip photo of the travelers, not a stock placeholder.

Example cover copy:

```text
Some friendships
never needed
a restart.

<Trip Name> 2026
```

Cover photo selection:

- Prefer a real group/traveler photo from the trip.
- Prefer clear people, emotional memory, group photo, arrival, or beautiful scenic-social image.
- Allow explicit config override such as `cover_photo: input_data/trips/<trip_slug>/data/.../<cover_photo_filename>`.
- If the configured cover photo is unavailable, fall back to the highest `memory_score` / `album_score` selected photo.
- Preserve EXIF orientation for explicit cover photos; do not apply face-based auto-rotation to configured cover artwork unless a separate config option explicitly requests it.

### Closing Page Design

The final page should act like the album ending and must be visually aligned like a designed book page.

Closing photo selection:

- Allow explicit config override such as `closing_photo: input_data/trips/<trip_slug>/data/.../<closing_photo_filename>`.
- If the configured closing photo is unavailable, fall back to a strong late-sequence group, hero, or memory photo.
- The closing photo remains at its original `input_data` path and is embedded into the generated PDF only.
- The closing page should use a centered framed image with consistent margins, not an awkward full-bleed crop.
- Preserve EXIF orientation for explicit closing photos; do not apply face-based auto-rotation to configured closing artwork because it can rotate a landscape memory photo sideways.

Recommended closing copy:

```text
until the next adventure

from <Trip Name> 2026
```

Implementation guidance:

- Use Python libraries such as Pillow and ReportLab for local generation.
- Decode HEIC with `pillow-heif` when available.
- Use deterministic local textures/shapes if external design assets are unavailable.
- Do not require Canva for PDF generation.
- Do not use stock photos for the cover.
- Do not move or edit original photos.

### Interior Page Design

Interior pages should feel like a book:

- Opening section page for the activity.
- Moment-based spreads.
- 1-photo hero pages for exceptional photos.
- 2-photo, 3-photo, and 4-photo collage layouts.
- Occasional caption/date/moment title text.
- White margins or scrapbook paper margins.
- No overcrowded grid pages.

The page sequence should follow Story Builder order and Album Builder selection order.

### Future Page-Flip Digital Album

The local page-flip viewer is a future optional backend and is not required for the current PDF implementation. If implemented later, it should be generated from exported PDF pages or rendered page images.

It should:

- Live under `input_data/trips/<trip_slug>/curated/06 Album Builder/page_flip/`.
- Use local files only.
- Work offline in a browser.
- Provide previous/next page controls and a book-like reading flow.
- Not require Canva or any external service.

## Optional Canva Publishing Backend

Canva integration is optional and should not be required for local PDF album generation.

Use Canva later only when the user wants:

- Canva-hosted editable designs.
- Canva Brand Templates.
- Canva sharing/export workflows.
- Manual post-generation editing in Canva.

Recommended future config:

```yaml
album_builder:
  canva:
    enabled: no
    mode: plan_only  # plan_only | upload_assets | autofill_template | export
    brand_template_id: ""
    export_format: pdf
```

The first PDF book implementation should be local-first.

## Commands

Dry run is the default:

```bash
.venv/bin/python -B -m memory_curator_engine album-builder
```

Execute mode generates final PDFs only:

```bash
.venv/bin/python -B -m memory_curator_engine album-builder --execute
```

Optional future AI refinement may be added later:

```bash
export OPENAI_API_KEY="..."
.venv/bin/python -B -m memory_curator_engine album-builder --ai
```

Do not require AI for the first implementation.

## Outputs

Write metadata and reports to:

```text
MemoryCurator/06 Album Builder/album_candidates.csv
MemoryCurator/06 Album Builder/album_selection.csv
MemoryCurator/06 Album Builder/album_manifest.csv
MemoryCurator/06 Album Builder/album_report.md
```

In execute mode, write final PDFs to the trip curated root:

```text
input_data/trips/<trip_slug>/curated/06 Album Builder/exports/
```

Example for a trip whose slug is `sample`:

```text
input_data/trips/sample/curated/06 Album Builder/exports/sample_enhanced_album.pdf
```

Selected image files should not be copied. PDF filenames should be safe, deterministic, and include trip slug plus album size.

## Report Columns

`album_candidates.csv` should include every eligible photo candidate:

- media_set
- album_size
- moment_id
- moment_title
- moment_type
- media_path
- original_path
- file_type
- width
- height
- quality_score
- memory_score
- story_score
- people_score
- diversity_score
- face_count
- face_cutoff_count
- final_album_score
- candidate_role: hero, group, action, candid, detail, establishing, supporting, unknown
- selection_status: selected or not_selected
- selection_reason
- exclusion_reason

`album_selection.csv` should include selected photos only:

- media_set
- album_size
- album_sequence
- moment_id
- moment_title
- moment_type
- media_path
- export_path, pointing to the final PDF for that album size
- original_path
- candidate_role
- final_album_score
- selection_reason

`album_manifest.csv` is the downstream contract and should include selected album photos:

- media_set
- album_size
- album_sequence
- moment_id
- moment_title
- media_path
- export_path, pointing to the final PDF for that album size
- original_path
- file_type
- width
- height
- final_album_score
- candidate_role
- source_phase

In dry run, `export_path` should be the planned PDF path. In execute mode, `export_path` should be the generated PDF path. In both modes, `media_path` must remain the original `input_data` path.

`album_report.md` should include:

- Summary by activity and album size.
- Number of selected photos.
- Moment coverage table.
- Top hero photos.
- Group/action/candid breakdown.
- Photos excluded because of duplicates or moment overrepresentation.
- Any shortages against configured album-size targets.

## Export Safety

Dry run must:

- Score candidate photos.
- Generate CSV and markdown reports.
- Show planned album export paths.
- Not copy, move, delete, rename, or edit media.

Execute mode must:

- Generate final PDF albums only.
- Not copy selected source photos into export folders.
- Never move originals.
- Never delete originals.
- Never overwrite an existing different PDF unless overwrite policy allows it.
- Validate every selected source path before PDF generation.
- Write reports after successful PDF generation.
- If PDF generation fails, stop with a clear error and report what happened.

If a PDF export file already exists, replace or fail clearly based on config.

## Config Shape

Trip config example:

```yaml
modules:
  album_builder:
    enabled: yes

project:
  trip_slug: <trip_slug>
  curated_root: input_data/trips/<trip_slug>/curated

album_builder:
  dry_run: yes
  input_story_manifest: MemoryCurator/05 Story Builder/story_manifest.csv
  input_moment_assets: MemoryCurator/05 Story Builder/moment_assets.csv
  input_quality_manifest: MemoryCurator/03 Quality Scoring/quality_manifest.csv
  output_dir: MemoryCurator/06 Album Builder
  exports_dir: input_data/trips/<trip_slug>/curated/06 Album Builder/exports
  copy_on_execute: no
  pdf_export:
    enabled: yes
    title: Some friendships never needed a restart.
    subtitle: <Trip Name> 2026
    cover_photo: auto
    closing_photo: auto
  overwrite_policy: fail
  photo_only: yes
  variants:
    enhanced:
      enabled: yes
      strategy: visual_story
      min_photos: 70
      target_photos: 160
      max_photos: 10000
      include_all_good: yes
  scoring:
    quality_weight: 0.30
    memory_weight: 0.30
    story_weight: 0.20
    people_weight: 0.10
    diversity_weight: 0.10
  important_moment_types:
    - arrival
    - safety_briefing
    - gear_up
    - launch
    - rapids
    - splash
    - group_photo
    - meal
    - return_trip
  duplicate_similarity_threshold: 8
  max_same_minute_per_album: 3
  max_same_moment_fraction: 0.20
```

## Implementation Notes

Use standard libraries where possible.

Recommended implementation modules:

```text
memory_curator_engine/albums/
  __init__.py
  report.py
```

The implementation should reuse existing common utilities for:

- YAML config loading.
- Project path resolution.
- Media type helpers.
- Manifest reading and validation.

Optional libraries such as Pillow, pillow-heif, ImageHash, or OpenCV may be used if already installed, but the phase should still work without them using upstream duplicate and quality reports.

## AI Extension Point

Do not require AI in the first implementation.

Future optional AI could improve:

- Emotional/candid/funny detection.
- Better title and caption generation.
- Stronger group photo selection.
- People balance when face/person recognition exists.
- Page-spread recommendations.

If AI is added later, it should refine candidate labels and selection reasons after Python scoring, not replace deterministic filtering and quota logic.

## Acceptance Criteria

- Missing Story Builder manifests fail clearly.
- Dry run generates album candidate, selection, manifest, and markdown reports.
- Dry run does not copy, move, delete, rename, or edit media.
- Execute mode does not move, delete, rename, or edit originals.
- `album_manifest.csv` keeps `media_path` pointing to `input_data`.
- `album_manifest.csv` contains `export_path` for final PDF artifacts.
- One enhanced album selection is generated by default, with any other explicitly enabled variants honored from config.
- Each important moment contributes photos when usable candidates exist.
- No moment dominates the album beyond configured limits unless explicitly justified in the report.
- Duplicate and near-duplicate photos are avoided.
- Selection reasons explain why emotionally or narratively strong photos were chosen.
- Reports are deterministic across reruns.
- Execute mode generates final enabled PDFs. The recommended default is one complete enhanced album.
