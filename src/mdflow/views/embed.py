"""Mode=embed view synthesizer.

Replaces each `![alt](figs/<sha>.<ext>)` ref with a base64 data URI:
`![alt](data:<content_type>;base64,<b64>)`. Code blocks protected.

Content-type is inferred from the ext segment of the canonical name
(reverse of _image_util.EXT_BY_CT). Missing figs/ file →
MdflowError(CACHE_IO_ERROR).
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from mdflow.converters._image_util import EXT_BY_CT
from mdflow.core.errors import ErrorCode, MdflowError

# Reverse EXT_BY_CT: ext -> content_type. First wins for duplicate exts.
_CT_BY_EXT: dict[str, str] = {}
for ct, ext in EXT_BY_CT.items():
    _CT_BY_EXT.setdefault(ext, ct)

# NOTE: [^\]]*  not  .*?  — matches Task 6 regex fix (alt cannot contain ])
_REF = re.compile(r"!\[([^\]]*)\]\(figs/([^)]+)\)")


def _content_type_for(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _CT_BY_EXT.get(ext, "application/octet-stream")


def synthesize(canonical_md: str, figs_dir: Path) -> str:
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

        def repl(m: re.Match[str]) -> str:
            alt = m.group(1)
            name = m.group(2)
            path = figs_dir / name
            try:
                data = path.read_bytes()
            except OSError as e:
                raise MdflowError(
                    ErrorCode.CACHE_IO_ERROR,
                    f"image {name} unreadable from figs/: {e}",
                ) from e
            b64 = base64.b64encode(data).decode("ascii")
            ct = _content_type_for(name)
            return f"![{alt}](data:{ct};base64,{b64})"

        out_lines.append(_REF.sub(repl, line))
    return "\n".join(out_lines)
