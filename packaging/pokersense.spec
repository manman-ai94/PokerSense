# Canonical Windows package: AA-only, offline by default.
# macOS retains the explicitly legacy development shell.
import sys
from pathlib import Path

root = Path(SPECPATH).resolve()
spec = root / ('aa_live.spec' if sys.platform == 'win32'
               else 'pokersense_legacy.spec')
exec(compile(spec.read_text(encoding='utf-8'), str(spec), 'exec'))
