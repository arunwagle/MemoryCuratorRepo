# Open Source Release Checklist

MemoryCurator already has an Apache 2.0 license. Before making the repository public or announcing it broadly, use this checklist.

## Privacy and Data Safety

- Do not commit raw photos, videos, generated reels, generated PDFs, or documentaries.
- Do not commit runtime caches; they are local and reproducible.
- Review generated CSV/Markdown reports before publishing. They may contain personal filenames, folder names, timestamps, device metadata, or activity details.
- Prefer publishing `input_data/trips/sample/config/default.yaml` as the starter config.
- If you keep the Bali config, remove private paths, names, and anything you would not want indexed by search engines.

## Repository Hygiene

- Keep `requirements.txt` on public PyPI.
- Keep company-specific package indexes in a separate file such as `requirements-databricks.txt`.
- Keep `pyproject.toml` updated so users can install with `pip install -e .`.
- Make sure `memory-curator --help` works after install.
- Add small sample media later if licensing is clear, or link to a public sample dataset.

## User Experience

The first successful user journey should be:

```bash
git clone https://github.com/arunwagle/MemoryCuratorRepo.git
cd MemoryCuratorRepo
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
memory-curator --config input_data/trips/sample/config/default.yaml inventory
```

Then the user should copy their media into:

```text
input_data/trips/sample/data/<activity>/
```

and run:

```bash
memory-curator --config input_data/trips/sample/config/default.yaml run-all
memory-curator --config input_data/trips/sample/config/default.yaml run-all --execute
```

## Prompt-Only Users

Some users will only want the design prompts. Keep `prompts/` and `docs/PROMPT_ONLY_WORKFLOW.md` usable without needing the Bali media or generated reports.

## Recommended GitHub Files

Add these before a wider launch:

- `CONTRIBUTING.md`
- `SECURITY.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/pull_request_template.md`

## Suggested First Public Release

- `v0.1.0`: local Python engine, prompt library, sample config, no hosted service.
- Clearly mark AI and OpenCLIP features as optional.
- Clearly mark the project as alpha because scoring/editing taste will keep evolving.
