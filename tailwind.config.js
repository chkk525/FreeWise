/** @type {import('tailwindcss').Config} */
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
        sans: ['Inter', 'Noto Sans JP', 'system-ui', '-apple-system', 'sans-serif'],
        serif: ['Inter', 'Noto Sans JP', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['Roboto Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        primary: {
          50: '#FFFEE4',
          100: '#FCFFCC',
          300: '#EEFF66',
          400: '#F0FF33',
          500: '#EEFF00',
          600: '#000000',
          700: '#1D1E1F',
        },
        minna: {
          accent: '#EEFF00',
          surface: '#F8F8F8',
          band: '#F4F4F4',
          border: '#EAEAEA',
          text: '#000000',
          muted: '#4D4D4D',
        }
      }
    }
  },
  plugins: [],
};
