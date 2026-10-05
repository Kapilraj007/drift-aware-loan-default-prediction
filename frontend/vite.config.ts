import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxy = {
  "/api": {
    target: process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  publicDir: resolve(__dirname, "../samples"),
  build: {
    chunkSizeWarningLimit: 1_500,
    rollupOptions: {
      output: {
        manualChunks: {
          "ui-vendor": [
            "react",
            "react-dom",
            "react-router-dom",
            "@tanstack/react-query",
            "antd",
            "@ant-design/icons",
          ],
          "charts-vendor": ["recharts"],
        },
      },
    },
  },
  server: {
    proxy: apiProxy,
  },
  preview: {
    proxy: apiProxy,
  },
});
