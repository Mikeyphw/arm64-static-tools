# AST Recovery R04 — PitchBlack graphical terminal font qualification

This R04 component does **not** modify `recovery.img`, the boot partition,
`/twres`, or the installed GUI. It builds an **opt-in compatible theme ZIP**
from a user-provided, SHA-256-approved complete PBRP theme and a user-provided,
SHA-256-approved Nerd Font **Mono** `.ttf`. No font file is bundled or supplied by AST.

## Upstream basis

PitchBlackRecoveryProject/android_bootable_recovery, `android-12.1`, inspected
2026-11-17, upstream HEAD `c3ee88af57d32a842b2a8ff861a72a7bf24da846`.
`gui/theme/portrait_hdpi/ui.xml` defines `<font name="cons" filename="DroidSansMono.ttf" size="30"/>`;
`gui/theme/common/portrait.xml` uses `<font resource="cons" .../>` in its
`terminal` style; `gui/terminal.cpp` renders glyphs through `gr_textEx_scaleW`
with `mFont->GetResource()`; `gui/resources.cpp` loads `.ttf` from the theme
ZIP's `fonts/` directory through FreeType. These source properties explain
how replacing **only** `cons` in a complete theme can affect the GUI terminal.
The exact installed device recovery/theme may differ and must be qualified.

## Build, without installing/flashing

Run from the AST source repository in a normal Termux host. Supply your own
compatible *monospaced* Nerd Font TTF with glyphs U+E0B0 and U+F013, and a
working complete PitchBlack theme ZIP from your device/build:

```sh
cd "$HOME/Code/arm64-static-tools-module"
sha256sum "$HOME/storage/downloads/pbrp-base-theme.zip" \
          "$HOME/storage/downloads/MyNerdFontMono.ttf"
python3 scripts/build_pbrp_nerd_theme.py \
  --theme "$HOME/storage/downloads/pbrp-base-theme.zip" \
  --theme-sha256 'COPY-EXACT-64-HEX-SHA256-OF-THEME' \
  --font "$HOME/storage/downloads/MyNerdFontMono.ttf" \
  --font-sha256 'COPY-EXACT-64-HEX-SHA256-OF-FONT' \
  --out "$HOME/storage/downloads/PBRP-AST-Nerd-Mono-theme.zip"
```

The builder refuses mismatches, unsafe/traversal/symlink ZIP members, multiple
`cons` resources, unsupported font format, missing glyphs, oversized payloads,
and any existing output. The resulting theme ZIP preserves all original member
contents except `ui.xml`'s `cons` filename and adds
`fonts/AST-NerdFontMono.ttf`. Preserve your original theme ZIP for rollback.

Install the generated theme **only via the verified recovery's ordinary GUI
configuration**, not by overwriting recovery partitions. Do not assume the
install path; PBRP versions and device builds differ. Confirm visually that
menus and terminal still work, then in the actual recovery terminal:

```sh
sh /data/local/tmp/ast font doctor
sh /data/local/tmp/ast font sample
sh /data/local/tmp/ast font confirm   # explicit interactive typed approval
sh /data/local/tmp/ast theme set modern
sh /data/local/tmp/ast shell
```

`ast font confirm` is a statement by the device operator that they actually
saw the glyphs, line wrapping, cursor placement and editing work. It does **not**
automatically prove that the device rendered the new font. Without confirmation,
`modern` in recovery falls back to the ASCII-safe compact prompt. To undo
approval use `sh /data/local/tmp/ast font reset`, select compact/minimal and
restore the original recovery theme in its GUI. AST never auto-installs a font.

## Physical acceptance matrix (not performed locally)

- PBRP build/image and theme ZIP identity, SHA-256, GUI resource loader and
  FreeType build compatibility confirmed on the *actual* device
- Glyph sample U+E0B0/U+F013 and ASCII fallback verified on screen; real font
  is monospace at terminal size
- Line wrapping, cursor position, long paths, wide Unicode and input editing
  checked on the PBRP GUI terminal, not just a Termux terminal
- PBRP GUI restart/theme restore and return to stock terminal tested; no data loss
- `ast --safe`, Zsh and BusyBox fallback tested while the custom theme is active

Until those checks pass, describe R04 as **theme builder implemented, recovery
renderer acceptance pending**, not a device-qualified font renderer modification.
Any actual recovery-image/FreeType engine patch must be separately scoped,
source-pinned, backed up, tested and approved for the specific device/build.
