# Designing an AI That Understands Memories, Not Just Media

**Total build time:** About one week  
**Estimated read time:** 13 minutes  
**Project:** MemoryCurator, an AI-assisted media curation engine for trips, albums, reels, timelines, and documentaries

## 1. Why I Built It

This started as a very personal problem.

I went to Bali with my engineering friends, and the trip quickly became a greatest-hits album of bad jokes, old stories, rafting splashes, ATV mud, beach walks, waterfalls, temples, rice fields, restaurants, and Savaya nights.

Then I went to India to spend time with my parents.

Somewhere between family time and trying to make a simple reel, I opened the media folder.

That folder did not look like a vacation.

It looked like a production backlog.

There were photos from iPhones, GoPro videos, tour company photos, Meta glasses clips, beach shots, rafting videos, ATV clips, waterfall videos, restaurant photos, and many small in-between moments. The trip was amazing, but the media folder was overwhelming.

I wanted three things:

- A beautiful photo album.
- Instagram-style reels for each activity.
- Longer timeline/documentary-style videos that captured the real feeling of the trip.

The problem was time.

I did not want to manually inspect every photo and every video, remove duplicates, find the best faces, identify the right moments, slice videos at the right timestamps, keep everything chronological, and then create albums and reels by hand.

So I asked myself a simple question:

**Can I use AI, prompt engineering, and product thinking to build a reusable media curation engine in a week?**

That became MemoryCurator.

## 2. The Problem

Most media tools think in files.

People do not.

Nobody remembers a trip as:

```text
IMG_2623.HEIC
GX010679.MP4
IMG_2255.MOV
IMG_2632.MOV
```

We remember moments:

- Reaching the rafting center.
- Putting on helmets.
- Walking down to the river.
- The first rapid.
- The big splash.
- The ATV tunnel.
- The muddy turns.
- The beach walk.
- The waterfall.
- The group photo at the end.

That difference matters.

If a system optimizes only for sharpness, smiles, duration, or file metadata, it creates media that feels technically correct but emotionally flat.

For example, a rafting reel should not look like a slideshow:

```text
Arrival
Friends standing
River
Smile
Selfie
Water
Lunch
Bye
```

It should feel like rafting:

```text
Quick setup
Walking to raft
First rapid
Big splash
GoPro POV
Friends screaming
Another rapid
Waterfall
Celebration
Group closing
```

That was the core product problem:

**How do you build software that understands why the memory matters, not just what media files exist?**

## 3. Product Thinking

The first design decision was to treat MemoryCurator as a product, not a script.

That meant a few principles became non-negotiable.

Original media should never be deleted or moved. Every phase should generate reports, manifests, or curated outputs that point back to the original source. The system should be able to run one activity at a time, such as rafting first and ATV later. It should also support a full trip run once all activities are ready.

The second decision was to make the system activity-aware.

Rafting, ATV, beach, restaurants, temples, waterfalls, and night clubs should not be scored the same way.

Rafting should maximize:

- Water
- Rapids
- Splashes
- Group reactions
- GoPro-style action
- Adventure energy

ATV should maximize:

- Mud
- Speed
- Tunnel shots
- Water crossings
- Turns
- Slopes

Beach should optimize more for:

- People
- Group moments
- Scenic beauty
- Natural chronology
- Clean faces

Restaurants should care more about:

- Friends at the table
- Food
- Warm atmosphere
- Social memory

This became the idea of **Activity Intelligence**.

Instead of one generic media score, each activity gets a profile. That profile influences quality scoring, selected timelines, reels, and documentary planning.

The third decision was to separate outputs by purpose.

An album, reel, and documentary should not select media the same way.

Album Builder optimizes for people, memories, faces, emotion, and photo diversity.

Reel Builder optimizes for movement, clarity, energy, pacing, chronological flow, vertical composition, and activity-specific highlights.

Documentary Builder optimizes for story, continuity, chapters, emotional rhythm, and narrative flow.

The same asset can be excellent for one output and wrong for another.

## 4. Architecture

MemoryCurator is a Python-based, config-driven media curation engine.

The trip configuration controls:

- Trip name
- Input folders
- Enabled activities
- Activity profiles
- Phase settings
- Selected timeline rules
- Reel duration settings
- Audio behavior
- Model options
- Output locations

The project structure is phase-based:

```text
input_data/trips/<trip>/data/<activity>/
  photos/
  videos/

MemoryCurator/
  01 Inventory/
  02 Duplicate Detection/
  03 Quality Scoring/
  05 StoryBuilder/
  06 AlbumBuilder/
  07 Video Processing/
  08 Selected Timeline/
  09 ReelBuilder/
  10 Documentary Builder/

input_data/trips/<trip>/curated/
  06 AlbumBuilder/
  08 Selected Timeline/
  09 ReelBuilder/
  10 Documentary Builder/
```

The design intentionally separates human-readable workflow reports from rendered media.

`MemoryCurator/` contains CSVs, Markdown summaries, manifests, edit decisions, and debug reports.

`input_data/trips/<trip>/curated/` contains generated PDFs, MP4s, thumbnails, and exports.

This keeps the original media immutable and makes the pipeline explainable.

The high-level flow is:

```text
Raw activity media
  -> Inventory
  -> Duplicate Detection
  -> Quality Scoring
  -> Story Builder
  -> Album Builder
  -> Video Processing
  -> Selected Timeline
  -> Reel Builder
  -> Documentary Builder
```

Each phase writes a contract for the next phase.

That is important because AI-assisted systems need traceability. If a generated reel has a bad clip, I should be able to inspect the selected timeline, see the source video, source timestamp, output timestamp, score, tags, and rejection/selection reason.

## 5. AI Workflow

The most useful pattern was not “ask AI to build everything.”

The useful pattern was:

```text
Design the phase
Write the prompt/spec
Implement the module
Run it on real media
Review the output like a product user
Tighten the algorithm
Cache expensive analysis
Repeat
```

I used Codex as the engineering partner to move quickly from design to implementation.

But the key was that every phase had a product contract.

For example, Duplicate Detection is not just “find duplicates.” It has to find exact duplicates, near-duplicate photos, visually similar videos, and produce a keeper manifest without deleting originals.

Selected Timeline is not just “pick video clips.” It has to inspect videos, reject boring setup/floor/sideways clips, preserve chronology, identify action windows, include faces when people matter, cache frame audits, preserve natural audio when useful, and generate a master timeline that Reel Builder can consume.

The AI/ML stack is intentionally hybrid.

Deterministic tools are used first:

- Python standard libraries for file scanning, CSVs, manifests, and orchestration.
- Pillow and pillow-heif for images and HEIC support.
- ImageHash for perceptual photo similarity.
- OpenCV for frame sampling, face detection, motion cues, visual scoring, and video introspection.
- FFmpeg through imageio-ffmpeg for timeline and reel rendering.
- Librosa and soundfile for audio feature analysis.
- ReportLab for PDF album generation.

Then optional AI layers are added where semantics matter:

- OpenCV YuNet face detector using `models/face_detection_yunet_2023mar.onnx`.
- OpenCLIP with PyTorch for semantic frame embeddings.
- Current OpenCLIP model: `ViT-B-32`.
- Current pretrained checkpoint: `openai`.
- Optional transcription backends: `none`, `local_whisper`, or `openai`.
- Future vision backends: OpenAI vision models, local VLMs, YOLO, InsightFace, MediaPipe, and FAISS.

OpenCLIP helps with a specific problem: deterministic signals can say a frame is sharp, bright, and has motion, but they may not know whether two clips are semantically the same kind of moment.

So Selected Timeline can sample representative frames, encode them with OpenCLIP, compare visual embeddings, and suppress repeated same-layout or same-person clips. This is useful for avoiding five near-identical beach walking videos or repeated selfie-style shots.

The model loading is configurable.

YuNet is stored locally in the repo, so face detection does not need a runtime download.

OpenCLIP weights are managed by the `open_clip` and PyTorch stack. With `ViT-B-32` and `pretrained: openai`, the first run may download weights through the model registry used by the package, commonly Hugging Face Hub or OpenCLIP’s configured source depending on package version.

For privacy and reproducibility, the config supports disabling implicit Hugging Face tokens and can point to a local checkpoint path.

Caching is critical.

Media processing is expensive. MemoryCurator caches:

- Segment frame audits per activity.
- OpenCLIP semantic embeddings per activity.
- Audio analysis windows.
- Transcript outputs.

This allows the product to improve scoring rules without reprocessing every frame from scratch.

## 6. Why Existing AI Editors Fail

Most AI editors are optimized for generic media quality.

They look for:

- Sharp clips
- Smiling faces
- Short durations
- Centered subjects
- Fast motion
- “Good-looking” frames

Those are useful signals, but they are not enough.

The problem is that the best media depends on the activity.

A slightly shaky GoPro splash may be the best rafting moment.

A clean group selfie may be perfect for an album but boring for a reel.

A conversation clip may be useless for Instagram but valuable for a documentary.

A dark restaurant photo may not score high technically, but it may capture the exact friendship moment you want to remember.

This is where generic AI editing fails.

It optimizes the media.

It does not optimize the memory.

MemoryCurator tries to solve that by asking different questions:

- What activity is this?
- What is the purpose of this output?
- What makes this activity memorable?
- Is this clip in the right chronological place?
- Is this scene visually distinct from the previous scene?
- Is there a usable face when the clip is person-focused?
- Is the audio part of the memory or noise to suppress?
- Should this scene be normal speed or speed-ramped?
- Is this better for an album, reel, documentary, or time capsule?

Those questions make the system feel less like a generic editor and more like a memory-aware curator.

## 7. Designing MemoryCurator

The system currently has these phases.

### Phase 01: Inventory

Inventory scans all enabled activity folders and writes one row per media asset.

It captures:

- File name
- Relative path
- File type
- Size
- Created date
- Modified date
- Embedded capture date where available
- Capture date source
- Dimensions
- Video duration
- Activity tag from folder structure

The embedded capture time became very important.

Filesystem modified time can be wrong after copying files across devices. Camera capture metadata gives better chronology. This directly improves Story Builder, Selected Timeline, Reels, and Documentary Builder.

### Phase 02: Duplicate Detection

Duplicate Detection uses a layered approach.

Exact duplicates are detected with SHA-256 hashes.

Near-duplicate photos use perceptual image hashing through ImageHash. This catches burst shots, repeated exports, and visually similar photos even when filenames differ.

Video similarity uses OpenCV frame sampling so duplicate-like videos are compared by sampled visual content, not filename.

The output is a keeper manifest and review reports.

Nothing is deleted.

The downstream phases consume the keeper manifest so the pipeline avoids obvious duplicates before scoring.

### Phase 03: Quality Scoring

Quality Scoring creates purpose-aware scores.

It considers technical and memory signals such as:

- Sharpness
- Exposure
- Face presence
- Face count
- People visibility
- Motion/action
- Activity fit
- Story value
- Album suitability
- Reel suitability
- Documentary suitability

The important design shift was to avoid one global “best media” score.

The same clip can be poor for an album but great for a reel. The same photo can be weak technically but emotionally important.

So the phase generates scores that downstream builders can interpret differently.

### Phase 05: Story Builder

Story Builder groups media into moments.

It uses chronology, activity context, media density, and available tags to build moment rows such as:

```text
Moment: First Rapids
Activity: Rafting
Start time: 10:32
End time: 10:39
Assets: photos and videos from that window
Hero photo: best representative image
Hero video: best representative clip
Mood: excitement
Score: 97
```

Today this is mostly deterministic.

In the future, an LLM or vision-language model can improve moment titles, classify nuanced events, and create better narrative summaries.

### Phase 06: Album Builder

Album Builder creates PDF photo albums.

The design changed during testing.

Instead of copying selected photos into export folders, the phase now produces final PDF albums and reports. Original photos remain in `input_data`.

Album Builder requires faces for people-oriented photos. It rejects obvious face cutoffs and avoids photos where the subject is badly cropped.

It also uses folder-driven activity tagging so a temple photo does not accidentally get grouped as a beach moment just because the visual tags are imperfect.

The album logic emphasizes:

- People
- Friendship
- Chronology
- Activity sections
- Diversity
- Low duplication
- Cover and ending pages
- Correct orientation for placed photos

The latest design produces two enhanced album variants with different photo sets instead of a small/standard/extended size hierarchy.

That is closer to how a user wants to review albums: “Show me two good versions,” not “show me three sizes of the same idea.”

### Phase 07: Video Processing

Video Processing is an internal engine used by Selected Timeline, Reel Builder, and Documentary Builder.

It includes:

- Scene detection
- Clip segmentation
- Clip scoring
- Frame analysis
- Audio analysis
- Transcript extraction
- Timeline builder

The goal is not to modify the media like a professional editing suite.

The goal is to understand the media.

For audio, the system can preserve natural sound for activities like rafting and ATV where water, engine, laughter, and movement add energy. It can also mute configured unwanted phrases such as GoPro voice commands.

For transcripts, the backend is configurable:

```yaml
backend: none | local_whisper | openai
```

This allows a lightweight local run today and richer transcript-based search or muting later.

### Phase 08: Selected Timeline

Selected Timeline became one of the most important modules.

The idea is simple:

Before making reels or documentaries, build the best activity timeline.

For each activity, it inspects candidate video windows and selects the strongest chronological sequence.

It looks for:

- Activity-specific action
- Faces when people are important
- Water, mud, tunnels, waterfalls, beaches, temples, food, or club scenes depending on profile
- Motion and energy
- Visual clarity
- Chronological order
- Distinct scene layout
- Useful natural audio

It rejects:

- Floor-only clips
- Setup surfaces
- Weak close POV
- Person-focused clips with no usable face
- Bad orientation
- Unstable roll
- Duplicate-looking scenes
- Clips that only work if artificially rotated

One important rule:

**Do not auto-rotate source video during rendering.**

If a clip is sideways or poorly oriented, it is a selection problem, not a rendering problem. The right fix is to reject it upstream so the final timeline flows naturally.

OpenCLIP is used here as the semantic layer.

The system samples frames from candidate windows, encodes them with `ViT-B-32` using the `openai` pretrained checkpoint, compares similarity against recent selected clips, and suppresses repetitive scenes.

This is also where the product starts to feel more intelligent.

For ATV, the selected timeline should find tunnels, muddy turns, water crossings, slopes, and speed sections.

For rafting, it should prioritize rapids, splashes, river action, waterfall moments, and group reactions.

For beach, it should avoid too many similar walking shots and include people when the video is clearly person-focused.

### Phase 09: Reel Builder

Reel Builder never analyzes raw media directly.

It consumes Selected Timeline.

That separation is important.

Selected Timeline answers:

**What are the best activity scenes?**

Reel Builder answers:

**How should those scenes be paced into a vertical Instagram reel?**

The reel rules include:

- Keep scenes chronological.
- Use 9:16 vertical output.
- Fill the screen without black bars.
- Avoid forced or broken transitions.
- Mix normal speed and faster sections.
- Preserve natural audio when configured.
- Mute unwanted phrases.
- Add music placeholders for future soundtrack support.
- Generate a 90-second Instagram reel and a longer 180-second highlight where appropriate.

The speed strategy became dynamic.

If the timeline is short, keep the reel slower and more natural.

If the timeline is long, compress with moderate speed ramps instead of pushing everything to uncomfortable 5x speed.

The goal is not just to fit content.

The goal is to create something people would actually enjoy watching.

### Phase 10: Documentary Builder

Documentary Builder should not decide which clips are good.

That decision has already been made by Inventory, Duplicate Detection, Quality Scoring, Story Builder, Video Processing, and Selected Timeline.

Documentary Builder answers a different question:

**How do we tell the best story?**

The target is more like a travel documentary than a chronological dump.

Instead of:

```text
Day 1
Day 2
Day 3
```

It should feel like:

```text
Introduction
Adventure
Conflict
Emotion
Celebration
Reflection
Closing
```

The documentary layer can use selected timelines as chapter sources and later add narration, captions, interviews, music, and voiceover.

## 8. Lessons Learned

The biggest lesson is that AI products still need product thinking.

AI helped me move fast, but the quality improved only when the product goals became precise.

“Create a reel” is vague.

“Create a rafting reel where 85 percent of the video is water adventure, rapids, splashes, GoPro POV, group reactions, and waterfall moments, in chronological order, with natural water audio preserved and GoPro command phrases muted” is much better.

The second lesson is that deterministic systems and AI systems work well together.

Rules are excellent for:

- File safety
- Manifests
- Chronology
- Folder-based activity tags
- CSV contracts
- Reproducible scoring
- Cache keys
- Rendering decisions

AI is better for:

- Semantic scene understanding
- Moment classification
- Captioning
- Story summaries
- Similarity search
- Emotion and mood detection
- Natural-language search

The third lesson is that every AI workflow needs inspectability.

If the system picks a bad clip, I need to know why.

That is why MemoryCurator writes reports, candidates, edit decisions, selected manifests, scores, and rejection tags.

The fourth lesson is that media curation is not one problem.

It is many product problems stacked together:

- Duplicate detection
- Quality scoring
- Face detection
- Activity understanding
- Timeline selection
- Semantic similarity
- Audio filtering
- Reel pacing
- Album layout
- Documentary storytelling

Solving each one separately made the whole system easier to improve.

## 9. GitHub

The goal is to make MemoryCurator generic enough for other trips, reunions, weddings, birthdays, and events.

The project is designed so a user can configure:

- Trip folder
- Activity folders
- Enabled phases
- Activity profiles
- AI backends
- Model paths
- Audio rules
- Output types

The repository can include:

- Source code
- Prompts
- Phase documentation
- Draw.io architecture diagram
- Example config
- Sample reports
- Setup instructions

GitHub link:

```text
<add GitHub repository URL here>
```

## 10. Future Roadmap

The next version should make MemoryCurator more intelligent and easier to use.

Near-term roadmap:

- Add stronger local visual classification using OpenCLIP prompt sets per activity.
- Add FAISS for scalable visual similarity search.
- Add YOLO or grounding models for object and scene detection.
- Add InsightFace, RetinaFace, or MediaPipe for stronger face detection and face quality scoring.
- Add OpenAI vision models for optional high-quality scene captions and moment summaries.
- Add local VLM support for offline semantic tagging.
- Add Whisper or OpenAI transcription for searchable trip audio.
- Add music selection and beat-aware reel editing.
- Add better documentary chapter planning.
- Add a lightweight review UI for approving selected moments before rendering.
- Add packaging so others can run the engine on their own trip folders.

The bigger idea is this:

Most people do not need more media.

They need help turning their media into memories they can actually revisit.

That is what MemoryCurator is trying to become.

Not just a media organizer.

An AI memory curator.

## Final Summary

MemoryCurator started with a simple vacation problem: too many photos and videos, not enough time to turn them into something meaningful.

The product idea became bigger than media organization. The real goal was to design a system that understands activities, moments, people, chronology, quality, emotion, and story.

The current version combines deterministic Python, OpenCV, FFmpeg, audio analysis, face detection, OpenCLIP embeddings, configurable activity profiles, and AI-ready extension points. Each phase produces transparent reports and manifests so every decision can be reviewed and improved.

The biggest takeaway is that good AI products are not built by asking one big prompt.

They are built by combining clear product thinking, strong data contracts, fast iteration, and selective AI where semantics matter.

That is what MemoryCurator is trying to prove:

**AI should not just process media. It should help preserve memories.**
