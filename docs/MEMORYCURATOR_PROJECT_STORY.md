# Designing an AI That Understands Memories, Not Just Media

**Total build time:** About one week  
**Estimated read time:** 10-12 minutes  
**Project:** MemoryCurator, an AI-assisted media curation engine for trips, albums, reels, timelines, and documentaries

## 1. Why I Built It

This started as a very personal problem. I went to Bali with my engineering friends, and the trip quickly became a greatest-hits album of bad jokes, old stories, rafting splashes, ATV mud, beach walks, waterfalls, temples, rice fields, restaurants, and Savaya nights.

Then I went to India to spend time with my parents. Somewhere between family time and trying to make a simple reel, I opened the media folder.

**That folder did not look like a vacation. It looked like a production backlog.**

There were iPhone photos, GoPro videos, Meta glasses clips, tour company photos, rafting videos, ATV clips, beach shots, restaurant photos, waterfall videos, and hundreds of small friend moments in between. The trip was amazing. The media folder was chaos.

I wanted three things: **a beautiful photo album, Instagram-style reels for each activity, and longer timeline/documentary-style videos** that captured the real feeling of the trip.

The problem was time. I did not want to manually inspect every photo and video, remove duplicates, find the best faces, identify the right moments, slice clips at the right timestamps, preserve chronology, and then create albums and reels by hand.

So I asked myself a simple question: **Can I use AI, prompt engineering, and product thinking to build a reusable media curation engine in a week?**

That became **MemoryCurator**.

## 2. The Problem

**Most media tools think in files. People do not.**

Nobody remembers a trip as `IMG_2623.HEIC`, `GX010679.MP4`, or `IMG_2255.MOV`. We remember moments: reaching the rafting center, putting on helmets, walking down to the river, the first rapid, the big splash, the ATV tunnel, the muddy turns, the beach walk, the waterfall, and the group photo at the end.

**That difference matters.** If a system optimizes only for sharpness, smiles, duration, or file metadata, it creates media that feels technically correct but emotionally flat.

A rafting reel should not feel like this: **arrival, friends standing, river, smile, selfie, water, lunch, bye.** That is a travel slideshow.

It should feel like rafting: **quick setup, walking to the raft, first rapid, big splash, GoPro POV, friends screaming, another rapid, waterfall, celebration, group closing.**

That became the real product question: **How do you build software that understands why the memory matters, not just what media files exist?**

## 3. Product Thinking

The first design decision was to treat **MemoryCurator as a product, not a script.** Original media should never be deleted or moved. Every phase should generate reports, manifests, or curated outputs that point back to the original source. The system should support one activity at a time, such as rafting first and ATV later, and also support a full trip run once all activities are ready.

The second decision was to make the system **activity-aware.** Rafting, ATV, beach, restaurants, temples, waterfalls, and night clubs should not be scored the same way.

Rafting should maximize water, rapids, splashes, group reactions, GoPro-style action, and adventure energy. ATV should maximize mud, speed, tunnel shots, water crossings, turns, and slopes. Beach should optimize more for people, group moments, scenic beauty, natural chronology, and clean faces.

This became the idea of **Activity Intelligence.** Instead of one generic media score, each activity gets a profile. That profile influences quality scoring, selected timelines, reels, and documentary planning.

The third decision was to separate outputs by purpose. Album Builder optimizes for people, memories, faces, emotion, and photo diversity. Reel Builder optimizes for movement, clarity, energy, pacing, chronological flow, vertical composition, and activity-specific highlights. Documentary Builder optimizes for story, continuity, chapters, emotional rhythm, and narrative flow.

**The same asset can be excellent for one output and wrong for another.**

## 4. Architecture

MemoryCurator is a **Python-based, config-driven media curation engine.** The trip configuration controls the trip name, input folders, enabled activities, activity profiles, phase settings, selected timeline rules, reel duration settings, audio behavior, model options, and output locations.

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

The project separates **human-readable workflow reports** from **rendered media.** `MemoryCurator/` contains CSVs, Markdown summaries, manifests, edit decisions, and debug reports. `input_data/trips/<trip>/curated/` contains generated PDFs, MP4s, thumbnails, and exports.

That separation keeps the **original media immutable** and makes the pipeline **explainable.** If a generated reel has a bad clip, I can inspect the selected timeline and see the source video, timestamp, score, tags, and selection reason.

## 5. AI Workflow

The most useful pattern was not **“ask AI to build everything.”** The useful pattern was: design the phase, write the prompt/spec, implement the module, run it on real media, review the output like a product user, tighten the algorithm, cache expensive analysis, and repeat.

I used Codex as the engineering partner to move quickly from design to implementation. But the quality came from turning each vague idea into a clear product contract.

For example, **Duplicate Detection is not just “find duplicates.”** It has to find exact duplicates, near-duplicate photos, visually similar videos, and produce a keeper manifest without deleting originals.

**Selected Timeline is not just “pick video clips.”** It has to inspect videos, reject boring setup/floor/sideways clips, preserve chronology, identify action windows, include faces when people matter, cache frame audits, preserve natural audio when useful, and generate a master timeline that Reel Builder can consume.

**The stack is intentionally hybrid: deterministic Python first, AI where semantics matter.**

The deterministic layer uses Python standard libraries for file scanning and manifests, Pillow and pillow-heif for images and HEIC support, ImageHash for perceptual photo similarity, OpenCV for frame sampling and video introspection, FFmpeg through imageio-ffmpeg for rendering, librosa and soundfile for audio analysis, and ReportLab for PDF album generation.

The AI/ML layer currently includes **OpenCV YuNet face detection, OpenCLIP with PyTorch for semantic frame embeddings, and configurable transcription backends.** The current OpenCLIP setup uses `ViT-B-32` with the `openai` pretrained checkpoint.

**OpenCLIP helps with a specific problem:** deterministic signals can say a frame is sharp, bright, and has motion, but they may not know whether two clips are semantically the same kind of moment. Selected Timeline can sample representative frames, encode them with OpenCLIP, compare embeddings, and suppress repeated same-layout or same-person clips.

Model loading is configurable. YuNet is stored locally in the repo. OpenCLIP weights are managed by the `open_clip` and PyTorch stack, and the first run may download model weights through Hugging Face Hub or OpenCLIP’s configured source depending on the installed package version. For privacy and reproducibility, the config can disable implicit Hugging Face tokens and point to a local checkpoint path.

**Caching is critical.** MemoryCurator caches segment frame audits, OpenCLIP semantic embeddings, audio analysis windows, and transcript outputs. This makes iteration practical because scoring rules can change without reprocessing every frame from scratch.

## 6. Why Existing AI Editors Fail

Most AI editors are optimized for **generic media quality.** They look for sharp clips, smiling faces, short durations, centered subjects, fast motion, and good-looking frames.

**Those signals are useful, but they are not enough.**

The best media depends on the activity. A slightly shaky GoPro splash may be the best rafting moment. A clean group selfie may be perfect for an album but boring for a reel. A conversation clip may be useless for Instagram but valuable for a documentary. A dark restaurant photo may not score high technically, but it may capture the exact friendship moment you want to remember.

**Generic AI editors optimize the media. They do not optimize the memory.**

MemoryCurator asks different questions: What activity is this? What is the purpose of this output? What makes this activity memorable? Is this clip in the right chronological place? Is this scene visually distinct from the previous scene? Is there a usable face when the clip is person-focused? Is the audio part of the memory or noise to suppress?

Those questions make the system feel less like a generic editor and more like a **memory-aware curator.**

## 7. Designing MemoryCurator

**Phase 01, Inventory,** scans all enabled activity folders and writes one row per media asset. It captures file name, relative path, file type, size, created date, modified date, embedded capture date, dimensions, duration, and activity tag. **Embedded capture time** became especially important because filesystem modified time can be wrong after copying files across devices.

**Phase 02, Duplicate Detection,** uses SHA-256 for exact duplicates, perceptual image hashing for near-duplicate photos, and OpenCV frame sampling for visually similar videos. The output is a keeper manifest and review reports. **Nothing is deleted.**

**Phase 03, Quality Scoring,** creates purpose-aware scores. It considers sharpness, exposure, face presence, people visibility, motion, action, activity fit, story value, album suitability, reel suitability, and documentary suitability. The key design shift was to avoid **one global “best media” score.**

**Phase 05, Story Builder,** groups media into moments using chronology, activity context, media density, and available tags. Today this is mostly deterministic. In the future, an LLM or vision-language model can improve moment titles, classify nuanced events, and create richer summaries.

**Phase 06, Album Builder,** creates PDF photo albums. It emphasizes people, friendship, chronology, activity sections, diversity, low duplication, cover and ending pages, and correct orientation. **People-oriented photos require usable faces, and obvious face cutoffs are rejected.**

**Phase 07, Video Processing,** is an internal engine used by Selected Timeline, Reel Builder, and Documentary Builder. It includes scene detection, clip segmentation, clip scoring, frame analysis, audio analysis, transcript extraction, and timeline building. **The goal is not to modify media like an editing suite; the goal is to understand it.**

**Phase 08, Selected Timeline,** became one of the most important modules. Before making reels or documentaries, the system builds the best activity timeline. It inspects candidate video windows, looks for activity-specific action, rejects weak clips, keeps chronology, avoids repeated scene layouts, and produces a master activity timeline.

For Waterfall-style activities, I also added story-stage regression filtering. The system should not start with an approach, enter the waterfall/swimming sequence, and then jump back to random stairs or trail clips just because those later clips scored well technically.

**Phase 09, Reel Builder,** consumes Selected Timeline. It keeps scenes chronological, renders 9:16 vertical output, avoids black bars, mixes normal speed and faster sections, preserves natural audio when configured, mutes unwanted phrases, and supports future music placeholders. It can create a **90-second Instagram reel** and a longer **180-second highlight** where appropriate.

**Phase 10, Documentary Builder, should not decide which clips are good.** That work has already been done upstream. Documentary Builder answers a different question: **How do we tell the best story?**

The target is more like a travel documentary than a chronological dump. Instead of Day 1, Day 2, Day 3, the structure should feel like introduction, adventure, emotion, celebration, reflection, and closing.

## 8. Lessons Learned

The biggest lesson is that **AI products still need product thinking.** AI helped me move fast, but the quality improved only when the product goals became precise.

**“Create a reel” is vague.** “Create a rafting reel where most of the video is water adventure, rapids, splashes, GoPro POV, group reactions, and waterfall moments, in chronological order, with natural water audio preserved and unwanted GoPro command phrases muted” is much better.

The second lesson is that **deterministic systems and AI systems work well together.** Rules are excellent for file safety, manifests, chronology, folder-based activity tags, CSV contracts, reproducible scoring, cache keys, and rendering decisions. AI is better for semantic scene understanding, moment classification, captioning, story summaries, similarity search, emotion detection, and natural-language search.

The third lesson is that **every AI workflow needs inspectability.** If the system picks a bad clip, I need to know why. That is why MemoryCurator writes reports, candidates, edit decisions, selected manifests, scores, and rejection tags.

The fourth lesson is that **media curation is not one problem.** It is many product problems stacked together: duplicate detection, quality scoring, face detection, activity understanding, timeline selection, semantic similarity, audio filtering, reel pacing, album layout, and documentary storytelling.

## 9. GitHub

The goal is to make **MemoryCurator generic enough for other trips, reunions, weddings, birthdays, and events.** A user should be able to configure trip folders, activity folders, enabled phases, activity profiles, AI backends, model paths, audio rules, and output types.

GitHub link:

```text
https://github.com/arunwagle/MemoryCuratorRepo
```

## 10. Future Roadmap

The next version should make MemoryCurator more intelligent and easier to use. The roadmap includes stronger local visual classification with OpenCLIP prompt sets, FAISS for scalable similarity search, YOLO or grounding models for object detection, stronger face detection with InsightFace or MediaPipe, OpenAI vision models for richer captions, local VLM support, Whisper/OpenAI transcription, beat-aware music editing, documentary chapter planning, and a lightweight review UI.

The bigger idea is simple: **most people do not need more media. They need help turning their media into memories they can actually revisit.**

That is what MemoryCurator is trying to become.

**Not just a media organizer. An AI memory curator.**

## Final Summary

MemoryCurator started with a simple vacation problem: **too many photos and videos, not enough time to turn them into something meaningful.**

The product idea became bigger than media organization. The real goal was to design a system that understands **activities, moments, people, chronology, quality, emotion, and story.**

The current version combines **deterministic Python, OpenCV, FFmpeg, audio analysis, face detection, OpenCLIP embeddings, configurable activity profiles, and AI-ready extension points.** Each phase produces transparent reports and manifests so every decision can be reviewed and improved.

The biggest takeaway is that good AI products are not built by asking one big prompt. They are built by combining clear product thinking, strong data contracts, fast iteration, and selective AI where semantics matter.

That is what MemoryCurator is trying to prove: **AI should not just process media. It should help preserve memories.**
