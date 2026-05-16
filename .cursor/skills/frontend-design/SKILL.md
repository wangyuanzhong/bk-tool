---
name: frontend-design
description: >
  Distinctive UI and visual polish for BKCurveTool's pywebview HTML/CSS
  (primarily src/index.html). Load when changing layout, typography, color,
  spacing, status/list UX, or any aesthetic direction for the embedded UI.
---

# Frontend design (BKCurveTool)

## When to load

- Editing `src/index.html`, `src/splash.html`, or other static UI loaded by pywebview.
- Refactoring controls, list layout, status bar, buttons, or visual hierarchy.

## Design thinking (before coding)

- **Purpose**: Desktop utility for clipboard curve data — clarity and density matter; avoid decorative noise that slows scanning.
- **Tone**: Pick one direction and stay consistent — e.g. calm technical panel, high-contrast “instrument” UI, or restrained dark theme. Intentionality beats intensity.
- **Differentiation**: One or two memorable choices (typography pair, accent color, subtle border treatment) rather than a generic “template” look.

## Project constraints

- **Stack**: Plain HTML + `<style>` (or small inline blocks). No build step unless the repo already has one — prefer CSS variables and scoped class names over shipping a new framework.
- **Runtime**: pywebview; keep assets self-contained under `src/` unless `main.py` loading paths are updated deliberately.

## Typography

- Prefer a clear **display vs body** pairing if you introduce webfonts (with a system fallback stack).
- Avoid defaulting everything to generic “AI” stacks without intent; if you keep system fonts, tune weight, letter-spacing, and size scale for hierarchy.

## Color and theme

- Centralize tokens as **CSS custom properties** on `:root` (or a single wrapper) — e.g. `--bg`, `--surface`, `--text`, `--accent`, `--border`, `--danger`.
- One dominant background, one strong accent for primary actions; avoid evenly loud colors everywhere.
- Respect contrast for text and focus states (keyboard and small controls).

## Layout and composition

- This app uses **flex** for the main card and a **scrollable list** — preserve `min-height: 0` on flex children that scroll; do not let the list grow unbounded without `overflow`.
- Keep tap/click targets comfortable for filename inputs and row actions.

## Motion

- Prefer **CSS-only** transitions (hover/focus, subtle panel open). Avoid long or gratuitous animations on a data tool.

## Anti-patterns

- Generic “AI slop” look: purple gradients on white, random rounded-everything cards with no hierarchy.
- Scattering magic hex values — tie them to variables once you introduce a palette.
- Overuse of `!important` or duplicating the same utility blocks across unrelated rules without consolidation.

## Verification

- After visual changes, sanity-check in a **window size** typical for the tool (not only full-screen devtools).
- Ensure list scroll, status bar, and filename inputs still behave correctly with many rows.
