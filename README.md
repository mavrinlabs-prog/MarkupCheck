# MarkupCheck
**Track:** Finance
**Run it:** see [REPRODUCE.md](REPRODUCE.md)

## The problem
A dealer can add a markup to the lender's approved rate, which the buyer never sees. In 2013 one lender paid $98 million to settle federal charges that its dealers' markups were higher for Black, Hispanic and Asian/Pacific Islander borrowers.

## What we built
A buyer enters an offer: credit score, car, loan, APR and (optionally) lender. MarkupCheck shows where the offer falls among similar loans, what the difference costs, why, and a flag: typical, high, or well above similar loans. It stress-tests its verdict, shows the rule of thumb beside it, and adds credit-union rates, a dealer card, a contract-box check, refinancing, an API, a classroom mode and Spanish. No chatbot: every number comes from public data and stated assumptions.

## What we added
Our question: can a buyer detect a dealer markup from public data alone? We use the loan-level records auto-loan bond deals must file with the SEC (Regulation AB II), which no consumer tool we found uses.

## How it works
From 29 deals' first pool filings by 10 lenders (carmakers, banks, CarMax, Ally, Santander) we kept 554,021 of 1,978,371 loans: originated within 12 months of filing, no promotional rate, a consumer credit score. The target is APR minus that month's 5-year Treasury yield. Gradient-boosted quantile regression uses credit score, new/used, car age, amount, loan-to-value and term; payment-to-income is excluded (it depends on the APR). Conformal calibration sets an 80% range. A second model adds the lender. We trained on Jan 2023–Nov 2024, calibrated on Dec 2024–Jul 2025, and tested on 112,657 later loans (Aug 2025–Jan 2026).

## Results
- **Price.** Typical-price error was 2.53 points, against 3.50 for the credit-tier rule of thumb; the lender model reached 2.35. Both won in all 6 test months. The lender model beat the rule at all 9 testable lenders, including later Toyota and Capital One deals (Nissan's are all promotional); without the lender, Hyundai lost, so the page asks for it. The range covered 81.7% of loans, 76.3% for prime used-car buyers.
- **On newer loans.** On 113,200 CarMax loans from Feb–Aug 2026, the unchanged model beat the rule (1.72 vs 2.45), but the range covered only 68.8%: newer loans were cheaper. Monthly recalibration reached 77.2%, under our pre-set 78% bar, so the app only warns.
- **Markup detection: mostly no.** We added 2 points to a random 10% of test loans (our assumed size and share). At the "well above" flag's 5.5% false-alarm rate, it newly caught 10.8%, the rule of thumb 4.9%; at a 2016 federal order's caps for Toyota's lender (1.25 or 1.00 points), 4.8%. The "high" flag caught 20.1% but flagged 10.1% of ordinary loans. Real loans may already include markups.
- **A high price can also mean risk.** For the original three lenders, loans priced above 90% of similar loans were later 30+ days late or charged off more often: Santander 42.1% vs 29.7%, Ally 6.3% vs 3.1%, CarMax 8.6% vs 7.2%. The test can't tell why.
- **Fairness on groups the model never sees.** Within the same lender, Alabama buyers paid 1.46 more and Connecticut 1.01 less (27 of 43 states survive a multiple-testing correction); the data can't say whether that's law, risk or dealer practice. It has no race, sex or age.
- **Where it fails.** Error rises from 1.73 to 3.78 points across the test months as Santander loans take over. The percentile is accurate at the top (88.0% of loans at or below the 90th) but not the bottom (14.7% below the 10th).

This project is a prototype and is not financial advice.

## What we'd do next
Recalibrate every lender monthly, test real buyers' offers (with permission) and add non-bond lenders.

## Sources
[SOURCES.md](SOURCES.md) lists every source and AI tool. Full results: [RESULTS.md](RESULTS.md). Code: [notebooks/MarkupCheck.ipynb](notebooks/MarkupCheck.ipynb), [src/](src/), [app/](app/). Rebuild: [REPRODUCE.md](REPRODUCE.md).
