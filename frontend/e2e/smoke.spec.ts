import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// Captured from the real API (python -m statnav.api) so the UI is tested on real payloads.
const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8')

async function mockApi(page: Page) {
  await page.route('**/api/query', async (route) => {
    const q = JSON.parse(route.request().postData() ?? '{}').question as string
    const body = q.includes('refund') ? fixture('query-refusal.sse') : fixture('query-s99-2.sse')
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body })
  })
  await page.route('**/api/provisions/**', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('provision-s99-2.json') }))
  await page.route('**/api/evals?split=dev_mini', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('evals-dev_mini.json') }))
  await page.route('**/api/evals?split=dev', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('evals-dev.json') }))
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
})

test('says it is not tax advice', async ({ page }) => {
  await expect(page.getByText('Not tax advice.')).toBeVisible()
})

test('answers with a citation that opens the provision, amended words marked', async ({ page }) => {
  await page.getByRole('button', { name: /section 99\(2\) amended/ }).click()
  await expect(page.getByText('Wrote the answer from those passages')).toBeVisible()
  const answer = page.locator('article.answer')
  await expect(answer).toContainText('(1)(a)(i) or (b)')  // the old and the new wording
  await expect(answer).toContainText('(1)(a)(ii) or (b)')
  await expect(answer.getByRole('button', { name: /s\. 99\(2\)/ })).toBeVisible()

  const sheet = page.getByRole('complementary', { name: 'Provision' })
  await expect(sheet.getByRole('heading', { name: 'Section 99(2)' })).toBeVisible()
  await expect(sheet.locator('mark.amended')).toHaveText('sub-section (1)(a)(ii) or (b)')
  await sheet.getByRole('button', { name: 'Before' }).click()
  await expect(sheet.locator('mark.was')).toHaveText('sub-section (1)(a)(i) or (b)')
  await expect(sheet.getByText(/Substituted in section 99\(2\)/)).toBeVisible()
})

test('refuses a question outside the Act without reading it', async ({ page }) => {
  await page.getByRole('button', { name: /refund that is stuck/ }).click()
  await expect(page.getByText('Not answered from the Act')).toBeVisible()
  await expect(page.getByText('Refused before reading the Act')).toBeVisible()
  await expect(page.locator('details.evidence')).toHaveCount(0)
})

test('shows the eval ladder as charts and a table', async ({ page }) => {
  await page.getByRole('button', { name: 'How well it answers' }).click()
  await expect(page.getByRole('img', { name: /Facts found in the answer/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /Right provision in the top 5/ })).toBeVisible()
  const v8 = page.getByRole('row', { name: /^v8 / })
  await expect(v8).toContainText('wording before and after')
  await expect(page.getByRole('table')).toContainText('oracle')
})
