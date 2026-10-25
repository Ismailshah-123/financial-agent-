import js from '@eslint/js'
import tseslint from 'typescript-eslint'

// Browser and Node globals the source relies on. Listed explicitly so linting needs no extra package.
const browser = Object.fromEntries([
  'window', 'document', 'navigator', 'console', 'fetch', 'URL', 'URLSearchParams', 'AbortController', 'setTimeout',
  'clearTimeout', 'setInterval', 'clearInterval', 'Event', 'CustomEvent', 'PopStateEvent', 'Response', 'Request', 'Headers',
  'HTMLElement', 'HTMLDialogElement', 'Element', 'Blob', 'crypto', 'DOMException', 'sessionStorage', 'localStorage',
  'globalThis', 'requestAnimationFrame', 'cancelAnimationFrame', 'MouseEvent', 'KeyboardEvent', 'WindowEventMap',
].map((name) => [name, 'readonly']))
const node = { process: 'readonly', Buffer: 'readonly', __dirname: 'readonly' }

export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'playwright-report/**', 'test-results/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...browser, ...node },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    files: ['src/**/*.{js,jsx}'],
    rules: { 'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }] },
  },
]
