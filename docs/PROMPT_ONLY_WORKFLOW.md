# Prompt-Only MemoryCurator Workflow

This project can be used in two ways:

1. Run the Python engine locally.
2. Use the phase prompts as a design/playbook with Codex, ChatGPT, or another coding agent.

Prompt-only mode is useful when someone wants to reimplement the pipeline in another language, run only one phase, or ask an AI coding assistant to generate a custom version for their own folder layout.

## How to Use the Prompts

Start with these files in order:

```text
prompts/duplicate_detection_phase_1.md
prompts/quality_scoring_phase.md
prompts/story_builder_phase.md
prompts/album_builder_phase.md
prompts/video_processing_engine_phase.md
prompts/selected_timeline_phase.md
prompts/reel_builder_phase.md
prompts/documentary_builder_phase.md
```

For a new implementation, give the AI assistant:

- The relevant prompt file.
- Your desired input folder structure.
- Your trip YAML or a simplified config.
- A clear rule that originals must never be deleted, moved, or overwritten.
- The expected reports for the phase.

## Suggested Master Prompt

```text
You are implementing MemoryCurator, a config-driven media curation engine.

Use the attached phase prompt as the source of truth.

Project rules:
- Never delete, move, or overwrite original media.
- Treat each activity folder as the default activity tag.
- Write CSV/Markdown manifests for downstream phases.
- Generated media must go under input_data/trips/<trip>/curated.
- Runtime caches should stay local and must not be committed.
- Make the implementation generic for future trips, not hardcoded to one vacation.

Implement this phase with clean Python packages, config-driven behavior, dry-run support where relevant, and clear README updates.
```

## Prompt-Only Phase Map

| Phase | Prompt | Expected Result |
| --- | --- | --- |
| Duplicate Detection | `prompts/duplicate_detection_phase_1.md` | Duplicate groups, review queue, keeper manifest |
| Quality Scoring | `prompts/quality_scoring_phase.md` | Purpose-specific quality scores and manifest |
| Story Builder | `prompts/story_builder_phase.md` | Moment database by activity |
| Album Builder | `prompts/album_builder_phase.md` | Album selections and PDF export design |
| Video Processing | `prompts/video_processing_engine_phase.md` | Scene, clip, frame, audio, transcript, timeline reports |
| Selected Timeline | `prompts/selected_timeline_phase.md` | Master activity timeline selections |
| Reel Builder | `prompts/reel_builder_phase.md` | Instagram/highlight reel edit decisions |
| Documentary Builder | `prompts/documentary_builder_phase.md` | Long-form story plan and render decisions |

## When to Use the Python Engine Instead

Use the local engine when you want reproducibility:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
memory-curator --config input_data/trips/sample/config/default.yaml run-all
```

Prompt-only mode is best for adapting the architecture. The Python engine is best for repeatable runs on large media collections.
