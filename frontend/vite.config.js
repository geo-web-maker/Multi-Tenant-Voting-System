import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Separate, long-cacheable vendor chunk: a redeploy of app code doesn't invalidate React for returning voters.
  build: { rollupOptions: { output: {
    // Stable names so scripts/check_template_build.sh can find the Blueprint chunk (nothing matches in default builds).
    chunkFileNames: (c) => (c.facadeModuleId && c.facadeModuleId.includes('/src/templates/blueprint/') ? 'assets/blueprint-[hash].js' : 'assets/[name]-[hash].js'),
    assetFileNames: (a) => ((a.originalFileNames || []).some((n) => n.includes('templates/blueprint')) ? 'assets/blueprint-[hash][extname]' : 'assets/[name]-[hash][extname]'),
    manualChunks(id) { if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'; if (/node_modules\/axios\//.test(id)) return 'axios'; } } } },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.js' },
})
