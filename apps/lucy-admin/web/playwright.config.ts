import {defineConfig} from '@playwright/test';
import path from 'node:path';
export default defineConfig({
  testDir:'./e2e',workers:1,timeout:30000,
  use:{baseURL:'http://localhost:8777',browserName:'chromium',headless:true,launchOptions:process.env.E2E_CHROMIUM_PATH?{executablePath:process.env.E2E_CHROMIUM_PATH}:{}},
  webServer:{command:`${process.env.PASSKEY_TEST_PYTHON||'python'} tests/passkey_browser_server.py`,
    cwd:path.resolve(__dirname,'../../..'),url:'http://localhost:8777',reuseExistingServer:false,
    env:{APP_ENV:'test',APP_SECRET:'browser-test-only-secret-at-least-32-characters',
      COOKIE_SECURE:'false',COOKIE_SAMESITE:'lax',MOBILE_REQUIRE_PROOF:'false',CUSTOMER_WEBAUTHN_ORIGIN:'http://localhost:8777', WEBAUTHN_ORIGIN:'http://localhost:8777',
      GOOGLE_CLIENT_ID:'e2e-google-client',GOOGLE_CLIENT_SECRET:'e2e-google-secret',GOOGLE_REDIRECT_URI:'https://shop.example.test/api/auth/google/callback'}}
});
