import { defineConfig } from '@playwright/test'
import prototype from './playwright.config.mjs'

export default defineConfig({
  ...prototype,
  testMatch: 'v1.real.e2e.ts',
  timeout: 120000,
  webServer: {
    ...prototype.webServer,
    reuseExistingServer: false,
    env: { VITE_API_BASE_URL: process.env.V1_E2E_API_URL || 'http://127.0.0.1:8101/api/v1' },
  },
})
