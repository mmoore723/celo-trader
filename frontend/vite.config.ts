import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Source maps so browser DevTools can show real file/line info in stack
    // traces instead of unreadable minified positions (e.g. index-XXXX.js:16:3704).
    // Safe to leave on permanently — adds .map files alongside the JS, doesn't
    // change runtime behavior or bundle execution at all.
    sourcemap: true,
  },
})
