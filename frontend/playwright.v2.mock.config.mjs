import { defineConfig } from '@playwright/test'
import mock from './playwright.mock.config.mjs'

const baseURL = 'http://127.0.0.1:5175'

export default defineConfig({
  ...mock,
  testMatch: 'v2.mock.e2e.ts',
  use: { ...mock.use, baseURL, timezoneId: 'Asia/Shanghai' },
  webServer: {
    ...mock.webServer,
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5175 --strictPort',
    url: baseURL,
    env: { VITE_API_BASE_URL: baseURL + '/api/v1', VITE_V2_API_BASE_URL: baseURL + '/api/v2' },
  },
})
