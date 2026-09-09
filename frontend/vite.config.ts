import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Phase 0 scaffold for the React rewrite of the jobs GUI. Builds into
// src/static/dist/ -- Flask's static_folder is already src/static, so
// nothing on the Flask side needs to change to serve the bundle.
//
// Fixed-filename approach (not a Vite manifest): output filenames are pinned
// via rollupOptions.output rather than hashed, so src/templates/app_shell.html
// can reference `dist/assets/main.js` / `dist/assets/main.css` directly with
// url_for('static', ...) instead of reading .vite/manifest.json at request
// time. Simpler for a Phase 0 staging shell; revisit if long-term caching of
// the bundle matters later.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/static/dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/main.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    proxy: {
      // Flask dev server, per the module docstring of src/jobs_gui.py.
      "/api": "http://127.0.0.1:5151",
    },
  },
});
