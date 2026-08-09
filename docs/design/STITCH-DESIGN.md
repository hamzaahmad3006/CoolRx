---
name: Urban Environmental Intelligence
colors:
  surface: '#faf9fb'
  surface-dim: '#dbd9dc'
  surface-bright: '#faf9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3f6'
  surface-container: '#efedf0'
  surface-container-high: '#e9e8ea'
  surface-container-highest: '#e3e2e4'
  on-surface: '#1b1c1e'
  on-surface-variant: '#42474c'
  inverse-surface: '#303032'
  inverse-on-surface: '#f2f0f3'
  outline: '#73787d'
  outline-variant: '#c2c7cd'
  surface-tint: '#43627a'
  primary: '#123349'
  on-primary: '#ffffff'
  primary-container: '#2b4a61'
  on-primary-container: '#9ab9d4'
  inverse-primary: '#abcae6'
  secondary: '#3d692d'
  on-secondary: '#ffffff'
  secondary-container: '#bdf1a5'
  on-secondary-container: '#436f32'
  tertiary: '#452b06'
  on-tertiary: '#ffffff'
  tertiary-container: '#5f411b'
  on-tertiary-container: '#d8ae7e'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#cae6ff'
  primary-fixed-dim: '#abcae6'
  on-primary-fixed: '#001e30'
  on-primary-fixed-variant: '#2b4a61'
  secondary-fixed: '#bdf1a5'
  secondary-fixed-dim: '#a2d48c'
  on-secondary-fixed: '#042100'
  on-secondary-fixed-variant: '#255017'
  tertiary-fixed: '#ffddb9'
  tertiary-fixed-dim: '#ebbf8e'
  on-tertiary-fixed: '#2b1700'
  on-tertiary-fixed-variant: '#5f411b'
  background: '#faf9fb'
  on-background: '#1b1c1e'
  surface-variant: '#e3e2e4'
typography:
  page-title:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  section-heading:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-base:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
  table-data:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  caption:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  eyebrow:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.08em
  identifier:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 16px
  report-body:
    fontFamily: Source Serif 4
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
  max-width: 1440px
---

## Brand & Style

The design system is engineered for high-stakes urban analysis, prioritizing scientific rigor, clarity, and administrative trust. The aesthetic is rooted in **Modern Minimalism** with a "quiet chrome" philosophy—UI elements recede into the background to ensure that complex spatial data and heat mapping remain the focal point.

The atmosphere is intellectual and objective. By utilizing flat surfaces and removing all decorative depth (shadows/gradients), the interface achieves a "government-grade" utility that feels reliable and precise. The emotional response is one of calm focus, allowing urban planners and scientists to process high-density information without visual fatigue.

## Colors

The palette is anchored by a neutral, off-white foundation that mimics architectural vellum, providing a sophisticated backdrop for data visualization. 

- **Functional Accents:** Slate Blue (#2B4A61) is reserved for primary interactive states and navigation, ensuring high contrast against the muted background.
- **Data Semantic Scales:** Heat mapping utilizes the "Magma" perceptual scale to ensure legibility for color-blind users and high-resolution differentiation of temperature.
- **Intervention Logic:** Specific categories (Water, Green, Shade, Material) are assigned distinct, desaturated hues that allow for categorical mapping without overwhelming the visual hierarchy.
- **Risk Assessment:** A traditional stop-light derivative is used for risk, shifted toward more organic, earthy tones to maintain the professional aesthetic.

## Typography

Typography is the primary tool for information density in this design system. 

- **System UI:** Inter is used for all functional interface elements. All numerical data must use `tabular-nums` (tnum) OpenType features to ensure alignment in data tables and dashboards.
- **Technical Identifiers:** JetBrains Mono is utilized for geospatial coordinates, sensor IDs, and raw data strings to distinguish machine-readable data from human-readable labels.
- **Report Mode:** Source Serif 4 is introduced for long-form analysis exports and executive summaries to provide a classic, authoritative, and highly readable literary quality.
- **Scaling:** On mobile devices, the Page Title should scale down to 24px/1.2 while maintaining its weight to preserve vertical space.

## Layout & Spacing

This design system employs a **Fixed Grid** model for analytical dashboards and a **Fluid Sidebar** model for map-based interfaces. 

- **Grid:** A 12-column grid is used for standard pages. In the "Map View," a fixed 320px left-hand panel contains controls, while the map fills the remaining viewport.
- **Density:** The spacing rhythm is based on a 4px baseline. To achieve high information density, internal card padding is set to 16px (md), and vertical list items use 8px (sm) padding.
- **Responsive Behavior:** At the 768px breakpoint (Tablet), the sidebar collapses into a bottom drawer or a hidden toggle menu to prioritize the spatial data visualization.

## Elevation & Depth

This system intentionally avoids depth shadows to maintain a flat, technical aesthetic. Hierarchy is instead established through **Tonal Layering** and **Hairline Outlines**:

- **Layer 0 (Background):** #F7F7F5 (The canvas).
- **Layer 1 (Card/Container):** #FFFFFF with a 1px solid border of #E2E1DC.
- **Layer 2 (Overlays/Modals):** #FFFFFF with a 1px solid border of #17181A (Primary text color) to provide focus, rather than a shadow.
- **Interactive States:** Hovering over a list item or card should trigger a subtle background color shift to #F0F0EE rather than an elevation lift.

## Shapes

The shape language is "Technical-Sharp." A consistent 4px (Soft/1) radius is applied to all cards, buttons, and input fields. This provides just enough softness to feel modern while maintaining the rigid, professional structure of a scientific instrument. 

- **Small elements:** Tags and small buttons use the 4px base.
- **Large elements:** Modals and main content containers also retain the 4px corner; do not use larger radii for larger components to ensure a unified geometric signature.

## Components

- **Buttons:** Primary buttons are solid #2B4A61 with white text. Secondary buttons are transparent with a 1px #E2E1DC border. All buttons have a height of 36px for high-density layouts.
- **Inputs:** Text fields use #FFFFFF background with #E2E1DC borders. Focus state is a 1px solid #2B4A61 border (no outer glow).
- **Data Tables:** Headers use the Eyebrow type style with a bottom border. Row hover state is #F7F7F5. Use JetBrains Mono for all numeric columns.
- **Status Chips:** Use the Risk Level colors with a 10% opacity background of the same hue and a solid 1px border of the same hue for maximum legibility without visual noise.
- **Map Controls:** Small, square 32x32px buttons with 4px radius, stacked vertically, using hairline borders.
- **Legend Items:** 12px x 12px square swatches (4px radius) for categorical data, or continuous horizontal gradients for heat scales.