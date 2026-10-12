import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// Captured from the real API (python -m statnav.api) so the UI is tested on real payloads;
// query-cut-off.sse is query-s99-2.sse stopped after eight `token` events. The v9 (explained answer)
// fixtures: query-v9-s99-2.sse, and query-v9-cut-off.sse stopped after 120 `token` events.
const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8')

async function mockApi(page: Page) {
  // the welcome screen draws its example questions at random; 0 picks the first of each pool
  await page.addInitScript(() => { Math.random = () => 0 })
  // count the view transitions the welcome page starts when it hands a question to the chat
  await page.addInitScript(() => {
    const w = window as unknown as { transitions: number }
    w.transitions = 0
    const start = document.startViewTransition?.bind(document)
    if (start) document.startViewTransition = ((cb: () => void) => { w.transitions++; return start(cb) }) as typeof document.startViewTransition
  })
  await page.route('**/api/query', async (route) => {
    const q = JSON.parse(route.request().postData() ?? '{}').question as string
    if (q.includes('one question too many')) {
      await route.fulfill({ status: 429, contentType: 'application/json', headers: { 'retry-after': '1800' },
        body: JSON.stringify({ detail: 'Question limit reached (10 an hour). Try again in about 30 min.' }) })
      return
    }
    const body = q.includes('Explain') ? fixture(q.includes('half') ? 'query-v9-cut-off.sse' : 'query-v9-s99-2.sse')
      : q.includes('refund') ? fixture('query-refusal.sse')
      : q.includes('"transfer"') ? fixture('query-cut-off.sse') : fixture('query-s99-2.sse')
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body })
  })
  await page.route('**/api/provisions/**', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('provision-s99-2.json') }))
  await page.route('**/api/evals?split=dev_mini', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('evals-dev_mini.json') }))
  await page.route('**/api/evals?split=dev', (route) =>
    route.fulfill({ contentType: 'application/json', body: fixture('evals-dev.json') }))
}

/** On a phone the chat list is a drawer; open it. On a desktop it is already showing. */
async function chatList(page: Page) {
  const menu = page.getByRole('button', { name: 'Show the chat list' })
  if (await menu.isVisible()) await menu.click()
  return page.getByRole('navigation', { name: 'Chats' })
}

const AMENDMENT = /section 99\(2\) amended/

test.describe('first visit', () => {
  test.beforeEach(async ({ page }) => { await mockApi(page); await page.goto('/') })

  test('shows the welcome once, then Your chats opens an empty chat', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Ask the Income-tax Act, 2025.' })).toBeVisible()
    await expect(page.getByRole('img', { name: 'The Act as 536 sections, one dot each' })).toBeVisible()
    await expect(page.getByText('Not tax advice.')).toBeVisible()
    await expect(page.getByRole('list', { name: 'Example questions' }).getByRole('listitem')).toHaveCount(3)
    await page.getByRole('button', { name: 'Your chats' }).click()
    await expect(page.getByRole('heading', { name: 'What does the Act say?' })).toBeVisible()
    await page.reload()  // the welcome shows once
    await expect(page.getByRole('heading', { name: 'What does the Act say?' })).toBeVisible()
  })

  const transitions = (page: Page) => page.evaluate(() => (window as unknown as { transitions: number }).transitions)

  test('a question asked on the welcome glides into a new chat', async ({ page }) => {
    const box = page.getByRole('textbox', { name: 'Ask about the Act' })
    await box.click()  // focusing and typing stay on the welcome page
    await box.fill('How was section 99(2) amended by the Finance Act, 2026?')
    await expect(page.getByRole('heading', { name: 'Ask the Income-tax Act, 2025.' })).toBeVisible()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('article', { name: AMENDMENT })).toContainText('(1)(a)(ii) or (b)')
    await expect(page).toHaveURL(/#\/c\//)
    expect(await transitions(page)).toBe(1)
    await expect(page.getByRole('textbox', { name: 'Ask about the Act' })).toHaveValue('')
    await expect(page.getByRole('heading', { name: 'Ask the Income-tax Act, 2025.' })).toHaveCount(0)
  })

  test('an example on the welcome glides into a new chat', async ({ page }) => {
    await page.getByRole('list', { name: 'Example questions' }).getByRole('button', { name: AMENDMENT }).click()
    await expect(page.getByRole('article', { name: AMENDMENT })).toContainText('(1)(a)(ii) or (b)')
    expect(await transitions(page)).toBe(1)
  })
})

test.describe('chat', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('statnav.seenWelcome', '1'))
    await mockApi(page)
    await page.goto('/')
  })

  test('keeps the not-tax-advice line to the welcome page', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'What does the Act say?' })).toBeVisible()
    await expect(page.getByText('Not tax advice.')).toHaveCount(0)
  })

  test('draws different example questions on each visit', async ({ page }) => {
    const examples = page.getByRole('list', { name: 'Example questions' }).getByRole('listitem')
    await expect(examples).toHaveCount(4)
    const first = await examples.allInnerTexts()
    await page.reload()
    await expect(examples).toHaveCount(4)
    const second = await examples.allInnerTexts()
    for (let i = 0; i < 4; i++) expect(second[i]).not.toBe(first[i])  // no slot repeats
  })

  test('answers with a citation that opens the provision, amended words marked', async ({ page }) => {
    await page.getByRole('button', { name: AMENDMENT }).click()
    await expect(page.getByText('Wrote the answer from those passages')).toBeVisible()
    const answer = page.getByRole('article', { name: AMENDMENT })
    await expect(answer).toContainText('(1)(a)(i) or (b)')  // the old and the new wording
    await expect(answer).toContainText('(1)(a)(ii) or (b)')

    // the provision opens only when its citation is clicked
    const sheet = page.getByRole('complementary', { name: 'Provision' })
    await expect(sheet).toBeHidden()
    await answer.getByRole('button', { name: /s\. 99\(2\)/ }).click()
    await expect(sheet.getByRole('heading', { name: 'Section 99(2)' })).toBeVisible()
    await expect(sheet.locator('mark.amended')).toHaveText('sub-section (1)(a)(ii) or (b)')
    await sheet.getByRole('button', { name: 'Before' }).click()
    await expect(sheet.locator('mark.was')).toHaveText('sub-section (1)(a)(i) or (b)')
    await expect(sheet.getByText(/Substituted in section 99\(2\)/)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(sheet).toBeHidden()
    await expect(answer.getByRole('button', { name: /s\. 99\(2\)/ })).toBeVisible()
  })

  test('shows the streamed text when the stream stops before the answer', async ({ page }) => {
    await page.getByRole('button', { name: /meaning of "transfer"/ }).click()
    await expect(page.getByText('Section 99(2) was amended by substituting the reference')).toBeVisible()
    await expect(page.getByText('Stopped before the answer was finished.')).toBeVisible()
  })

  test('lays an explained answer out in sections with § marks and follow-ups', async ({ page }) => {
    const ask = async (q: string) => {
      await page.getByRole('textbox', { name: 'Ask about the Act' }).fill(q)
      await page.keyboard.press('Enter')
    }
    await ask('Explain how section 99(2) was amended')
    const answer = page.getByRole('article', { name: /Explain how section 99\(2\)/ })
    for (const h of ['In short', 'What this means for you', 'What changed', 'Watch out', 'Example']) {
      await expect(answer.getByRole('heading', { name: h, exact: true })).toBeVisible()
    }
    await expect(answer.getByText(/^Suppose you transferred an asset/)).toBeVisible()
    await expect(answer.getByText('[C1]')).toHaveCount(0)  // markers render as § marks
    await expect(answer.getByRole('heading', { name: /Follow/ })).toHaveCount(0)

    // a § mark opens the provision it cites
    const sheet = page.getByRole('complementary', { name: 'Provision' })
    await answer.getByRole('button', { name: 'Open s. 99(2)' }).first().click()
    await expect(sheet.getByRole('heading', { name: 'Section 99(2)' })).toBeVisible()
    await page.keyboard.press('Escape')

    // a follow-up asks itself
    const next = answer.getByRole('list', { name: 'Suggested follow-up questions' }).getByRole('button')
    await expect(next).toHaveCount(3)
    await next.first().click()
    await expect(page.getByRole('article', { name: /Which assets fall under/ })).toBeVisible()
  })

  test('renders a half-streamed explained answer', async ({ page }) => {
    await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('Explain half of section 99(2)')
    await page.keyboard.press('Enter')
    const answer = page.getByRole('article', { name: /Explain half/ })
    await expect(answer.getByRole('heading', { name: 'What changed', exact: true })).toBeVisible()
    await expect(answer.getByRole('heading', { name: 'Watch out', exact: true })).toBeVisible()
    await expect(page.getByText('Stopped before the answer was finished.')).toBeVisible()
  })

  test('a question asked while another chat is answering waits its turn instead of vanishing', async ({ page }) => {
    let release!: () => void
    const held = new Promise<void>((r) => { release = r })
    await page.route('**/api/query', async (route) => {
      const q = JSON.parse(route.request().postData() ?? '{}').question as string
      if (!q.includes('slow')) { await route.fallback(); return }
      await held
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: fixture('query-refusal.sse') })
    })
    await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('A slow question about the Act')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('button', { name: 'Stop' })).toBeVisible()

    // back to the welcome page while that answer is still coming, and ask there
    await page.evaluate(() => { window.location.hash = '#/welcome' })
    await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('How was section 99(2) amended by the Finance Act, 2026?')
    await page.keyboard.press('Enter')
    const waiting = page.getByRole('article', { name: AMENDMENT })
    await expect(waiting).toContainText('Waiting for the answer in another chat to finish')

    release()
    await expect(waiting).toContainText('(1)(a)(ii) or (b)')
    await expect(waiting).not.toContainText('Waiting for the answer')
  })

  test('refuses a question outside the Act without reading it', async ({ page }) => {
    await page.getByRole('button', { name: /refund that is stuck/ }).click()
    await expect(page.getByText('Not answered from the Act')).toBeVisible()
    await expect(page.getByText('Refused before reading the Act')).toBeVisible()
    await expect(page.locator('details.evidence')).toHaveCount(0)
  })

  test('shows the rate-limit message when the server refuses another question', async ({ page }) => {
    await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('This is one question too many')
    await page.keyboard.press('Enter')
    await expect(page.getByText('Question limit reached (10 an hour). Try again in about 30 min.')).toBeVisible()
  })

  test('keeps chats in the sidebar across reloads; rename, delete and Ctrl+K work', async ({ page }) => {
    await page.getByRole('textbox', { name: 'Ask about the Act' }).fill('How was section 99(2) amended by the Finance Act, 2026?')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('article', { name: AMENDMENT })).toContainText('(1)(a)(ii) or (b)')
    await page.keyboard.press('Escape')

    await page.reload()
    await expect(page.getByRole('article', { name: AMENDMENT })).toContainText('(1)(a)(ii) or (b)')
    let list = await chatList(page)
    await expect(list.getByRole('button', { name: 'How was section 99(2) amended by the Finance Act, 2026?', exact: true })).toBeVisible()

    await list.getByRole('button', { name: /Options for How was section 99/ }).click()
    await page.getByRole('menuitem', { name: 'Rename' }).click()
    await page.getByRole('textbox', { name: 'Chat name' }).fill('Section 99 amendment')
    await page.keyboard.press('Enter')
    await expect(list.getByRole('button', { name: 'Section 99 amendment', exact: true })).toBeVisible()

    await page.keyboard.press('Escape')
    await page.keyboard.press('Control+k')
    await expect(page.getByRole('heading', { name: 'What does the Act say?' })).toBeVisible()
    await expect(page).toHaveURL(/#\/new$/)

    list = await chatList(page)
    await list.getByRole('button', { name: 'Options for Section 99 amendment' }).click()
    await page.getByRole('menuitem', { name: 'Delete' }).click()
    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(list.getByText('Your questions are kept here, in this browser only.')).toBeVisible()
  })

  test('shows the eval ladder as charts and a table', async ({ page }) => {
    await (await chatList(page)).getByRole('button', { name: 'How well it answers' }).click()
    await expect(page.getByRole('img', { name: /Facts found in the answer/ })).toBeVisible()
    await expect(page.getByRole('img', { name: /Right provision in the top 5/ })).toBeVisible()
    const v8 = page.getByRole('row', { name: /^v8 / })
    await expect(v8).toContainText('wording before and after')
    await expect(page.getByRole('table')).toContainText('oracle')
  })
})
