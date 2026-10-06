// Screenshots of the main flows for visual review: node scripts/shots.mjs <outdir>
// Needs the API (python -m statnav.api) and `npx vite preview` (port 4173) running.
import { chromium } from '@playwright/test'

const out = process.argv[2] ?? '.'
const URL = process.env.URL ?? 'http://localhost:4173'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

await page.goto(URL)
await page.screenshot({ path: `${out}/1-home.png` })

await page.getByRole('button', { name: /meaning of "transfer"/ }).click()
await page.locator('article.answer').waitFor({ timeout: 60000 })
await page.locator('.sheet header').waitFor()
await page.screenshot({ path: `${out}/2-definition.png` })

await page.getByRole('textbox').fill('How was section 99(2) amended by the Finance Act, 2026?')
await page.getByRole('button', { name: 'Ask', exact: true }).click()
await page.locator('article.answer').waitFor({ timeout: 60000 })
await page.locator('.amend-bar').waitFor()
await page.screenshot({ path: `${out}/3-amendment-now.png` })
await page.getByRole('button', { name: 'Before' }).click()
await page.screenshot({ path: `${out}/4-amendment-before.png` })

await page.getByRole('button', { name: 'How well it answers' }).click()
await page.locator('.chart svg').first().waitFor()
await page.locator('.chart .col').nth(6).hover()
await page.screenshot({ path: `${out}/5-ladder.png`, fullPage: true })

const phone = await browser.newPage({ viewport: { width: 390, height: 844 } })
await phone.goto(URL)
await phone.getByRole('button', { name: /refund that is stuck/ }).click()
await phone.locator('article.answer').waitFor({ timeout: 60000 })
await phone.screenshot({ path: `${out}/6-phone-refusal.png`, fullPage: true })

await browser.close()
console.log('ok')
