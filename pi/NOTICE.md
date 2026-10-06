# Source attribution

The lifecycle engine, footer, prompts, threshold helpers, state recovery, summary generation, and most tests are adapted from [disler/self-compact-pi-agent](https://github.com/disler/self-compact-pi-agent), reviewed on 6 October 2026. The upstream MIT license is reproduced in `LICENSE`.

Local changes add a Pi package manifest, automatically loaded layered JSON configuration with a direct maximum threshold, configuration provenance, model-aware cutoff resolution, an isolated offline test profile, and configuration tests. The engine's upstream built-in defaults remain 10% / 20% / 30%; this package's automatically loaded example configuration is 40% / 55% / 65%.

The upstream Justfile, credential loading, paid-model tests, and personal installation workflow are not included. No extension has been installed by building or testing this package.

Version 0.1.1 adds standalone source and runtime distribution archives, GitHub installation instructions, and a relocation test exercising the shipped runtime through a complete note-first compaction cycle. The manifest permits later npm publication; no npm name or GitHub repository is claimed as published.
