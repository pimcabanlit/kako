# Kako look and feel: tokens

The palette, type and shapes of Kako's web app. The values come from the "Kako Look and Feel" preview Claude
built on Nov 24, 2026 from Pim's direction (emerald and teal, gold and amber, orange, charcoal, white type,
Meko-inspired glass). Every text colour was checked against WCAG AA (4.5:1 or better) on `bg`, `surface` and
`raised` in its own theme. The web app holds them in `web/src/app/globals.css` (the tokens, under the same names)
and `web/src/app/layout.tsx` (the fonts); change them there and here together.

Status (Nov 25, 2026): built into the session screen (Phase 5, task 1). Pim has not yet approved or changed the
direction; a change goes here first, then into the theme.

## Colour tokens

Dark is the default (the video is shot in dark). Light uses the same token names with deeper colours.

| Token | Dark | Light | Use |
| --- | --- | --- | --- |
| `bg` | `#0A0F0D` | `#F5F7F4` | Page ground. Charcoal with a slight green lean |
| `surface` | `#111916` | `#FFFFFF` | Cards, panels |
| `raised` | `#17221E` | `#EEF3EF` | User chat bubbles, secondary buttons, active tab |
| `line` | `#22302B` | `#DCE5E0` | Borders, table rules |
| `line-strong` | `#2E3F39` | `#C6D3CC` | Stronger borders, button outlines |
| `glass` | `rgba(23,34,30,.66)` | `rgba(255,255,255,.82)` | Translucent panels, with `backdrop-filter: blur(10px)` |
| `fg` | `#F2F6F3` (17.7:1) | `#0D1613` (17.1:1) | Body text. Never pure white |
| `muted` | `#9DAEA6` (8.3:1) | `#52625B` (6.0:1) | Secondary text, labels, timestamps |
| `emerald` | `#34D399` (10.1:1) | `#047857` (5.1:1) | Brand. Current, approved, on track. Main button |
| `teal` | `#2DD4BF` (10.4:1) | `#0F766E` (5.1:1) | Links, focus rings, tool names in agents' steps |
| `gold` | `#FCD34D` (13.4:1) | `#8A5A00` (5.5:1) | Waiting for the household's yes: approval cards, dreaming's proposals, "to revisit" |
| `orange` | `#FB923C` (8.5:1) | `#C2410C` (4.8:1) | Changed: life events, lines in "what changed". Use sparingly |
| `rose` | `#FB7185` (7.2:1) | `#BE123C` (5.8:1) | Off track, rejected options, failed what-ifs, retracted facts, errors |
| `meko` | `#B9A4FF` (9.0:1) | `#6D3FD6` (5.9:1) | Only on things that came from Meko (memories, knowledge, traces) |
| `on-accent` | `#04221A` | `#FFFFFF` | Text on primary and gold buttons |

Soft fills for chips (background behind the coloured text; border is the colour at 30% mixed with transparent):

| Token | Dark | Light |
| --- | --- | --- |
| `emerald-soft` | `rgba(52,211,153,.12)` | `#E1F3EA` |
| `gold-soft` | `rgba(252,211,77,.12)` | `#FBF0CF` |
| `orange-soft` | `rgba(251,146,60,.13)` | `#FDE9DC` |
| `rose-soft` | `rgba(251,113,133,.12)` | `#FCE7EB` |
| `meko-soft` | `rgba(185,164,255,.13)` | `#EEE8FD` |

Gradients:

| Token | Dark | Light |
| --- | --- | --- |
| `btn` (primary) | `linear-gradient(100deg, #34D399, #2DD4BF)`, text `on-accent` (8.8:1) | `linear-gradient(100deg, #047857, #0F766E)`, white (5.5:1) |
| `btn-gold` (promote) | `linear-gradient(100deg, #FCD34D, #FB923C)`, text `on-accent` (7.4:1 worst) | `linear-gradient(100deg, #8A5A00, #A8480B)`, white (5.8:1 worst) |
| `grad-text` | `90deg: #34D399 0%, #2DD4BF 35%, #FCD34D 70%, #FB923C 100%` | `90deg: #047857, #0F766E, #8A5A00, #C2410C` |

Page background (both themes): `bg` plus two faint halos, emerald top left and orange right:
`radial-gradient(60rem 36rem at 8% -6%, halo-a, transparent 60%), radial-gradient(50rem 30rem at 100% 40%, halo-b, transparent 60%)`,
with `halo-a` = `rgba(16,185,129,.16)` dark / `.10` light and `halo-b` = `rgba(249,115,22,.10)` dark / `.07` light.
Gold dust (tiny 1 to 1.4px radial dots) uses `dust` = `rgba(252,211,77,.55)` dark / `rgba(161,92,0,.30)` light.

## One meaning per colour

| State | Colour | Examples |
| --- | --- | --- |
| Current | emerald | A fact true now, an approved decision, a figure on track |
| Waiting for your yes | gold | A proposal from an agent or dreaming. Nothing gold is household knowledge yet |
| Changed | orange | A life event, a row in "what changed" |
| Replaced | muted, struck through | The old value, kept, never deleted (e.g. ~~₱52,000~~ replaced) |
| Rejected | rose | An option turned down, a failed what-if, a retracted mistake |
| From Meko | meko violet | A memory, a knowledge entry, a trace, a `context_search` call |

Orange and rose are kept apart on purpose, so a pay raise never looks like a warning.

Comparing an option with today's plan (Pim, Nov 25) uses two of these for the change: emerald when
the option is better for the household (paid off sooner, less interest, a target reached), rose when
it is worse (later, more, never reached), and a plain chip when nothing changes. Each chip carries
its words ("38 months sooner", "never reached"), so the colour never stands alone. What is left
unplanned gets no chip: it is the household's to plan, neither better nor worse.

## Charts

The money screen's donut (where each peso of the pay goes) has a palette of its own, so a part of the
pay never borrows a state colour above. Each colour means one part, nothing else, always in this
order clockwise from twelve o'clock. Checked with a colour-vision-deficiency validator against each
theme's panel: dark passes every check; light passes with a contrast warning, so the legend beside
the ring always carries each part's name, amount and share in words.

| Token | Part | Dark | Light |
| --- | --- | --- | --- |
| `chart-needs` | Needs | `#338CED` | `#257DE0` |
| `chart-wants` | Wants | `#E76624` | `#F47230` |
| `chart-debt` | Debt | `#00A888` | `#00B894` |
| `chart-savings` | Savings | `#D28E05` | `#F2A600` |
| `chart-unplanned` | Not planned yet (neutral) | `#5D6E67` | `#A7B5AE` |

Segments are separated by a 2px gap in the panel's colour. Hovering a segment or its legend row
names it in the middle of the ring; text stays in the text colours, never the part's colour.

## Type

| Role | Family | Weights | Where |
| --- | --- | --- | --- |
| Display | Unbounded | 500, 700 | Wordmark (700, lowercase "kako", letter-spacing -0.02em), page titles, panel titles (500), one big figure per screen |
| Text | Plus Jakarta Sans | 400, 500, 600, 700 | Everything else. Tabular figures (`font-variant-numeric: tabular-nums`) wherever pesos appear |
| Working | Geist Mono | 400, 500 | Tool calls, formulas, ids, the agents' steps |

All three carry the peso sign ₱ (checked against the Google Fonts files). Sora, Outfit and JetBrains Mono do not, so
avoid them. Fallbacks: `system-ui, sans-serif` and `ui-monospace, Menlo, Consolas, monospace`. In Next.js, load
them with `next/font/google`.

Sizes used in the preview: body 15px / line-height 1.55; chat bubble 14.5px; panel title 17px Unbounded 500
(letter-spacing -0.015em); section title 22 to 28px Unbounded 500 (-0.02em); page title 28 to 44px Unbounded 500
(-0.025em); hero figure 30px Unbounded 500 (-0.02em); labels and eyebrows 11.5px, 600, uppercase, letter-spacing
0.14em; chips 12.5px 600; meta text 12.5 to 13.5px; mono 12.5 to 13px.

## Shape, glow and shadow

- Radii: chips and pills 999px; buttons 10px; panels 18px; app frame 22px; list rows 16px; small cards 14px.
- Panels: `glass` fill, 1px `line` border, `backdrop-filter: blur(10px)`, padding 18px, inner gap 14px.
- **The glow means state, never decoration.** A stateful card gets a 2px top edge from 14% to 86% of its width:
  `linear-gradient(90deg, transparent, <state colour>, transparent)` with
  `box-shadow: 0 0 18px 2px <state colour at 55%>`, and its border becomes the state colour at 34 to 38% mixed
  into `line`. Gold = waiting, emerald = approved, orange = changed.
- Only a card waiting for a yes animates: the edge sweeps left to right over 4.5s. Off under
  `prefers-reduced-motion`. On approval the card turns emerald and the chip reads "Current".
- Shadow: dark `0 1px 0 rgba(255,255,255,.04) inset, 0 20px 50px -24px rgba(0,0,0,.7)`; light
  `0 1px 2px rgba(13,22,19,.05), 0 18px 40px -26px rgba(13,22,19,.35)`. Use on the app frame and title card, not on
  every panel.
- Primary button shadow: `0 6px 20px -8px <emerald at 70%>`; gold button uses orange at 70%.
- Focus: 2px `teal` outline, offset 2px.

## Style rules

1. Dark first, light just as finished.
2. Glass cards on charcoal; the glow means state.
3. One gradient phrase per screen (`grad-text`), on a key phrase, never on numbers.
4. The swirl art (Pim's title card) only on big moments: the video's first frame, empty states, the first screen.
5. Violet means Meko, nowhere else.
6. Pesos line up: tabular figures, two decimals in tables, whole pesos in sentences, ₱ before the number.
7. Every screen keeps the line "Synthetic data. Not financial advice."

## Open

- Pim's approval of this direction (no changes requested yet).

## Decided

- Layout: like ChatGPT, Claude and Gemini (Pim, Nov 25): the sessions down the left, the conversation in the
  middle, the composer at the bottom. See [architecture.md](architecture.md#the-session-screen).
- Screens (Pim, Nov 25): a screen's title large at the top left (Unbounded 500, 28px on a phone,
  34px wide), with its views as chips under it; lists and cards first, one line or one card per
  item, and an item's details in a sheet (from the right, or from the bottom on a phone). Built on
  the timeline first (`PageHeader`, `ViewChips`, `DetailSheet`).
- Decisions as books (Pim, Nov 25): each decision a book on a shelf, opened at three bookmarks on one
  row. A book's cover is a coloured object, the same in both themes, its colour and pattern standing
  for the session it was made in: the one place colour is decoration, so covers keep to deep teal,
  green and brown and never use a state colour. The gold ribbon on a cover means "to revisit", as
  gold does everywhere. The open bookmark takes its own colour (emerald the decision, gold to
  revisit, teal the facts); an option turned down is greyed, with no colour.
- The swirl art (Pim's title card, `web/public/swirl.jpg`, 1400 x 724) sits on the empty new-session screen.
- The mark (Pim, Nov 25): three rising bars, emerald, gold and orange, over an orange swoosh
  (`web/public/kako-mark.png`, 256 x 256, transparent, so it sits on both themes). It goes to the left of the
  wordmark (26px beside the sidebar's 22px "kako", 22px on a phone's top bar) and alone at the top of the
  collapsed sidebar. It is a picture beside the word, never in place of it.
- The sidebar collapses (Pim, Nov 25), as ChatGPT's does: the panel icon at the header's right, after the theme
  switch, folds it to a 60px rail of icons; on the rail the mark turns into the panel icon under the pointer or
  the keyboard's focus and opens it again.
- The fonts load with `next/font/google` and the `latin-ext` subset as well as `latin`: the peso sign (U+20B1) is
  only in `latin-ext`.
- The theme is kept per device (`kako-theme` in local storage) and set before the first paint, so it never flashes.
