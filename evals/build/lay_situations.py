"""Hand-written lay questions: everyday situations, in the words a taxpayer would use.

Gold provisions were found by reading the parsed Act (section headings, then the provision
text), never by running the retriever, so the gold is not biased toward what the system already
finds. `evals.build.lay.situations()` checks that every id exists, every fact occurs verbatim in
the gold text, and every question passes the leak lint.

Fields: type, q, provisions, rows (table rows), facts, amendment (for type amendment),
person ("first" unless set), note. A refusal has no gold provisions.
"""

from __future__ import annotations


def _amend(kind: str, footnote: str | None, prior: str | None = None) -> dict:
    return {"type": kind, "prior_text": prior, "effective_date": "1-4-2026", "footnote": footnote}


SITUATIONS: list[dict] = [
    # -- salary and pension ------------------------------------------------------------------
    {"type": "table", "q": "I'm a salaried employee. Is there a fixed amount I can knock off my "
     "salary before tax is worked out, and how much is it?",
     "provisions": ["s19:tbl1"], "rows": ["s19:tbl1#2"], "facts": ["Rs. 75000"],
     "note": "standard deduction"},
    {"type": "lookup", "q": "My father gets a monthly pension after retiring. Is that treated "
     "like a salary for tax?", "provisions": ["s16"], "facts": ["pension"], "person": "first",
     "note": "salary includes pension"},
    {"type": "table", "q": "I left my private sector job and got paid for the leave I never "
     "took. How much of that payment is tax-free?",
     "provisions": ["s19:tbl1"], "rows": ["s19:tbl1#14"], "facts": ["ten months"],
     "note": "leave encashment, non-government employee"},
    {"type": "table", "q": "When I retire from a company that falls under the gratuity law, "
     "how much of my gratuity escapes tax?",
     "provisions": ["s19:tbl1"], "rows": ["s19:tbl1#5"], "facts": ["Payment of Gratuity Act"],
     "note": "gratuity under the 1972 Act"},
    # -- house property and home loans ------------------------------------------------------
    {"type": "lookup", "q": "I live in the flat I own. Do I have to show some notional rent "
     "from it as income?", "provisions": ["s21(6)"], "facts": ["nil"],
     "note": "self-occupied annual value nil"},
    {"type": "lookup", "q": "I own a few homes and keep them all for my family's use. How many "
     "of them can be treated as having zero rental value?",
     "provisions": ["s21(7)"], "facts": ["two of such houses"], "note": "two self-occupied houses"},
    {"type": "lookup", "q": "I rent out an apartment. Can I subtract something for repairs and "
     "maintenance from the rent before paying tax on it?",
     "provisions": ["s22(1)(a)"], "facts": ["30%"], "note": "30% standard deduction on rent"},
    {"type": "lookup", "q": "I took a home loan to buy the house I stay in. What is the most "
     "interest I can claim against it each year?",
     "provisions": ["s22(2)"], "facts": ["Rs. 200000", "five years"],
     "note": "self-occupied interest cap"},
    {"type": "lookup", "q": "My rental flat makes a loss after paying the loan interest. If I "
     "can't use the loss this year, for how many years can I carry it forward?",
     "provisions": ["s110"], "facts": ["eight tax years"], "note": "house property loss"},
    {"type": "lookup", "q": "I don't get house rent allowance from my employer but I pay rent "
     "for my flat. Is there any relief, and what is the limit?",
     "provisions": ["s134"], "facts": ["Rs. 5000 per month"], "note": "rent paid deduction"},
    # -- TDS and TCS: what gets cut from payments --------------------------------------------
    {"type": "table", "q": "I pay my landlord 60,000 a month for my flat. Am I supposed to cut "
     "tax from the rent, and at what rate?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#2(i)"], "facts": ["2%", "Rs. 50,000"],
     "note": "TDS on rent by individuals"},
    {"type": "table", "q": "I'm 66 and keep my savings in bank FDs. How much interest can the "
     "bank pay me in a year before it starts deducting tax?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#5(ii)"], "facts": ["Rs. 1,00,000"],
     "note": "TDS on bank interest, senior citizen"},
    {"type": "table", "q": "Bank deducted tax on my fixed deposit interest. I'm 35. Above what "
     "yearly interest does that kick in?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#5(ii)"], "facts": ["Rs. 50,000"],
     "note": "TDS on bank interest, not a senior citizen"},
    {"type": "table", "q": "We are buying a flat for 80 lakh. Do we have to hold back some tax "
     "when we pay the seller?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#3(i)"],
     "facts": ["1%", "Fifty lakh rupees"], "note": "TDS on buying property"},
    {"type": "table", "q": "I won 50,000 in a lottery. Will tax be cut before I receive the "
     "prize money?", "provisions": ["s393:tbl3"], "rows": ["s393:tbl3#1"],
     "facts": ["Rs. 10,000"], "note": "TDS on lottery winnings"},
    {"type": "table", "q": "Companies whose shares I hold pay me dividends. Do they deduct tax "
     "first, and how much?", "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#7"],
     "facts": ["10%"], "note": "TDS on dividends"},
    {"type": "table", "q": "I sold some bitcoin to a buyer. Is the buyer supposed to withhold "
     "tax from what they pay me?", "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#8(vi)"],
     "facts": ["1%"], "note": "TDS on crypto sale"},
    {"type": "table", "q": "I work as a freelance architect and a company pays me fees. How "
     "much tax will they cut, and from what amount?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#6(iii)"], "facts": ["10%", "Rs. 50,000"],
     "note": "TDS on professional fees"},
    {"type": "table", "q": "My life insurance payout is partly taxable. Will the insurer cut "
     "tax before paying me?", "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#8(i)"],
     "facts": ["2%", "Rs. 1,00,000"], "note": "TDS on life insurance payout"},
    {"type": "table", "q": "I'm getting my bungalow rebuilt and the contractor's bill is about "
     "60 lakh. As a private person, must I deduct tax from his payments?",
     "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#6(ii)"],
     "facts": ["2%", "Fifty lakh rupees"], "note": "TDS by individuals on large contracts"},
    {"type": "table", "q": "I sell insurance policies as an agent. Does the insurance company "
     "deduct tax from my commission?", "provisions": ["s393:tbl1"], "rows": ["s393:tbl1#1(i)"],
     "facts": ["Rs. 20,000"], "note": "TDS on insurance commission"},
    {"type": "table", "q": "If I withdraw a lot of cash from my bank account during the year, "
     "will the bank deduct tax on it?", "provisions": ["s393:tbl3"], "rows": ["s393:tbl3#5"],
     "facts": ["2%", "one crore rupees"], "note": "TDS on cash withdrawals"},
    {"type": "table", "q": "I'm a partner in a small firm. Does the firm deduct tax when it pays "
     "me my share of salary and interest?", "provisions": ["s393:tbl3"],
     "rows": ["s393:tbl3#7"], "facts": ["10%", "Rs. 20,000"], "note": "TDS on partner payments"},
    {"type": "table", "q": "I'm buying a new car costing 14 lakh. Will the dealer collect any "
     "extra tax from me on top of the price?", "provisions": ["s394:tbl1"],
     "rows": ["s394:tbl1#6"], "facts": ["1%"], "note": "TCS on motor vehicles"},
    {"type": "table", "q": "I'm sending 15 lakh to my son for his studies abroad. Will the bank "
     "collect tax on that transfer?", "provisions": ["s394:tbl1"], "rows": ["s394:tbl1#7"],
     "facts": ["2%"], "note": "TCS on foreign remittance for education"},
    # -- rates on particular income ---------------------------------------------------------
    {"type": "table", "q": "I made a profit trading crypto coins. At what rate is that profit "
     "taxed?", "provisions": ["s194:tbl1"], "rows": ["s194:tbl1#4"], "facts": ["30%"],
     "note": "tax on virtual digital assets"},
    {"type": "table", "q": "How is money won on online gaming apps taxed?",
     "provisions": ["s194:tbl1"], "rows": ["s194:tbl1#5"], "facts": ["30%"], "person": "third",
     "note": "online game winnings"},
    {"type": "table", "q": "Under the new tax system, what rate applies to the slice of income "
     "between 8 and 12 lakh?", "provisions": ["s202:tbl1"], "rows": ["s202:tbl1#3"],
     "facts": ["10%"], "person": "third", "note": "new regime slab"},
    {"type": "table", "q": "I pay advance tax on my consulting income. By when is the first "
     "instalment due, and what share should I have paid by then?",
     "provisions": ["s408:tbl1"], "rows": ["s408:tbl1#1"], "facts": ["15th June", "15%"],
     "note": "advance tax first instalment"},
    {"type": "table", "q": "How much of my yearly advance tax should be paid by the middle of "
     "December?", "provisions": ["s408:tbl1"], "rows": ["s408:tbl1#3"], "facts": ["75%"],
     "note": "advance tax third instalment"},
    {"type": "table", "q": "I run a small shop with a turnover of about 1.5 crore and don't "
     "keep detailed accounts. Can my profit just be taken as a fixed percentage of sales?",
     "provisions": ["s58:tbl1"], "rows": ["s58:tbl1#1"], "facts": ["two crore rupees", "8%"],
     "note": "presumptive taxation for business"},
    {"type": "table", "q": "I'm a doctor with yearly receipts of around 40 lakh. Is there a "
     "simple scheme where part of my receipts is just assumed to be profit?",
     "provisions": ["s58:tbl1"], "rows": ["s58:tbl1#3"], "facts": ["50% of the gross receipts"],
     "note": "presumptive taxation for professionals"},
    {"type": "lookup", "q": "I sold shares I had held for about 2 years at a profit. What rate "
     "of tax applies to that gain?", "provisions": ["s197(1)"], "facts": ["12.5%"],
     "note": "long-term capital gains rate"},
    {"type": "lookup", "q": "I bought shares and sold them on the stock exchange within six "
     "months for a profit. How much tax do I pay on that?",
     "provisions": ["s196(1)"], "facts": ["20%"], "note": "short-term gains on listed shares"},
    # -- capital gains on property ----------------------------------------------------------
    {"type": "multi_hop", "q": "I'm selling the flat I've owned for five years and plan to buy "
     "a bigger one. Can I avoid tax on the profit, and how soon must I buy the new flat?",
     "provisions": ["s82(1)", "s2(101)(a)"], "facts": ["two years after", "twenty-four months"],
     "note": "reinvestment relief + holding period"},
    {"type": "lookup", "q": "I sold my old house and haven't bought the new one by the time I "
     "file my return. What do I do with the unspent money to keep the tax relief?",
     "provisions": ["s82(2)"], "facts": ["specified bank or institution"],
     "note": "capital gains deposit"},
    {"type": "lookup", "q": "My profit from selling my house is under 2 crore. Can I put it "
     "into two new homes instead of one and still get the exemption?",
     "provisions": ["s82(5)"], "facts": ["two crore rupees", "two residential houses"],
     "note": "two-house option"},
    {"type": "lookup", "q": "I sold some gold jewellery I had for years and want to put the "
     "money into a house. Can I still save tax on the gain?",
     "provisions": ["s86(1)"], "facts": ["one residential house"],
     "note": "reinvestment of other long-term gains"},
    {"type": "multi_hop", "q": "I bought listed shares 14 months ago and want to sell now. Will "
     "the profit count as long-term, and what is the rate then?",
     "provisions": ["s2(101)", "s197(1)"], "facts": ["twelve months", "12.5%"],
     "note": "holding period for listed shares + LTCG rate"},
    # -- gifts, family and residence --------------------------------------------------------
    {"type": "lookup", "q": "A friend gave me 80,000 as a gift. Do I have to pay tax on it?",
     "provisions": ["s92(2)(m)"], "facts": ["Rs. 50000"], "note": "gifts from non-relatives"},
    {"type": "multi_hop", "q": "My uncle transferred 3 lakh to me as a gift. Is it taxable, or "
     "does family count as an exception?",
     "provisions": ["s92(3)", "s92(5)(g)"], "facts": ["from any relative",
                                                      "brother or sister of either of the parents"],
     "note": "gift from relative + who is a relative"},
    {"type": "lookup", "q": "We received cash and jewellery as gifts at our wedding. Is any of "
     "that taxable?", "provisions": ["s92(3)"], "facts": ["marriage"],
     "note": "wedding gifts"},
    {"type": "lookup", "q": "I inherited my grandmother's flat. Do I pay income tax just for "
     "receiving it?", "provisions": ["s92(3)"], "facts": ["inheritance"],
     "note": "inheritance"},
    {"type": "lookup", "q": "My 15-year-old son earns interest on an FD in his name. Is that "
     "added to my income?", "provisions": ["s99(1)(c)", "s99(5)(b)"],
     "facts": ["minor child"], "note": "clubbing of minor child's income"},
    {"type": "lookup", "q": "I gave my wife money and she invested it. Whose income is the "
     "return on that money?", "provisions": ["s99(1)(a)"],
     "facts": ["adequate consideration"], "note": "clubbing of spouse's income"},
    {"type": "lookup", "q": "I came back to India after working abroad and stayed here about "
     "200 days this year. Do I count as a resident for tax?",
     "provisions": ["s6(2)"], "facts": ["one hundred and eighty-two days"],
     "note": "residence test"},
    {"type": "lookup", "q": "I live in Dubai but own a flat in Pune that I rent out. Is that "
     "rent taxable in India?", "provisions": ["s5(2)"], "facts": ["accrues or arises"],
     "note": "non-resident's Indian income"},
    {"type": "multi_hop", "q": "I grow wheat and vegetables on my land in the village. Is the "
     "money from selling the crops taxed?",
     "provisions": ["s2(5)"], "rows": ["sch:II:tbl1#1"], "facts": ["agriculture",
                                                                  "Agricultural income"],
     "note": "farm income definition + exemption"},
    # -- deductions and savings -------------------------------------------------------------
    {"type": "lookup", "q": "I put money into PF, life insurance and my kids' tuition. What is "
     "the combined limit I can deduct for these?",
     "provisions": ["s123"], "facts": ["Rs. 150000"], "note": "80C-style limit"},
    {"type": "lookup", "q": "I pay for my parents' health insurance. They're both over 60. How "
     "much of the premium can I claim?",
     "provisions": ["s126(2)(b)", "s126(8)"], "facts": ["Rs. 50000"],
     "note": "health insurance for senior parents"},
    {"type": "lookup", "q": "Can I claim anything for a full-body health check-up I paid for "
     "in cash?", "provisions": ["s126(3)", "s126(9)"], "facts": ["Rs. 5000"],
     "note": "preventive health check-up"},
    {"type": "lookup", "q": "I took an education loan for my daughter's engineering degree. Can "
     "I claim the interest, and for how long?",
     "provisions": ["s129"], "facts": ["seven tax years"], "note": "education loan interest"},
    {"type": "lookup", "q": "I want to donate to a political party and get a tax benefit. Can "
     "I pay in cash?", "provisions": ["s137"], "facts": ["other than by way of cash"],
     "note": "political donations"},
    {"type": "lookup", "q": "Is the interest from my savings bank account tax-free up to some "
     "amount? I'm 40.", "provisions": ["s153(2)"], "facts": ["Rs. 10000"],
     "note": "savings interest deduction"},
    {"type": "multi_hop", "q": "My mother is 62 and lives on FD interest. How much of that "
     "interest can she deduct, and from what age does this higher limit apply?",
     "provisions": ["s153(2)", "s2(100)"], "facts": ["Rs. 50000", "sixty years"],
     "note": "senior citizen interest deduction + definition"},
    {"type": "lookup", "q": "If my income is under 12 lakh in the new tax system, do I end up "
     "paying any tax at all?", "provisions": ["s156(2)"],
     "facts": ["twelve lakh rupees", "Rs. 60000"], "note": "rebate under the new regime"},
    {"type": "multi_hop", "q": "I've chosen the new tax regime. Can I still deduct the interest "
     "on the home loan for the house I live in?",
     "provisions": ["s202(2)(a)", "s22(1)(b)"], "facts": ["borrowed capital"],
     "note": "new regime disallows self-occupied interest"},
    {"type": "lookup", "q": "I'm salaried with no business income. When and how do I choose to "
     "stay in the old tax system instead of the new one?",
     "provisions": ["s202(4)"], "facts": ["along with the return of income"],
     "note": "opting out of the new regime"},
    # -- paying tax, returns, refunds, penalties -------------------------------------------
    {"type": "lookup", "q": "Do I have to pay tax in instalments during the year if my tax "
     "bill is small?", "provisions": ["s404"], "facts": ["Rs. 10000"],
     "note": "advance tax threshold"},
    {"type": "lookup", "q": "I'm 70 and live on my pension and FD interest. Do I still need to "
     "pay advance tax?", "provisions": ["s403(3)"], "facts": ["sixty years"],
     "note": "senior citizens without business income"},
    {"type": "lookup", "q": "I missed the deadline to file my tax return. What late fee will I "
     "be charged? My income is about 4 lakh.", "provisions": ["s428"],
     "facts": ["Rs. 1000"], "note": "late filing fee"},
    {"type": "lookup", "q": "My refund came months after I filed. Do I get any interest for "
     "the delay?", "provisions": ["s437(1)"], "facts": ["0.5%"],
     "note": "interest on refunds"},
    {"type": "lookup", "q": "A friend wants to lend me 50,000 in cash. Is that allowed?",
     "provisions": ["s185(1)"], "facts": ["Rs. 20000"], "note": "cash loans"},
    # -- amendments, as a lay person asks about them ---------------------------------------
    {"type": "amendment", "q": "I made a mistake in the tax return I filed. How long do I have "
     "to send a corrected one, and did the 2026 budget change that?",
     "provisions": ["s263(5)"], "facts": ["twelve months"],
     "amendment": _amend("substituted", "45@9457", "within nine months from the end of the "
                         "relevant tax year"),
     "note": "revised return window"},
    {"type": "amendment", "q": "If the tax department finds money I can't explain, how much "
     "tax is charged on it? Did the 2026 budget change the rate?",
     "provisions": ["s195(1)(i)"], "facts": ["30%"],
     "amendment": _amend("substituted", "24@6934"), "note": "rate on unexplained income"},
    {"type": "amendment", "q": "Did the 2026 budget change the cap on home-loan interest for a "
     "house I live in, for example interest from before the construction was finished?",
     "provisions": ["s22(2)"], "facts": ["(1)(b) and (c)"],
     "amendment": _amend("substituted", "6@1383"), "note": "self-occupied interest cap"},
    {"type": "amendment", "q": "I booked a foreign holiday package with a travel agent. How "
     "much tax do they collect on it now, after the 2026 budget?",
     "provisions": ["s394:tbl1"], "rows": ["s394:tbl1#8"], "facts": ["2%"],
     "amendment": _amend("substituted", None), "note": "TCS on overseas tour packages"},
    {"type": "amendment", "q": "Did the 2026 budget change the tax collected by the bank when I "
     "pay my son's university fees abroad?",
     "provisions": ["s394:tbl1"], "rows": ["s394:tbl1#7"], "facts": ["2%"],
     "amendment": _amend("substituted", None), "note": "TCS on education remittances"},
    {"type": "amendment", "q": "I'm a builder with finished flats that haven't sold. For how "
     "long is their rental value taken as zero, and did the 2026 budget change this?",
     "provisions": ["s21(5)"], "facts": ["two years"],
     "amendment": _amend("substituted", "5@1357"), "note": "unsold flats held as stock"},
    {"type": "amendment", "q": "I gave money to my wife and she used it in her business. Did "
     "the 2026 budget change how income from that is added to mine?",
     "provisions": ["s99(2)"], "facts": ["(1)(a)(ii) or (b)"],
     "amendment": _amend("substituted", "11@4589"), "note": "clubbing via spouse's business"},
    {"type": "amendment", "q": "Were the late fees for filing an income tax return changed by "
     "the 2026 budget?", "provisions": ["s428"], "facts": ["Rs. 5000"], "person": "third",
     "amendment": _amend("substituted", "3@15245"), "note": "fees for late filing"},
    # -- refusals that stay refusals (computation, advice, portal, other laws) -------------
    {"type": "refusal", "q": "My salary is 14 lakh and I have 2 lakh of deductions. Work out "
     "exactly how much tax I owe this year.", "note": "personal computation"},
    {"type": "refusal", "q": "Should I put my bonus into a tax-saving mutual fund or PPF? "
     "Which is better for me?", "note": "advice"},
    {"type": "refusal", "q": "Old or new regime, which one should I pick? I pay 25k rent and "
     "have a home loan.", "note": "choose-for-me advice"},
    {"type": "refusal", "q": "Which return form do I fill if I have a salary and some share "
     "trading?", "note": "forms"},
    {"type": "refusal", "q": "My refund has been stuck for four months. How do I check its "
     "status on the website?", "note": "portal"},
    {"type": "refusal", "q": "I got an email from the tax department about a mismatch in my "
     "return. What should I write back?", "note": "own notice"},
    {"type": "refusal", "q": "What's the GST on my monthly broadband bill?",
     "person": "first", "note": "other law: GST"},
    {"type": "refusal", "q": "How much stamp duty will I pay to register my flat in Bengaluru?",
     "note": "other law: stamp duty"},
    {"type": "refusal", "q": "Can my landlord legally raise my rent by 20% this year?",
     "note": "other law: tenancy"},
    {"type": "refusal", "q": "What interest rate is PPF paying right now?",
     "person": "third", "note": "current rates"},
    {"type": "refusal", "q": "Is it safe to invest in bitcoin in India?", "person": "third",
     "note": "investment advice"},
    {"type": "refusal", "q": "How much tax will the US take from dividends on my American "
     "shares?", "note": "foreign law / treaty"},
    {"type": "refusal", "q": "What will next year's budget change for salaried people?",
     "person": "third", "note": "future law"},
    {"type": "refusal", "q": "What did the court decide in the recent case about taxing "
     "YouTubers?", "person": "third", "note": "case law"},
    {"type": "refusal", "q": "My CA says forming an LLP will cut my tax. Is that a good idea "
     "for me?", "note": "advice"},
]
