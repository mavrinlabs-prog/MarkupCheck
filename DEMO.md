# Finals demo: 5 minutes, live

The finals give each team a 5-minute live demo, then questions from the panel. This script runs about 4:30, leaving 30 seconds for lag. Every number below is what the app shows today or what `RESULTS.md` reports; the model files are fixed, so they won't change. Rehearse it twice, out loud, with a timer.

## Before you go live (the safety kit)
- **Run the app on the laptop as the main demo:** `.venv/bin/python app/app.py`, then open http://127.0.0.1:7860. A Space can sleep or lag on a public stream; keep it only as a backup tab.
- Set the browser zoom to 125% so the stream can read the numbers. Close every other tab and notification. No personal data, keys or accounts on screen.
- Have a screen recording of this script ready in case the laptop fails.
- In the Q&A, offer to type a judge's own numbers. Rehearse a few first: scores of 500 and 850, an 84-month loan, a next-year model, a $90,000 loan.

## The script

**0:00–0:25: The problem** (empty page)
"Dealers can add a hidden markup to the rate the lender approved. MarkupCheck compares your offer with 554,021 real car loans that 10 lenders filed with the SEC."

**0:25–1:10: Sam** (click **Sam: a rate well above similar loans**; the page scrolls to the verdict)
"Sam's 14.5% looks normal, and a rate table agrees: for a prime used-car buyer it says 7.73% to 16.65%. But loans like Sam's mostly got 6.93% to 13.03%, typical 8.87%. Sam's rate is higher than over 95% of them and costs about $4,252 more over 60 months."

**1:10–1:30: Jordan** (click **Jordan: a fair rate**)
"Jordan pays more, 15.9%, but for a 660 score on a 7-year-old car that's typical: similar loans got 13.27% to 24.75%. The lower rate is the one that's out of line." (Click **Sam** again.)

**1:30–2:10: How it works**
"We take each loan's APR minus that month's Treasury rate, split the data by time so we test on later loans the model never saw, train 19 quantile models, and widen the range until it holds 8 in 10 held-out loans. On the test months the typical price was off by 2.53 points, against 3.50 for the rate-table rule, and the range held 81.7% of loans."

**2:10–2:50: How sure, and where it fails** (scroll to **How sure is this?**)
"The app checks its own verdict: with a score 30 points lower, Sam's rate would be typical, so it tells Sam to treat it as less certain. It also says how it did on newer loans: on 113,200 CarMax loans from 2026, the price error stayed lower than the rule's, 1.72 against 2.45, but the range held only 69%. So when a buyer names CarMax, the app now uses a range updated with CarMax's newest loans, and says so."
Then type the notebook's biggest miss: score **746**, **Used**, model year **2024**, price **19303**, amount **25846**, **75** months, APR **29.99**, lender **Santander** (model year 2024 because the app counts a car's age from 2026, and this loan's car was 2 years old). "A real Santander loan from December 2025. The app calls it well above: 6.0 points over the 13.11% to 23.94% that similar Santander loans got, and the verdict holds in all 3 checks. The data can't say why: the buyer's full credit file, a co-signer, or the dealer. That's why we never say 'marked up'."

**2:50–3:35: The hour after the verdict** (click **Sam** again, then **Dealer card** in the jump links)
"Sam takes this card to the finance desk: the verdict, the cost, how sure it is, and the questions to ask. If the dealer pushes back, here are calm replies with Sam's own numbers, and a message to send two or three lenders so every quote is for the same loan."

**3:35–4:05: What the data shows** (**Your state**: pick Alabama)
"At the same lender, Alabama buyers paid 1.46 points more than similar loans, and it holds up after correcting for testing 43 states. The data can't say why: state law, risk or dealer practice."

**4:05–4:30: Our honest answer, and who it helps**
"Can public data alone catch a dealer markup? Mostly no: at a 5.5% false-alarm rate we newly caught 10.8% of 2-point markups, and only 4.8% at the caps a 2016 federal order set for Toyota's dealers. So we don't accuse anyone. We price the offer, show how sure we are, and send the buyer back with questions and a credit-union quote. This project is a prototype and is not financial advice."

**If the laptop app won't start:** use the backup Space tab, or play the recording.

Answers for the hardest questions are in LEARN.md (questions 22–31).
