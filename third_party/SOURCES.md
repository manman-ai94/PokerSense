# Sources and immutable pins

The thin adapter code retains this repository's `Proprietary` license metadata
in [pyproject.toml](../pyproject.toml); this file does not relicense PokerSense.
No upstream solver implementation or binary is bundled or executed by lookup.

| Source | Pin | Use | Notice |
| --- | --- | --- | --- |
| [ucsandman/postflop](https://github.com/ucsandman/postflop/tree/5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de) | `5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de` | Existing synthetic saved frequency assets | [MIT at that exact source pin](postflop/LICENSE-5fc7ee3.txt) |
| [PokerKit](https://github.com/uoftcprg/pokerkit) | `0.7.5` | Native legal-menu/state replay and range expansion | [Installed distribution MIT notice](pokerkit/LICENSE-0.7.5.txt) |

The existing `solver-tools` extra already pins PokerKit 0.7.5. Its existing CI
installation step is moved before pytest so the saved-asset tests execute.
No new dependency is added; local integration uses the existing runtime.

`tests/fixtures/hu_saved/MANIFEST.json` binds the three saved solution files and
their synthetic golden ROOT query data. Solutions are copied without byte
changes. Only each golden file's machine-specific `solution_file` metadata is
made relative; all query frequencies and other semantic values remain equal.
These are synthetic fixtures with no recorded game, personal player data,
credential or device content. The frozen four-node asset is independently
SHA-bound in its provider. Turn coverage is only its two catalogued decisions;
complete turn BR and chance crossings are not certified by inclusion of a file.
