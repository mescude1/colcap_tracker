"""
bvc — supporting package for the Colcap Tracker dashboard generator.

Pure, dependency-light building blocks extracted from sura_tracker.py:
  • indicators — technical-indicator + risk math (no I/O)
  • period     — flexible --period string parsing
  • sentiment  — bilingual news sentiment / relevance helpers

The fetch/cache/render/CLI layers stay in sura_tracker.py, which re-exports
these names so the public API and the `python sura_tracker.py` entry point
are unchanged.
"""
