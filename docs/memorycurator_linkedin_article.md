# How I Used AI, Prompt Engineering, and Design Thinking to Build a Vacation Media Curation Product in a Week

I came back from a Bali vacation with a familiar modern problem.

Not a lack of memories.

Too many of them.

There were photos from phones, videos from GoPro, Meta glasses clips, iPhone videos, rafting shots, ATV rides, beach photos, restaurants, temples, waterfalls, rice fields, and all the small friend moments in between.

That sounds amazing until you try to turn it into something useful.

The reality is that most of us do not remember a trip as 1,000 files.

We remember moments:

- Arriving at the rafting center
- Putting on helmets
- Walking down to the river
- The first rapid
- A huge splash
- The ATV tunnel
- The water crossing
- The group photo
- The final beach walk

That observation became the product idea:

**What if I could build a system that understands trip media as moments, activities, and stories, then generates useful outputs like albums, reels, and documentaries?**

This became **MemoryCurator**.

## The Challenge

The goal was not simply to organize files.

The goal was to build a repeatable, configurable curation engine that could take raw trip media and produce:

- A clean inventory of all photos and videos
- Duplicate and near-duplicate reports
- Quality scores
- Activity-aware media scoring
- Story moments
- Photo albums
- Activity highlight videos
- Instagram reels
- Documentary plans

And it had to be safe:

- Never delete originals
- Never move source media
- Make every step reviewable
- Use reports and manifests so the pipeline is transparent
- Keep AI optional where deterministic logic is good enough

## The AI Setup

I used Codex with a $100 AI subscription as my engineering partner.

But this was not a one-shot "build me an app" prompt.

The real work was iterative:

1. Define the product goal.
2. Break the workflow into phases.
3. Design the data contracts between phases.
4. Implement one phase.
5. Run it on real Bali media.
6. Review the outputs.
7. Improve the logic.
8. Repeat.

This is where AI became powerful.

It helped me code faster, refactor faster, test ideas faster, and turn design decisions into working Python modules quickly.

But the architecture, product judgment, and iteration loop still mattered.

## The Technical Stack

The first version deliberately used a hybrid approach:

- Deterministic Python for file contracts, manifests, scoring, and orchestration.
- Pillow and pillow-heif for image and HEIC handling.
- ImageHash for perceptual image similarity.
- OpenCV for frame sampling, face detection, visual metrics, motion cues, and video introspection.
- ReportLab for PDF album generation.
- FFmpeg through imageio-ffmpeg for rendering timelines and reels.
- Librosa and soundfile for audio analysis.
- OpenCLIP with PyTorch for optional semantic frame embeddings.

The key design principle was simple:

**Use deterministic logic first, then add AI where semantics matter.**

That kept the system cheaper, easier to debug, and easier to explain.

The model setup is also intentionally modular:

- OpenCV YuNet face detector: `models/face_detection_yunet_2023mar.onnx`
- OpenCLIP model: `ViT-B-32`
- OpenCLIP pretrained checkpoint: `openai`
- Optional transcription backends: `none`, `local_whisper`, or `openai`
- Future vision/LLM backends: OpenAI vision models, local VLMs, YOLO, InsightFace, MediaPipe, FAISS

For OpenCLIP, the first run may download model weights through the model registry used by the `open_clip` package, commonly Hugging Face Hub or OpenCLIP's configured source depending on the installed package version. I made this configurable so the same product can later run offline by pointing to a local checkpoint path.

The other important decision was caching.

Media processing gets expensive quickly. So expensive work is cached:

- Segment audits are stored per activity.
- OpenCLIP frame embeddings are stored per activity.
- Audio analysis is cached by source identity.
- Transcripts can be reused for muting and search.

That makes the product practical to iterate on. You can change a scoring rule without reprocessing every frame and audio window from scratch.

## The Architecture

The system is organized as a phase-based pipeline:

![MemoryCurator architecture](MemoryCurator_Flow_Diagram.png)

At a high level:

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

Each phase writes CSV or Markdown outputs that downstream phases consume.

That design decision was important.

Instead of hiding decisions inside code, every major decision becomes inspectable:

- Why was a file selected?
- Why was another file skipped?
- What moment does it belong to?
- What is its activity score?
- Which clip was chosen for a reel?
- What timeline segment made it into the final video?

That makes the system easier to debug, explain, and improve.

## Phase 01: Inventory

Inventory scans all configured activity folders.

For each photo or video, it records:

- File name
- Relative path
- File type
- Size
- Created date
- Modified date
- Capture date
- Capture date source
- Dimensions
- Duration for videos
- Metadata notes

This sounds simple, but it matters.

Chronology is one of the most important signals in media curation. If the system cannot understand when something happened, it cannot tell a good story.

The pipeline extracts embedded capture time where possible and falls back safely when metadata is missing.

Design pattern:

- Treat every file as immutable source data.
- Normalize all paths relative to the trip root.
- Extract embedded camera capture time before filesystem time.
- Store one row per asset in CSV.
- Make activity tagging folder-driven by default, because folder structure is usually the most reliable source of trip context.

This phase becomes the clock for the rest of the system.

## Phase 02: Duplicate Detection

Duplicate Detection was one of the first hard problems.

Filename matching is not enough.

Vacation media often contains:

- Exact duplicates
- Burst photos
- Near-identical group shots
- Similar GoPro clips
- Repeated exports
- Photos from different devices at nearly the same moment

The duplicate phase uses:

- SHA-256 hashes for exact duplicates
- Perceptual image hashing for near-duplicate photos
- HEIC/Pillow support
- OpenCV frame sampling for video similarity
- Hamming distance thresholds
- Duplicate groups
- Keeper selection

The key design decision:

**Do not delete anything.**

The phase writes:

- `duplicate_groups.csv`
- `duplicates_to_review.csv`
- `keeper_manifest.csv`

Downstream phases consume the keeper manifest.

This keeps the system safe and reviewable.

Design pattern:

- Separate exact duplicate detection from near-duplicate detection.
- Never rely on filenames.
- Build duplicate groups, then choose one keeper per group.
- Preserve review reports even when the run is executed.
- Make `keeper_manifest.csv` the contract for the next phase.

For a product version, I would add embedding search with CLIP/OpenCLIP plus FAISS so visually similar media can be found across devices and folders at scale.

## Phase 03: Quality Scoring

Quality Scoring ranks media for different purposes.

This was where the product thinking became more interesting.

A great album photo is not always a great reel clip.

A technically sharp group selfie might be perfect for an album but boring in a rafting reel.

A slightly shaky GoPro splash might be amazing for a reel because it captures the reason we went rafting.

So the system calculates multiple scores:

- Technical score
- Sharpness score
- Exposure score
- Resolution score
- Stability score
- Motion score
- Activity score
- Album purpose score
- Reel purpose score
- Documentary purpose score
- Time capsule purpose score

This gives downstream phases different optimization goals.

Design pattern:

- Score media once, but score it for multiple downstream purposes.
- Keep album scoring separate from reel scoring and documentary scoring.
- Make activity context part of the score, not a later filter.
- Fail fast if `keeper_manifest.csv` is missing, because every phase should consume a stable upstream contract.

For example, a group selfie may get a high album score and a lower reel score. A slightly chaotic rafting splash may do the opposite.

## Activity Intelligence

This became the biggest design insight.

Different activities need different scoring strategies.

Rafting should optimize for:

- Water
- Rapids
- Splashes
- Action
- Group reactions
- Adventure

ATV should optimize for:

- Mud
- Speed
- Tunnel
- Slopes
- Water crossing
- Turns

Beach should optimize for:

- Ocean
- Friends
- Landscape
- Swimming
- Sunset
- Cinematic beauty

Restaurants should optimize for:

- Food
- Friends
- Conversation
- Laughter
- Ambience

This led to activity profiles in YAML.

Example:

```yaml
activity_profiles:
  rafting:
    optimization_goal: adventure
    maximize: [action, water, rapids, splash, excitement, river, waterfall, group_reactions]
    minimize: [static, waiting, walking, talking, parking, meal]
    required_context: [rafting, river, water, rapid, splash, paddle, raft, helmet]
    reject_context: [atv, quad, temple, restaurant, beach, pool, villa]
```

That changes the product behavior.

It means the system does not treat every vacation file the same way.

This is the layer I would keep even if the AI models changed.

The activity profile is the product brain:

- It tells the scorer what matters.
- It tells the timeline selector what to preserve.
- It tells the reel builder what the viewer should feel.
- It prevents a generic travel slideshow from replacing the actual purpose of the activity.

## Phase 05: Story Builder

Story Builder converts files into moments.

This is the mental model shift:

Humans do not remember trips as filenames.

We remember:

- Arrival
- Setup
- Main activity
- Highlight
- Reactions
- Group photo
- Closing

Story Builder groups assets by:

- Activity
- Capture time
- Temporal gaps
- Media mix
- Activity score
- Taxonomy

It then creates moments with:

- Moment ID
- Activity
- Start/end time
- Moment type
- Title
- Assets
- Hero photo
- Hero video
- Moment score

This becomes the semantic layer for albums, reels, and documentary planning.

Design pattern:

- Group media by activity and time windows.
- Let moments be human concepts, not file lists.
- Keep moment IDs stable enough for downstream reports.
- Use simple taxonomies first: arrival, setup, action, reaction, group, scenic, food, closing.
- Add LLM-generated titles later if needed.

The first version does not need perfect AI captions. It needs reliable moment boundaries and good handoff manifests.

## Phase 06: Album Builder

Album Builder creates PDF photo albums.

The album logic is different from reels.

Albums should optimize for:

- People
- Memories
- Emotion
- Diversity
- Story order

The album score combines:

```text
final_album_score =
  quality_score * 0.30
+ memory_score  * 0.30
+ story_score   * 0.20
+ people_score  * 0.10
+ diversity_score * 0.10
```

The system also handles:

- Face requirement
- Cutoff face rejection
- Orientation correction
- Similarity filtering
- Burst duplicate filtering
- Chronological ordering
- Activity-based sections
- Cover and closing photos

The current output is PDF-based, which means Canva integration is not required immediately. Canva could be added later if the goal becomes template-driven design automation.

Design pattern:

- Use a different optimization goal from reels.
- Require faces for people-focused album photos.
- Reject cut-off faces and poor crops.
- Remove near-duplicate album pages even when duplicate detection missed them.
- Order photos chronologically within activity sections.
- Create final PDF artifacts only, not copied source images.

This is also where product judgment matters. A technically imperfect emotional photo can beat a sharp but boring one.

## Phase 07: Video Processing

Video Processing is an internal intelligence engine.

It includes:

- Scene detection
- Clip segmentation
- Clip scoring
- Frame analysis
- Audio analysis
- Transcript support
- Timeline building

The goal is to understand videos without manually editing every clip.

This phase creates outputs like:

- `scene_manifest.csv`
- `clip_manifest.csv`
- `clip_scores.csv`
- `frame_manifest.csv`
- `audio_events.csv`
- `transcript_segments.csv`
- `video_timeline.csv`

These files feed Selected Timeline, Reel Builder, and Documentary Builder.

Design pattern:

- Split videos into reusable intelligence outputs instead of making reels analyze raw files directly.
- Keep scene detection, clip segmentation, clip scoring, frame analysis, audio analysis, transcript, and timeline building as separate internal steps.
- Cache audio work because it is expensive and does not change unless the source changes.
- Use transcript rows not only for captions, but also for muting unwanted phrases such as GoPro voice commands.

This phase is the video understanding layer. It should not be tied to Instagram, albums, or documentaries.

## Phase 08: Selected Timeline

Selected Timeline became one of the most important phases.

Instead of asking Reel Builder to search raw videos every time, Selected Timeline creates a master activity timeline first.

For example, for ATV:

- Start directly with the ride
- Capture tunnel movement
- Capture mud action
- Capture slope and turns
- Capture water crossing
- Capture the final speed-through-water payoff

This phase:

- Scores candidate windows
- Uses activity profiles
- Rejects activity mismatches
- Rejects floor/ground-only starts
- Uses frame-level introspection
- Preserves chronological order
- Selects late payoff scenes
- Caches expensive analysis

This master timeline can then feed reels and documentary.

The most important recent improvement was orientation handling.

Earlier, I tried to fix bad video orientation during rendering. That was the wrong abstraction. It rotated some clips that should not have been rotated.

The better product rule is:

**Do not auto-rotate source video in the renderer. Reject bad-orientation clips before they enter the selected timeline.**

The current Selected Timeline phase now rejects candidates tagged as:

- `bad_orientation`
- `unstable_roll`
- `weak_close_pov`
- `ground_only`
- `setup_surface`

The OpenCV audit looks at signals such as face confidence, face count, water ratio, mud ratio, greenery, dark/tunnel ratio, gray-floor ratio, edge density, vehicle-like cues, and activity-specific tags.

OpenCLIP adds a semantic layer:

- Sample a few representative frames from each candidate window.
- Encode them with `ViT-B-32` / `openai`.
- Compare against text prompts for people-focused versus scene-focused clips.
- Reject person-focused clips when no face is visible.
- Suppress repeated same-layout clips from the same visual setup.

This is a useful product lesson: rendering should not rescue bad selection. Selection should decide what deserves to be rendered.

## Phase 09: Reel Builder

Reel Builder creates vertical videos for each activity.

The important design choices:

- Reels consume Selected Timeline
- They do not re-analyze raw media from scratch
- They preserve chronological order
- They use 9:16 crop
- They avoid black bars
- They mix normal speed and speed-ramped sections
- They support natural audio for activities like rafting and ATV
- They support muting phrases like "GoPro stop recording"
- They include configurable music placeholders

The system currently supports:

- 90-second Instagram reel
- 180-second full highlight reel

The reel logic is purpose-specific.

It does not optimize like an album.

It optimizes for:

- Energy
- Motion
- Activity essence
- Continuity
- Watchability

Design pattern:

- Build reels from Selected Timeline, not raw media.
- Keep chronological order so the viewer feels the activity unfolding.
- Use vertical 9:16 output with full-frame crop and no black bars.
- Mix normal-speed and speed-ramped sections, but avoid over-speeding to the point that it becomes unpleasant.
- Preserve natural audio for activities where sound is part of the memory, such as rafting water or ATV engine/mud action.
- Use configurable music as a later layer, not a hard dependency.
- Mute known unwanted phrases from transcript windows or action-camera boundaries.

The 90-second reel is for Instagram. The 180-second highlight is for people who actually went on the trip.

## Phase 10: Documentary Builder

Documentary Builder has a different job.

It should not decide which clips are good.

That has already been done.

Its question is:

**How do I tell the best story?**

The documentary should feel less like:

```text
Day 1
Day 2
Day 3
```

And more like:

```text
Introduction
Adventure
Emotion
Celebration
Reflection
```

It consumes:

- Moments
- Album manifest
- Clip scores
- Video timeline
- Audio events
- Transcripts
- Selected timelines

The goal is a long-form memory artifact that feels coherent, not choppy.

Design pattern:

- Treat documentary generation as story assembly, not raw clip selection.
- Use selected activity timelines as chapter sources.
- Use moments for narrative structure.
- Use transcripts and audio events for emotion, conversation, and memory.
- Preserve chronology inside activities, but allow a documentary arc across the trip.

The documentary builder should think like an editor: introduction, adventure, emotion, celebration, reflection.

## Where AI Fits

The current design uses deterministic logic first.

That keeps cost lower, makes the system easier to debug, and avoids sending everything to an LLM unnecessarily.

AI was still central to the build in two ways.

First, I used Codex as the engineering accelerator. It helped generate and refactor Python modules, design phase boundaries, update configuration-driven workflows, create prompts, produce documentation, and iterate quickly when the first version of a reel or album did not feel right.

Second, the product itself was designed with AI-ready extension points. The first working version uses deterministic metadata, OpenCV, FFmpeg, perceptual hashing, and rule-based scoring for speed and reviewability. But the architecture leaves clear hooks for AI classification, transcription, captions, moment refinement, and semantic search.

The AI capabilities used so far include:

- AI-assisted coding and refactoring with Codex.
- Prompt-driven architecture design for the phase pipeline.
- AI-assisted documentation and prompt creation.
- Human-in-the-loop review, where I inspected outputs and used AI to improve the algorithm.
- Optional OpenAI-style hooks in the design for story classification and future timeline labeling.

AI can be added where it creates real value:

- Vision classification
- Frame captions
- Better moment names
- Activity-specific event detection
- Face/person grouping
- Emotion and mood detection
- Reel critique
- Documentary narration
- Semantic search
- Time capsule memory assistant

Potential technologies:

- OpenAI vision and LLM APIs: classify sampled frames, generate richer captions, improve moment names, critique reels, and help create documentary story treatments.
- Whisper or OpenAI transcription: extract speech from videos, search for memorable conversations, and mute unwanted action-camera commands like "GoPro stop recording."
- CLIP/OpenCLIP: match media against activity concepts such as rafting, waterfall, tunnel, mud, sunset, group photo, food, or temple without training a custom model.
- YOLO: detect objects and activity cues such as helmets, rafts, vehicles, water, people, food, signs, and crowd scenes.
- InsightFace: identify and balance people across albums, reels, and documentary outputs so one friend is not accidentally missing.
- MediaPipe: detect faces, bodies, poses, hands, and basic motion cues for better people-aware selection and vertical crop decisions.
- PySceneDetect: improve scene boundary detection so long videos can be split into more natural visual sections.
- TransNetV2: use learned video shot-boundary detection for more accurate cuts than simple frame-difference heuristics.
- FAISS: build fast similarity search over image, video, face, or caption embeddings for duplicate detection and semantic search.

The architecture is built so these can become optional modules, not hard dependencies.

## What I Learned

The biggest learning was not that AI can write code.

It can.

The bigger learning was that AI amplifies structured thinking.

If you can define:

- The product goal
- The user experience
- The architecture
- The data contracts
- The iteration loop
- The edge cases

Then AI can help you move dramatically faster.

This project would have taken much longer if I were writing every module manually from scratch.

With Codex, prompt engineering, and a clear product design direction, I was able to build a working first version in about a week.

## Why This Matters for Leaders

For technical leaders, this is a useful signal.

AI-assisted development is not just about generating snippets.

It can accelerate:

- Prototyping
- Architecture exploration
- Data pipeline design
- Media processing
- Product iteration
- Documentation
- Test-and-learn cycles

For C-level leaders, the takeaway is broader:

Small teams and individual builders can now validate product ideas much faster than before.

The bottleneck shifts from "Can we build it?" to:

- Can we define the right problem?
- Can we design the right workflow?
- Can we evaluate quality?
- Can we iterate with judgment?

That is a very different world.

## Final Thought

MemoryCurator started as a fun Bali vacation project.

But it became a clear example of what happens when personal curiosity, product thinking, prompt engineering, and AI-assisted coding come together.

The future is not AI replacing design thinking.

The future is design thinking moving faster with AI.
