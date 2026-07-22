# Contributing to MemoryCurator

Thanks for considering a contribution.

MemoryCurator is a config-driven media curation engine. The most valuable contributions improve correctness, portability, privacy, and the quality of generated albums, timelines, reels, and documentaries.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For Databricks-proxy environments:

```bash
pip install -r requirements-databricks.txt
pip install -e . --no-deps
```

## Contribution Guidelines

- Never add personal media files to the repo.
- Do not commit generated MP4, MOV, HEIC, JPG, PNG, PDF, or cache files unless they are intentional documentation assets under `docs/`.
- Keep behavior config-driven; avoid hardcoding a specific trip, person, camera, or filename.
- Preserve originals. Normal phases must not delete, move, or overwrite source media.
- Prefer CSV/Markdown manifests as phase handoffs.
- Keep optional AI/ML features optional and gracefully degradable.

## Good First Issues

- More sample configs for weddings, birthdays, sports, and road trips.
- Better activity profiles.
- Improved face cutoff detection.
- More robust video capture-time extraction.
- Public sample dataset and expected report snapshots.
- Tests for phase handoffs and config validation.

## Pull Request Checklist

- The change is generic and not hardcoded to one trip.
- New config keys are documented.
- Prompts are updated when phase behavior changes.
- Runtime/generated files are not included.
- The command line still works with `memory-curator --help`.
