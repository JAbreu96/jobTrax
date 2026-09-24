/*
 * Where Vite writes the bundle's files.
 *
 * Lives here, rather than inline in vite.config.ts, so it can be tested: the
 * config belongs to a different tsconfig project and importing it from a test
 * breaks `tsc --noEmit`.
 *
 * app_shell.html links `dist/assets/main.css` and mounts `dist/assets/main.js`
 * by fixed name instead of reading a Vite manifest. Both halves are
 * load-bearing and neither is visible from the other: get the output name
 * wrong and the template links nothing at all, so the page renders unstyled
 * with no error anywhere.
 *
 * That is exactly what `assets/[name][extname]` did. It looks like it pins the
 * name, but `[name]` for the bundle's stylesheet comes from the HTML entry, so
 * it wrote index.css -- unnoticed for as long as no component imported CSS and
 * Vite emitted no stylesheet at all.
 */

/** Rollup's assetFileNames: main[extname] for the stylesheet, own name for the rest. */
export function assetFileName(info: { names?: string[] }): string {
  const isStylesheet = info.names?.some((n) => n.endsWith(".css"));
  // Fonts and images keep their own names -- pinning every asset to "main"
  // would have them overwrite each other.
  return isStylesheet ? "assets/main[extname]" : "assets/[name][extname]";
}
