import { configDefaults, defineConfig, type Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";

// The packaged renderer is loaded over file://, where webRequest never fires and
// response headers cannot be injected, so the policy has to travel in the HTML.
// It is added at build time only: the dev server needs eval and a websocket for
// HMR, and baking those allowances into index.html would weaken the shipped app.
//
// Sources in use: bundled JS/CSS and fonts (self/file), inline style attributes
// from React (style 'unsafe-inline'), and audio and image previews served over
// the custom studio-media:// protocol.
const CONTENT_SECURITY_POLICY = [
  "default-src 'none'",
  "script-src 'self' file:",
  "style-src 'self' file: 'unsafe-inline'",
  "img-src 'self' file: data: blob: studio-media:",
  "media-src 'self' file: data: blob: studio-media:",
  "font-src 'self' file: data:",
  "connect-src 'self' file: data: blob: studio-media:",
  "worker-src 'self' blob:",
  "base-uri 'none'",
  "form-action 'none'",
  "object-src 'none'"
  // frame-ancestors is deliberately absent: it is ignored when delivered in a
  // meta element and only warns. Nothing embeds this window in a frame.
].join("; ");

function contentSecurityPolicy(): Plugin {
  return {
    name: "inject-csp",
    apply: "build",
    transformIndexHtml(html) {
      return {
        html,
        tags: [
          {
            tag: "meta",
            attrs: {
              "http-equiv": "Content-Security-Policy",
              content: CONTENT_SECURITY_POLICY
            },
            injectTo: "head-prepend"
          }
        ]
      };
    }
  };
}

export default defineConfig({
  plugins: [react(), contentSecurityPolicy()],
  root: ".",
  base: "./",
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true
  },
  build: {
    target: "chrome120",
    outDir: "dist",
    emptyOutDir: true
  },
  test: {
    environment: "jsdom",
    globals: true,
    exclude: [...configDefaults.exclude, "e2e/**"]
  }
});
