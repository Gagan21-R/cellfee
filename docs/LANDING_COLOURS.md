# Landing page colours

The landing page (`experience/index.html`, served at `/`) now uses the dashboard's palette
(`frontend/src/styles.css`, `:root`). Only colours changed. Layout, typography, timing, easing, keyframes,
scroll logic and the canvas geometry are untouched, and no dashboard file was modified.

## Where the colours live

All of the landing page's colours are defined in **one `:root` block at the top of `experience/index.html`**.
- CSS reads them with `var(--…)`. Translucent colours use `color-mix(in srgb, var(--token) N%, transparent)`
  instead of hard-coded `rgba(…)`.
- The canvas script reads them **once at start-up** through `TOK("--name")` (an `[r, g, b]` array) and
  `HEX("--name")` (a string), then stores them in `COL`. No colour literals are left in the drawing code.
- Two literals remain on purpose: the `<meta name="theme-color" content="#f2eee3">` tag (meta tags can't read
  CSS variables) and a `#000` in a CSS mask. A mask uses only alpha, so its colour is never visible.

## Old → new mapping

| Role | Old (dark) | New token | New value | Dashboard source |
|---|---|---|---|---|
| Page and scene background | `--paper` #101010 | `--paper` | #f2eee3 | `--paper` |
| Primary text, borders, closing band | `--ink` #fffdf9 | `--ink` | #0b0b0b | `--ink` |
| Secondary / metadata text | `--fog` #6f879c | `--fog` | #3b3a36 | `--ink-2` (see exceptions) |
| Hairlines | `--ash` #403f3f | `--ash` | #0b0b0b | border colour (ink) |
| Glow behind the module | `--veil` #495764 | `--fog` at 16–42% | — | — |
| Light surfaces (live panel, macro card) | #141516, rgba(16,16,16,.86) | `--card` | #fffdf7 | `--card` |
| Text and strokes on the ink band | rgba(255,253,249,…) | `--on-ink` | #fffdf7 | `--card` |
| Accent: CTA hover, sweep, selection | (none; hover was bone) | `--yellow` | #ffe14d | `--yellow` |
| REUSE | #17b26a / #3fd08d | `--reuse` | #00875f | `--green` |
| TEST | #f5a524 / #f5b544 | `--test` | #b25e00 | `--amber` |
| RECYCLE | #e5484d / #ff6b6f | `--recycle` | #d62418 | `--red` |
| Text on REUSE/TEST/RECYCLE fills | #111, #0b0b0b | `--on-disp` | #ffffff | (see exceptions) |
| Small REUSE text on light surfaces | #3fd08d | `--reuse-text` | #007150 | darker `--green` (see exceptions) |
| Giant background letters | `--giant` #17181a | `--giant` | #dddad0 | paper mixed 9% toward ink |
| Studio light gradient | #1e2328 → #141618 → #101010 | `--studio-0/1/2` | #fffdf7 → #f2eee3 → #e7e2d4 | card → paper → deeper paper |
| Vignette edge | rgba(0,0,0,.55) | `--vig` | #c4c1b8 | paper mixed 20% toward ink |
| Menu pop-up | #141516, hover #1d1f21 | `--ink` / `--on-ink` 10% | — | ink surface |
| Card shadows | none | `--sh`, `--sh-sm` | 4px / 2px hard offset in ink | dashboard hard shadows |
| Tag / chip tints | — | `--lilac --mint --peach --pink` | #dcd6ff #c9f3e2 #ffe7b8 #ffd6d0 | the same names |

**Canvas materials** (`--c-*`). Each old value was moved onto the dashboard's warm paper and ink family at a
similar lightness, so the 3-D shading reads the same:

| Material | Old | New |
|---|---|---|
| paper / label | [236,235,230] / [232,230,222] | `--c-paper` #ece7da / `--c-label` #f2eee3 |
| graphite casing | [62,66,76] | `--c-graphite` #3e3c37 |
| BMS board (pcb) | [24,92,72] | `--c-pcb` #0b5c43 |
| nickel / bus bar | [186,192,198] | `--c-nickel` #c2bcb0 / `--c-busbar` #918b7e |
| cell wrap | [44,58,76] | `--c-wrap` #2e2c28 |
| platform | [214,212,205] | `--c-platform` #dcd6c8 |
| red / black terminal | [196,52,46] / [30,32,36] | `--c-red` #d62418 / `--c-black` #1e1d1b |
| terminal gradient | #f4f5f6 → #9ea4aa | `--c-term-hi` #f7f4ec → `--c-term-lo` #a49e90 |
| highlight / edge strokes | rgba(255,255,255,…) / rgba(0,0,0,…) | `--c-hi` #fffdf7 / `--c-edge` #0b0b0b (same alpha) |
| contact shadow | rgba(40,36,30,…) | `--c-shadow` #232220 (same alpha) |
| caps, print, traces, chip, pads, LED, tray, glass, pack/test/recycle platforms | inline literals | `--c-cap --c-cap2 --c-print --c-trace --c-trace2 --c-chip --c-pad --c-led --c-tray --c-glass --c-glass-top --c-plat-pack --c-plat-test --c-plat-recycle` |

In total there were 82 colour replacements; every alpha value was kept.

## Verification

**Frozen-code diff.** I compared the original and the recoloured file with colour values masked out.
- The only differences are colour declarations, the new token block, the theme-color meta tag,
  `::selection`, the `:focus-visible` outline colour and the `TOK`/`HEX` reads.
- Every timing fragment (`animation`, `transition`, `@keyframes`, durations, easings) is identical.

**Layout.** I compared the bounding box of every element at scroll positions 0, 0.15, 0.35, 0.55, 0.75 and 0.95.
The original and new files were captured in the same browser session, at the same URL, after `document.fonts.ready`.
- Desktop 1440×960: identical at all 6 positions (230–253 elements each). I re-ran this check after the contrast
  fixes below.
- Phone 390×844: identical at all 6 positions. I ran this check before the contrast fixes; those fixes change text
  colours only.

**Motion.** All 27 animation/transition rules are identical, and so are the 5 infinite animations
(name, duration, delay, easing, iterations).

**Console.** No errors.

**Screenshots.** `docs/landing-recolour-comparison.png` shows before, after, the closing band and the dashboard
side by side. It was taken before the text-only contrast fixes.

**Contrast** (WCAG 2.1 AA: 4.5:1 for small text, 3:1 for large text). Each pair was measured against its worst
real background, including the darkest corner of the vignette.

| Pair | Ratio | |
|---|---|---|
| Ink text on paper | 16.98:1 | ✅ |
| Caption tag / small text (`--fog` = ink-2) on vignette corner | 7.39:1 | ✅ fixed (was 4.36:1 with ink-3) |
| HUD (ink 75%) on vignette corner | 7.15:1 | ✅ fixed (was ink 62%) |
| Macro source line (ink 62%) on card | 5.55:1 | ✅ fixed (was ink 50%) |
| Live REUSE text `#007150` on card 86% | 5.83:1 | ✅ fixed (was #00875f, 4.38:1) |
| Pill text #ffffff on REUSE green | 4.53:1 | ✅ fixed (#fffdf7 was 4.46:1) |
| Pill text #ffffff on TEST amber / RECYCLE red | 4.67:1 / 5.09:1 | ✅ |
| `--on-ink` text on the ink band | 19.35:1 | ✅ |
| Ink on the yellow CTA hover | 15.12:1 | ✅ |

## Exceptions: where the exact dashboard colour was not kept

1. **`--fog` uses `--ink-2` (#3b3a36), not `--ink-3` (#6b675d).** Ink-3 fell to 4.36:1 where captions sit over
   the vignette edge.
2. **`--on-disp` is #ffffff, not the dashboard card colour #fffdf7.** The card colour on REUSE green measured 4.46:1.
3. **`--reuse-text` (#007150)** is a darker reuse green used only for small text on light surfaces. Filled
   REUSE areas still use the dashboard green #00875f.
4. **Text opacities changed.** The HUD went from ink 62% to 75%, and the macro source line from 50% to 62%.
5. **Hard shadows were added** to the live panel, the macro card and the menu, to match the dashboard's
   card style. Shadows don't affect layout; the bounding-box check above confirms this.
6. **Literals kept:** the theme-color meta tag, and the `#000` in the mask (alpha only, never visible).

## How to change a landing-page colour

Edit the token in the `:root` block at the top of `experience/index.html`, and nothing else.
- CSS picks the change up through `var()`.
- The canvas reads every `--c-*` and disposition token once at start-up, so a reload applies the change
  to the 3-D module too.
- Write canvas tokens as 6-digit hex (`#rrggbb`), because `TOK()` parses exactly that format.
- To keep the landing page in step with the dashboard, copy the value from `frontend/src/styles.css`.
- If the token is used for text, re-check its contrast against its worst background (the vignette corner for
  scene text, the card for panels) before you ship.
