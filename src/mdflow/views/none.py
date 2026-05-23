"""Mode=none view synthesizer.

Strips canonical markdown's `figs/<sha>.<ext>` image refs while
preserving alt text where present. External URL refs (non-figs/ paths)
pass through unchanged — they belong to the HTML converter's D7 policy.

Code blocks (``` ... ```) are protected: refs inside fences are not
touched.
"""

from __future__ import annotations

import re

_STANDALONE = re.compile(r"^\s*!\[([^\]]*)\]\(figs/[^)]+\)\s*$")
_INLINE = re.compile(r"!\[([^\]]*)\]\(figs/[^)]+\)")


def synthesize(canonical_md: str) -> str:
    out_lines: list[str] = []
    in_code = False
    for line in canonical_md.split("\n"):
        if line.lstrip().startswith("```"):
            out_lines.append(line)
            in_code = not in_code
            continue
        if in_code:
            out_lines.append(line)
            continue
        sm = _STANDALONE.fullmatch(line)
        if sm:
            alt = sm.group(1)
            if alt:
                out_lines.append(alt)
            # else: drop the line entirely
            continue
        replaced = _INLINE.sub(lambda m: m.group(1), line)
        out_lines.append(replaced)
    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text)
