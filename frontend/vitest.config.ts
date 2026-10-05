import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    maxWorkers: 2,
    testTimeout: 15_000,
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**'],
    css: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      exclude: ["src/main.tsx", "src/test/**"],
    },
  },
});
