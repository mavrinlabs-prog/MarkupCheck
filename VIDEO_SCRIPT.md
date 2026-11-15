# MarkupCheck: 2-minute video script

Screen-record the app (Hugging Face Space) with your voice over it; no editing needed. Every number below appears on the app's page or in `RESULTS.md`. The spoken words come to about 245, which fits two minutes with time for clicks.

**0:00–0:15: The problem** (show the app's empty form)
"When you finance a car at a dealership, the dealer can add a markup to the rate the lender approved, and you never see that rate. In 2013 one lender paid 98 million dollars over markups that were higher for Black, Hispanic, and Asian and Pacific Islander borrowers."

**0:15–1:15: The demo**
1. Click "Sam: a rate well above similar loans" (credit score 760, used 2022 car, $25,000 financed, 60 months, 14.5%). Point at the red verdict.
   "Similar real loans mostly got 6.93% to 13.03%; typical is 8.87%. Sam's 14.5% is well above them and costs about $4,252 more over the loan."
2. Scroll to "How sure is this?"
   "The app checks its own verdict. If Sam's lender used a score 30 points lower, the same rate would count as typical, and the app says so."
3. On the "Try it yourself" sliders, add $2,400 down.
   "These sliders answer instantly, so Sam can see what changes the typical rate."
4. Click "Jordan: a fair rate" (score 660, used 2019 car, 72 months, 15.9%).
   "Jordan's rate is higher than Sam's, but for Jordan's profile it's typical: similar loans ran 13.27% to 24.75%. So the lower rate is the one that's out of line."
5. Switch to Español for two seconds, then back.
   "It also works in Spanish."

**1:15–1:45: How it works and what we found**
"We parsed almost 2 million loans that 10 lenders filed with the SEC and kept 554,021. On later months the model never saw, its typical-price error was 2.53 points, against 3.50 for the rule of thumb. Our own question was whether public data can catch a markup. Mostly not: at a 5.5% false-alarm rate, only 10.8% of 2-point markups get caught."

**1:45–2:00: Limits**
"At the lenders we could follow, high-priced loans were also late more often, so a flag isn't proof of a markup. The data has no race or sex. This project is a prototype and is not financial advice."
