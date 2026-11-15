---
title: MarkupCheck
sdk: gradio
sdk_version: 6.32.0
python_version: "3.12"
app_file: app.py
pinned: false
short_description: Check a car-loan APR against similar real loans
---

# MarkupCheck: is your car-loan rate fair?

Enter the loan offer from the dealer: credit score, new or used, model year, price, amount financed, term and the APR you were offered. MarkupCheck compares that APR with real auto loans that lenders disclosed in public SEC filings (Regulation AB II asset-level data) and shows:

- where your APR falls among similar loans (its percentile),
- the range that 8 in 10 similar loans got, with your offer marked on it,
- the typical APR, both monthly payments and the extra cost over the loan,
- a verdict: typical, high, or well above similar loans,
- three plain-language reasons behind the typical price,
- checks on its own verdict: the offer at every lender, a credit score 30 points either way, interest rates unchanged since the data, and for new cars a lower car value or a used car,
- how many similar loans back the result, how often loans priced like it later ran into trouble, how the model did on newer loans it never saw, and credit-union and bank rates (NCUA averages, each credit union's posted rate from the June 2026 Call Report, and the Federal Reserve's G.19 bank rates),
- the credit-tier rule of thumb a rate table would give, beside the model's range,
- what to do next, and what the data can't tell you,
- the APR worked out from a quoted monthly payment (and a warning when the payment is higher than the APR explains), what financed add-ons really cost, and what one rate point is worth,
- sliders that show how a different score, term or down payment changes the typical rate, instantly,
- a card to take to the dealer (verdict, cost, how sure, data dates and the link), with print and a share link that keeps the numbers out of the server's logs, plus calm replies if the dealer pushes back and a message asking lenders for written offers,
- the whole deal (price, anything financed beyond it, interest and the total), and your state's same-lender price gap and credit-union rates,

Below the form, a contract-box check confirms that a contract's Truth-in-Lending numbers agree with each other. Other tabs compare up to three offers, check a refinance (with an offered rate and calendar reminders), run a CSV batch of up to 500 loans, map which states pay more at the same lender (with a citable CSV), chart typical APRs month by month, give teachers a lesson with four made-up buyers, and document a JSON API (`/check`). Nothing you type is kept on the server or in your browser.

Press **Jordan: a fair rate** to fill in a sample offer (credit score 660, used 2019 car, $17,500 price, $18,500 financed, 72 months, 15.9% APR).

This project is a prototype and is not financial advice.

## Files

| File | Purpose |
|---|---|
| `app.py` | The page: form, result, tabs, language switch, styles and page script. |
| `markupcheck_model.py` | The model interface, `predict(offer)`; its keys are listed in `CONTRACT.md` in the GitHub repository. |
| `scoring.py`, `inputs.py`, `fmt.py`, `finance.py` | Shared scoring math, input checks, number formats, and loan arithmetic. |
| `sections.py`, `tabs.py`, `explore.py`, `charts.py`, `teacher.py` | Result sections, the Compare/Refinance/Batch tabs and the contract-box check, the Explore tab, the SVG charts, and the For teachers tab. |
| `partners.json` | The partner demo (`?partner=example`): a made-up credit union that can add a line, never change a number. |
| `i18n.py` | The Spanish version. |
| `web_security.py` | Security headers and the rate limit. |
| `model/` | Trained model files, `meta.json`, `extras.json` (counts, rates and repayment figures for the checks), `rule_of_thumb.json` (the credit-tier rule), `rates_extra.json` (Call Report and G.19 rates) and `forward_summary.json` (the newer-loans test). |
| `fonts/`, `favicon.svg` | Self-hosted Inter, JetBrains Mono and Lora (licence in `fonts/OFL.txt`), and the icon. |
| `batch_template.csv` | The template for the Batch check tab. |
| `test_app.py`, `test_tabs.py`, `test_charts.py`, `test_i18n.py` | Tests. |
| `requirements.txt` | Python packages besides Gradio. |

## Run it locally

From the project folder:

```bash
.venv/bin/python app/app.py
```

Then open the local URL it prints (http://127.0.0.1:7860 by default). To run the checks:

```bash
.venv/bin/python app/test_app.py
```

## Deploy to Hugging Face Spaces

`model/` holds 38 binary `.joblib` files and `fonts/` three `.woff2` files. Hugging Face now requires a paid plan (PRO) to create a Gradio Space, or a free account in good standing (verified email, over 30 days old) can host it on ZeroGPU hardware. Create the Space on huggingface.co (Gradio SDK), then upload this folder with `hf upload <user>/<space> . . --repo-type space --exclude "__pycache__/*"` (huggingface-hub's `hf` command) or the website's file uploader, which store binaries correctly. A plain `git push` of binary files without Git LFS is likely to be rejected.
