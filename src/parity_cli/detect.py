"""Map a repo's languages to template directories."""

from __future__ import annotations

from .config import Config

# Languages exempt from language_threshold: a single file (e.g. one
# Dockerfile) is a meaningful signal regardless of its byte share.
THRESHOLD_EXEMPT_LANGUAGES = {"Dockerfile"}


def template_dirs(languages: dict[str, int], config: Config) -> list[str]:
    total = sum(languages.values())
    dirs: list[str] = []
    if total:
        for lang, count in sorted(languages.items(), key=lambda kv: -kv[1]):
            exempt = lang in THRESHOLD_EXEMPT_LANGUAGES
            if not exempt and count / total < config.language_threshold:
                continue
            mapped = config.language_map.get(lang)
            if mapped and mapped not in dirs:
                dirs.append(mapped)
    return dirs
