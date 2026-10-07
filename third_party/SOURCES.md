# Sources and immutable pins

The thin adapter code retains this repository's `Proprietary` license metadata
in [pyproject.toml](../pyproject.toml); this file does not relicense PokerSense.
No upstream solver implementation or binary is bundled. Saved-asset lookups
execute no solver; TexasSolver is built on the owner's machine and run as a
separate program (row below).

| Source | Pin | Use | Notice |
| --- | --- | --- | --- |
| [ucsandman/postflop](https://github.com/ucsandman/postflop/tree/5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de) | `5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de` | Existing synthetic saved frequency assets | [MIT at that exact source pin](postflop/LICENSE-5fc7ee3.txt) |
| [PokerKit](https://github.com/uoftcprg/pokerkit) | `0.7.5` | Native legal-menu/state replay and range expansion | [Installed distribution MIT notice](pokerkit/LICENSE-0.7.5.txt) |
| [TexasSolver](https://github.com/bupticybee/TexasSolver) (console branch) | commit `6dfb65b4d7ed081da509e8d8c3d82138c4708267` | Heads-up postflop solving. Downloaded and built on the owner's machine by `tools/setup_texassolver.sh` into the private data directory and called as a separate program by `src/poker_engine/solver/texassolver.py`; neither its source nor its binary is in this repository, and the built folder must not be shared (the author's FAQ allows calling the program from other software, not redistributing it) | [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) |
| [A Dataset of Poker Hand Histories](https://doi.org/10.5281/zenodo.13997158), Juho Kim (University of Toronto) | Zenodo record `13997158` (v2), zip MD5 `0918a30f97bda0129897b7e0f1ec895a` | Aggregate decision frequencies of real players in `src/poker_engine/scoreboard/phh_population_stats_v1.json`, counted by `tools/phh_population_stats.py`; no hand history is stored | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

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
