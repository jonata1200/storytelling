// Testar se a aplicação FastAPI está respondendo
import { test, expect } from '@playwright/test';

test('Validar que a aplicação está no ar', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Storytelling/);
});

// Testar endpoint de health check
test('Validar endpoint de health check', async ({ request }) => {
  const response = await request.get('/api/v1/health/live');
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ status: 'ok' });
});
