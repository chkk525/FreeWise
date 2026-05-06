/** @type {import('tailwindcss').Config} */
// Minna design system — see ~/.claude/skills/minna-design/references/platform-mapping.md
// Color values flow through CSS variables in app/static/css/input.css so light/
// dark theme switching is automatic. Legacy `primary-*` ramp is kept aliased
// to brand yellow + neutral text for one release as a transitional safety net
// while old templates still reference `text-primary-600` etc. Drop the alias
// once every template has been moved to the semantic tokens (text-1, surface-1,
// accent, etc.).
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/templates/**/*.jinja",
    "./app/static/**/*.js"
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans:    ['Inter', 'Noto Sans JP', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['Inter', 'Noto Sans JP', 'system-ui', '-apple-system', 'sans-serif'],
        body:    ['Inter', 'Noto Sans JP', 'system-ui', '-apple-system', 'sans-serif'],
        mono:    ['Roboto Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
        // Crimson Pro is reserved for `.highlight-text` (reading-mode
        // highlight bodies). The brand stack is intentionally serif-free,
        // but reading a quote in Inter feels institutional — we keep this
        // exception to preserve the reading voice of book quotes.
        // See handsoff.md §3.2 for rationale; do not "fix" it.
        serif:   ['Crimson Pro', 'Georgia', 'serif'],
      },
      colors: {
        // Semantic tokens — values come from CSS vars in input.css so light/
        // dark switching is automatic.
        background: 'var(--background)',
        surface: {
          1: 'var(--surface1)',
          2: 'var(--surface2)',
          3: 'var(--surface3)',
        },
        // `border-DEFAULT` here would override Tailwind's built-in `border`
        // utility, so we expose visible only and keep the default class for
        // the default border-color.
        'border-visible': 'var(--border-visible)',
        text: {
          1: 'var(--text1)',
          2: 'var(--text2)',
          3: 'var(--text3)',
          4: 'var(--text4)',
        },
        accent: {
          DEFAULT: 'var(--accent)',
          bg:      'var(--accent-bg)',
          strong:  'var(--accent-strong)',
        },
        success: { DEFAULT: 'var(--success)', bg: 'var(--success-bg)' },
        warning: { DEFAULT: 'var(--warning)', bg: 'var(--warning-bg)' },
        error:   { DEFAULT: 'var(--error)',   bg: 'var(--error-bg)'   },

        // Brand ramp (raw values — for cases that need a specific step).
        brand: {
          50:  '#FFFEE4',
          100: '#FCFFCC',
          200: '#F4FF99',
          300: '#EEFF66',
          400: '#F0FF33',
          500: '#EEFF00', // signature stamp
          600: '#D6E600',
          700: '#B5C200',
          800: '#8B9500',
          900: '#5C6300',
          950: '#2E3100',
        },

        // Minna namespace — used by .minna-skin overrides; keep for back-
        // compat with existing component classes.
        minna: {
          accent:  '#EEFF00',
          surface: '#F8F8F8',
          band:    '#F4F4F4',
          border:  '#EAEAEA',
          text:    '#000000',
          muted:   '#4D4D4D',
        },

        // Transitional alias — `text-primary-600` etc. in legacy templates
        // resolves to a neutral text token until those usages are rewritten.
        // Drop this alias once every template has been touched.
        primary: {
          50:  '#FFFEE4',
          100: '#FCFFCC',
          300: '#EEFF66',
          400: '#F0FF33',
          500: '#EEFF00',
          600: '#000000',
          700: '#1D1E1F',
        },
      },
      borderColor: {
        DEFAULT: 'var(--border)',
      },
      borderRadius: {
        // Pill aliases full-rounded; component aliases the brand's standard
        // 16px card; container is 24px (one step softer for modals/sheets).
        pill:      '999px',
        chip:      '4px',
        input:     '8px',
        component: '16px',
        container: '24px',
      },
      fontSize: {
        display:    ['56px', { lineHeight: '1.05', letterSpacing: '-0.02em', fontWeight: '700' }],
        heading:    ['32px', { lineHeight: '1.15', letterSpacing: '-0.01em', fontWeight: '700' }],
        subheading: ['20px', { lineHeight: '1.3',  letterSpacing: '0',       fontWeight: '600' }],
        body:       ['14px', { lineHeight: '1.6',  letterSpacing: '0',       fontWeight: '400' }],
        'body-sm':  ['13px', { lineHeight: '1.55', letterSpacing: '0',       fontWeight: '400' }],
        caption:    ['11px', { lineHeight: '1.5',  letterSpacing: '0.02em',  fontWeight: '500' }],
        label:      ['10px', { lineHeight: '1.4',  letterSpacing: '0.08em',  fontWeight: '700' }],
      },
      letterSpacing: {
        display: '-0.02em',
        heading: '-0.01em',
        body:    '0',
        caption: '0.02em',
        label:   '0.08em',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.2, 0, 0, 1)',
      },
      transitionDuration: {
        fast:   '120ms',
        medium: '180ms',
        slow:   '260ms',
      },
      boxShadow: {
        // The brand has zero box-shadow declarations across its stylesheets.
        // We keep `ring` (a flat 1px outline used on modals — see Minna
        // components.md §7) but every legacy blur-shadow utility is mapped to
        // none so existing templates do not visually regress before they get
        // touched.
        none: 'none',
        sm:   'none',
        DEFAULT: 'none',
        md:   'none',
        lg:   'none',
        xl:   'none',
        '2xl': 'none',
        inner: 'none',
        ring:  '0 0 0 1px var(--border-visible)',
      },
    }
  },
  plugins: [],
};
