// Screenshots of the main flows for visual review: node scripts/shots.mjs <outdir>
// Needs the API (python -m statnav.api) and `npx vite preview` (port 4173) running.
import { chromium } from '@playwright/test'

const out = process.argv[2] ?? '.'
const URL = process.env.URL ?? 'http://localhost:4173'
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

await page.goto(URL)
await page.getByText(/with effect from 1-4-2026\.$/).waitFor()  // the welcome has played
await page.screenshot({ path: `${out}/1-welcome.png` })
await page.getByRole('button', { name: 'Start asking' }).click()

await page.getByRole('button', { name: /meaning of "transfer"/ }).click()
const sheet = page.getByRole('complementary', { name: 'Provision' })
await sheet.getByRole('heading').first().waitFor({ timeout: 60000 })
await page.screenshot({ path: `${out}/2-definition.png` })

await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('How was section 99(2) amended by the Finance Act, 2026?')
await page.keyboard.press('Enter')
await sheet.getByRole('heading', { name: 'Section 99(2)' }).waitFor({ timeout: 60000 })
await page.screenshot({ path: `${out}/3-amendment-now.png` })
await sheet.getByRole('button', { name: 'Before' }).click()
await page.screenshot({ path: `${out}/4-amendment-before.png` })

await page.keyboard.press('Escape')
await page.getByRole('button', { name: 'How well it answers' }).click()
await page.locator('.chart svg').first().waitFor()
await page.locator('.chart .col').nth(6).hover()
await page.screenshot({ path: `${out}/5-ladder.png` })

const phone = await browser.newPage({ viewport: { width: 390, height: 844 } })
await phone.addInitScript(() => localStorage.setItem('statnav.seenWelcome', '1'))
await phone.goto(URL)
await phone.getByRole('button', { name: /refund that is stuck/ }).click()
await phone.getByText('Not answered from the Act').waitFor({ timeout: 60000 })
await phone.screenshot({ path: `${out}/6-phone-refusal.png` })
await phone.getByRole('button', { name: 'Show the chat list' }).click()
await phone.screenshot({ path: `${out}/7-phone-chats.png` })

await browser.close()
console.log('ok')
