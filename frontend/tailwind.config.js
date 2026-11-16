export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {
    colors: { base: '#eef2f7', panel: '#ffffff', line: '#cbd5e1', ember: '#d97706', alarm: '#dc2626', ok: '#059669', scan: '#0284c7' },
    fontFamily: { sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'], mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'] }
  } },
  plugins: []
}
