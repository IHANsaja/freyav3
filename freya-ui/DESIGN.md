---
name: Crimson Archival
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#e4beba'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#ab8985'
  outline-variant: '#5b403d'
  surface-tint: '#ffb3ac'
  primary: '#ffb3ac'
  on-primary: '#680008'
  primary-container: '#d32f2f'
  on-primary-container: '#fff2f0'
  inverse-primary: '#ba1a20'
  secondary: '#ffb4a8'
  on-secondary: '#690000'
  secondary-container: '#920703'
  on-secondary-container: '#ff9a8a'
  tertiary: '#c8c8b0'
  on-tertiary: '#303221'
  tertiary-container: '#70715d'
  on-tertiary-container: '#f6f6dd'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffdad6'
  primary-fixed-dim: '#ffb3ac'
  on-primary-fixed: '#410003'
  on-primary-fixed-variant: '#930010'
  secondary-fixed: '#ffdad4'
  secondary-fixed-dim: '#ffb4a8'
  on-secondary-fixed: '#410000'
  on-secondary-fixed-variant: '#920703'
  tertiary-fixed: '#e4e4cc'
  tertiary-fixed-dim: '#c8c8b0'
  on-tertiary-fixed: '#1b1d0e'
  on-tertiary-fixed-variant: '#474836'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  display-lg:
    fontFamily: Sora
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Sora
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Sora
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  title-md:
    fontFamily: Sora
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Sora
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 32px
  body-md:
    fontFamily: Sora
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 28px
  code-sm:
    fontFamily: Sora
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Sora
    fontSize: 12px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
spacing:
  base: 8px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 64px
  max-width: 1100px
---

## Brand & Style
The brand personality is a fusion of scholarly precision and modern computational power. It evokes the feeling of a digital library or an advanced archival terminal—intellectual, authoritative, and focused. The target audience includes researchers, developers, and power users who value high-density information presented with editorial elegance.

The design style is a hybrid of **Minimalism** and **Modern Brutalism**. It utilizes the expansive whitespace and typographic hierarchy found in premium editorial platforms, but grounds it with the sharp, utilitarian structures of a command-line interface. The aesthetic is strictly matte; it avoids all glassmorphism, glows, or synthetic gradients in favor of flat, tonal layering and rich, textured color values.

## Colors
The palette is built on a "Matte Archival" foundation. The primary experience occurs on a **Matte Black** (#121212) base, providing a high-contrast canvas that reduces eye strain during long sessions.

- **Primary Crimson (#D32F2F):** Used for critical actions, active states, and focus indicators. It represents the "pulse" of the AI.
- **Secondary Muted Blood (#8B0000):** Used for supportive UI elements, such as categorized tags or subtle borders, maintaining the theme without overwhelming the content.
- **Warm Parchment (#F5F5DC):** This is the primary ink color. Unlike pure white, this cream tone provides a sophisticated, "paper-like" readability against the dark surfaces, softening the digital harshness.
- **Deep Charcoal (#1A1A1A):** Employed for container backgrounds to create tonal depth through layering rather than shadows.

## Typography
The system uses **Sora** exclusively to achieve a modern, geometric clarity. To maintain an editorial feel, the typography relies on generous line heights and intentional weight contrasts.

- **Editorial Hierarchy:** Large display titles use a bold weight with tight letter spacing for impact. 
- **Readability:** Body text is set with an expanded line height (1.75x) to ensure the AI's long-form responses feel approachable and easy to scan.
- **Technical Accents:** Labels and metadata use uppercase styling with increased letter spacing to mimic archival indexing and technical logs.

## Layout & Spacing
The layout follows a **Fixed Grid** philosophy for content readability, centered within the viewport. While the UI containers may feel "dense" in terms of information, they are surrounded by expansive margins to prevent visual clutter.

- **The Archival Column:** AI responses are contained within a central column (max-width: 800px) to mimic a page-turning experience.
- **Breakpoints:** 
  - **Mobile (<600px):** 4 columns, 16px margins, fluid containers.
  - **Tablet (600px-1024px):** 8 columns, 24px margins.
  - **Desktop (>1024px):** 12 columns, 64px margins, fixed central content area.
- **Density:** Interaction elements (sidebars, inputs) use a 4px-increment system for a tighter, more technical feel, while editorial content uses an 8px-increment system for breathing room.

## Elevation & Depth
This system rejects traditional shadows. Depth is achieved exclusively through **Tonal Layering** and **Borders**.

- **Surface Levels:** The base is #121212. Overlays and containers use #1A1A1A. This subtle 2-8% brightness shift defines hierarchy without breaking the matte aesthetic.
- **Outlines:** Use 1px solid borders in #8B0000 (Secondary) or #2A2A2A (Neutral) to define boundaries. 
- **Depth Cues:** Active states are indicated by color fills (Crimson) rather than lifting the element off the page. This keeps the interface feeling grounded and "printed" on the screen.

## Shapes
The shape language is a deliberate study in contrast.

- **Structural Elements:** Containers, sidebars, and code blocks use **Sharp Corners (0px)**. This reinforces the "archival terminal" feel and technical rigidity.
- **Interactive Elements:** Primary buttons and chips utilize **Pill-shaped (Full Radius)** geometry. This creates a high-contrast visual cue that distinguishes clickable elements from static content.
- **Subtle Softness:** For input fields, a 2px radius may be used to provide a hint of approachability within the otherwise sharp architecture.

## Components
- **Buttons:** Primary buttons are pill-shaped with a Crimson (#D32F2F) fill and Parchment (#F5F5DC) text. Secondary buttons are pill-shaped with a 1px Crimson border and no fill.
- **Input Fields:** Rectangular with sharp corners. 1px border in Charcoal (#2A2A2A), turning Crimson on focus. 
- **Cards/Containers:** Hard-edged rectangles. Background: #1A1A1A. No shadows.
- **Chips/Tags:** Small pill-shaped elements with Secondary (#8B0000) background and Parchment text, used for categories or AI model indicators.
- **AI Activity Indicator:** A subtle SVG animation in the corner of the input or header. It features a "data stream" — vertical 1px lines pulsing at varied intervals in Crimson, representing background processing.
- **Lists:** Clean, border-bottom only (1px solid #1A1A1A). Generous vertical padding (16px) to maintain the editorial feel.