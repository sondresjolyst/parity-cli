"""Map a repo's languages to template directories."""

from __future__ import annotations

from .config import Config


def template_dirs(languages: dict[str, int], config: Config) -> list[str]:
    total = sum(languages.values())
    dirs: list[str] = []
    if total:
        for lang, count in sorted(languages.items(), key=lambda kv: -kv[1]):
            if count / total < config.language_threshold:
                continue
            mapped = config.language_map.get(lang)
            if mapped and mapped not in dirs:
                dirs.append(mapped)
    return dirs
