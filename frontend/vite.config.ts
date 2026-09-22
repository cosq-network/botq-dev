import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 450,
    rollupOptions: { output: { manualChunks: { mui: ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'], query: ['@tanstack/react-query'], forms: ['react-hook-form', 'zod'], router: ['react-router-dom'] } } },
  },
})
