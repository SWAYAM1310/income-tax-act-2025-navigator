// The example questions the welcome page and an empty chat offer.

export type Example = { q: string; why: string }

// Questions from the v9 dev_mini eval set, verbatim (so their answers replay from cache; some
// contain U+2011 hyphens), one pool per slot. Only questions v9 answered fully are listed.
export const EXAMPLES: Example[][] = [
  [
    { q: 'What is the meaning of "transfer" under the Income-tax Act, 2025?', why: 'A definition' },
    { q: 'How does the Income-tax Act, 2025 define "regular assessment"?', why: 'A definition' },
    { q: 'What deduction is allowed for an assessee whose gross total income includes business profits and gains, under section 63, when additional employee cost is incurred?', why: 'A provision' },
    { q: 'What penalty is imposed for a transaction that directly or indirectly transfers management or control rights in an Indian concern?', why: 'A provision' },
    { q: 'When an asset representing capital expenditure for promoting family planning is sold, how is the excess deduction treated under the Income‑tax Act, 2025?', why: 'Across provisions' },
    { q: 'When a person sells an overseas tour program package, at what point must tax be collected under the Income‑tax Act, 2025?', why: 'Across provisions' },
    { q: 'What constitutes a fixed place of business for a permanent establishment under the Income‑tax Act, 2025?', why: 'Across provisions' },
    { q: 'If an assessee fails to furnish documents within the time specified in a notice under section 171(2), how long can the Assessing Officer extend the deadline for the assessee to comply?', why: 'Across provisions' },
  ],
  [
    { q: 'Under section 393, what are the TDS rate and the threshold limit for payment on transfer of certain immovable property other than agricultural land: Any consideration for transfer of any immovable property (other than agricultural land) when paid by person, where the payee is a resident?', why: 'A rate table' },
    { q: 'What is the rate of tax collection at source under section 394 on remittance under the liberalised remittance scheme of an amount or aggregate of the amounts exceeding ten lakh rupees—?', why: 'A rate table' },
    { q: 'Under section 393, at what rate is tax deducted on Any income referred to in section 211 paid to a non-resident?', why: 'A rate table' },
    { q: 'Under section 393, what are the TDS rate and the threshold limit for interest income: Any income by way of interest other than interest on securities when paid by (a) a banking company; or (b) a co-operative society carrying on the business of banking; or (c) a post office for a deposit made under a scheme notified by the central government, where the payee is a resident?', why: 'A rate table' },
  ],
  [
    { q: 'How was section 99(2) amended by the Finance Act, 2026?', why: 'An amendment' },
    { q: 'How was section 195(1)(i) amended by the Finance Act, 2026?', why: 'An amendment' },
    { q: 'How was section 232(17) amended by the Finance Act, 2026?', why: 'An amendment' },
    { q: 'How was section 263(6)(c)(i) amended by the Finance Act, 2026?', why: 'An amendment' },
    { q: 'How was Schedule XIV, paragraph 4(3) amended by the Finance Act, 2026?', why: 'An amendment' },
  ],
  [
    { q: 'How do I claim a refund that is stuck on the portal?', why: 'Outside the Act, so it is refused' },
    { q: 'What does Rule 114 of the Income-tax Rules say about PAN applications?', why: 'Outside the Act, so it is refused' },
    { q: 'Who is the current Chairman of the CBDT?', why: 'Outside the Act, so it is refused' },
    { q: 'What did CBDT Circular No. 1 of 2026 clarify about TDS on salaries?', why: 'Outside the Act, so it is refused' },
    { q: 'How did the Supreme Court decide the Vodafone indirect transfer case?', why: 'Outside the Act, so it is refused' },
    { q: 'What does the Finance Bill, 2027 propose?', why: 'Outside the Act, so it is refused' },
  ],
]

const SHOWN_KEY = 'statnav.examples'

/** One example per slot, at random, never the one that slot showed on the previous visit. */
export function pickExamples(): Example[] {
  let last: unknown = []
  try { last = JSON.parse(localStorage.getItem(SHOWN_KEY) ?? '[]') } catch { /* first visit */ }
  const prev = Array.isArray(last) ? last : []
  const picks = EXAMPLES.map((pool, i) => {
    const fresh = pool.filter((x) => x.q !== prev[i])
    return fresh[Math.floor(Math.random() * fresh.length)]
  })
  try { localStorage.setItem(SHOWN_KEY, JSON.stringify(picks.map((x) => x.q))) } catch { /* no repeat check */ }
  return picks
}
