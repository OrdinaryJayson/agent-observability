import { defineConfig } from '@playwright/test'
import prototype from './playwright.config.mjs'

const baseURL = 'http://127.0.0.1:5174'

export default defineConfig({
  ...prototype,
  testMatch: 'v1.mock.e2e.ts',
  use: { ...prototype.use, baseURL },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174 --strictPort',
    url: baseURL,
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: baseURL + '/api/v1' },
  },
})
