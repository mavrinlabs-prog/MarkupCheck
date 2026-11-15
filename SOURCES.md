# Sources and credits

## Data
- SEC EDGAR, Form ABS-EE, exhibit EX-102 (asset-level auto-loan data), each deal's first pool filing:
  - CarMax Auto Owner Trust 2024-1: https://www.sec.gov/Archives/edgar/data/2003263/000125938024000005/cart20241u.xml
  - CarMax Auto Owner Trust 2025-1: https://www.sec.gov/Archives/edgar/data/2049715/000125938025000004/cart20251u.xml
  - CarMax Auto Owner Trust 2026-1: https://www.sec.gov/Archives/edgar/data/2094950/000125938026000007/cart20261u.xml
  - Ally Auto Receivables Trust 2024-1: https://www.sec.gov/Archives/edgar/data/2010413/000147733624000006/ex102jan2024aart20241_1.xml
  - Ally Auto Receivables Trust 2025-1: https://www.sec.gov/Archives/edgar/data/2087070/000147733625000006/ex102aug2025aart20251_1.xml
  - Ally Auto Receivables Trust 2026-1: https://www.sec.gov/Archives/edgar/data/2111835/000147733626000006/ex102jan2026aart20261_1.xml
  - Santander Drive Auto Receivables Trust 2024-1: https://www.sec.gov/Archives/edgar/data/2004812/000095013124000008/sdart241ex102_0105-1902lp.xml
  - Santander Drive Auto Receivables Trust 2025-1: https://www.sec.gov/Archives/edgar/data/2049903/000095013125000028/sdart251ex102_0108-1612lp.xml
  - Santander Drive Auto Receivables Trust 2026-1: https://www.sec.gov/Archives/edgar/data/2105961/000119312526045549/sdart261ex102_0210-1935lp.xml
  - Added in v2 (seven more lenders, same first-pool rule; `data/raw/<lender>/parse_<lender>.py`):
    - Toyota Auto Receivables 2024-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2002262/000095013124000229/taot24aex102_0111-1650lp.xml
    - Toyota Auto Receivables 2025-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2047571/000095013125000124/taot25aex102_0113-1648lp.xml
    - Toyota Auto Receivables 2026-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2099539/000119312526003680/taot26aex102_1215-2121lp.xml
    - Honda Auto Receivables 2024-1 Owner Trust: https://www.sec.gov/Archives/edgar/data/2008953/000095013124000414/harot241ex102_0206-1655lp.xml
    - Honda Auto Receivables 2025-1 Owner Trust: https://www.sec.gov/Archives/edgar/data/2052479/000095013125000398/harot251ex102_0128-1550lp.xml
    - Honda Auto Receivables 2026-1 Owner Trust: https://www.sec.gov/Archives/edgar/data/2100818/000119312526034352/harot261ex102_0202-1729lp.xml
    - Hyundai Auto Receivables Trust 2024-A: https://www.sec.gov/Archives/edgar/data/2010834/000110465924031026/hca-autoloanex102_021420241u.xml
    - Hyundai Auto Receivables Trust 2025-A: https://www.sec.gov/Archives/edgar/data/2056104/000110465925016986/hca-autoloanex102_021020251m.xml
    - Hyundai Auto Receivables Trust 2026-A: https://www.sec.gov/Archives/edgar/data/2104134/000110465926009139/hca-autoloanex102_011620261.xml
    - Nissan Auto Receivables 2024-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2017943/000095013124001680/narot24aex102_0506-1852lp.xml
    - Nissan Auto Receivables 2025-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2063629/000095013125002079/narot25aex102_0516-1634lp.xml
    - Nissan Auto Receivables 2025-B Owner Trust: https://www.sec.gov/Archives/edgar/data/2091790/000119312525287965/narot25bex102_1118-1657lp.xml
    - Ford Credit Auto Owner Trust 2024-A: https://www.sec.gov/Archives/edgar/data/2014176/000112998724000006/autoloaninitial1153lp.xml
    - Ford Credit Auto Owner Trust 2025-A: https://www.sec.gov/Archives/edgar/data/2057342/000112998725000004/autoloaninitial1183lp.xml
    - Ford Credit Auto Owner Trust 2025-C: https://www.sec.gov/Archives/edgar/data/2092555/000112998725000019/autoloaninitial1209.xml
    - GM Financial Consumer Automobile Receivables Trust 2024-1: https://www.sec.gov/Archives/edgar/data/2003007/000134718524000003/exh1024600112023lp.xml
    - GM Financial Consumer Automobile Receivables Trust 2025-1: https://www.sec.gov/Archives/edgar/data/2047316/000134718525000003/exh1024740112024_lp.xml
    - GM Financial Consumer Automobile Receivables Trust 2026-1: https://www.sec.gov/Archives/edgar/data/2099048/000134718526000003/exh1024860112025_mp.xml
    - Capital One Prime Auto Receivables Trust 2024-1: https://www.sec.gov/Archives/edgar/data/2039534/000095013124004424/copart241ex102_1112-1953.xml
    - Capital One Prime Auto Receivables Trust 2025-1: https://www.sec.gov/Archives/edgar/data/2089663/000119312525247047/copart251ex102_1021-1943lp.xml
  - Monthly EX-102 files of the three 2024-1 deals (12 months each) for the repayment test, listed on each trust's EDGAR filing page:
    - CarMax Auto Owner Trust 2024-1: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0002003263&type=ABS-EE
    - Ally Auto Receivables Trust 2024-1: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0002010413&type=ABS-EE
    - Santander Drive Auto Receivables Trust 2024-1: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0002004812&type=ABS-EE
- NCUA, Credit Union and Bank Rates 2025 Q4 (national average car-loan rates for December 26, 2025; data from S&P Global Market Intelligence), used for the app's credit-union and bank comparison: https://ncua.gov/analysis/cuso-economic-data/credit-union-bank-rates/credit-union-and-bank-rates-2025-q4
- Forward test (loans the model never saw; `src/forward_test.py`), first pool EX-102 files:
  - CarMax Auto Owner Trust 2026-2: https://www.sec.gov/Archives/edgar/data/2117307/000125938026000017/cart20262u.xml
  - CarMax Auto Owner Trust 2026-3: https://www.sec.gov/Archives/edgar/data/2142044/000125938026000027/cart20263u.xml
  - CarMax Auto Owner Trust 2026-4: https://www.sec.gov/Archives/edgar/data/2150706/000125938026000035/cart20264u.xml
  - Capital One Prime Auto Receivables Trust 2026-1 (a later deal from a lender in the training data): https://www.sec.gov/Archives/edgar/data/2149906/000119312526379485/copart261ex102_0831-1940lp.xml
- Later deals for lenders with no test-month loans (`src/later_deals.py`), first pool EX-102 files and 424B5 prospectuses:
  - Toyota Auto Receivables 2026-C Owner Trust: https://www.sec.gov/Archives/edgar/data/2099541/000119312526297081/taot26cex102_0623-1819lp.xml (424B5: https://www.sec.gov/Archives/edgar/data/2099541/000092963826002627/taot2026-c_424b5.htm)
  - Nissan Auto Receivables 2026-A Owner Trust: https://www.sec.gov/Archives/edgar/data/2130293/000119312526216202/narot26aex102_0508-1653lp.xml (424B5: https://www.sec.gov/Archives/edgar/data/2130293/000119312526236121/d59935d424b5.htm)
  - Nissan Auto Receivables 2026-B Owner Trust: https://www.sec.gov/Archives/edgar/data/2153094/000119312526392069/narot26bex102_0914-1302lp.xml (424B5: https://www.sec.gov/Archives/edgar/data/2153094/000119312526401058/d153597d424b5.htm)
- NCUA 5300 Call Report quarterly data, June 30 2026 (each credit union's posted new- and used-vehicle loan rate, accounts 523 and 524; `src/fetch_ncua_callreport.py`): https://ncua.gov/files/publications/analysis/call-report-data-2026-06.zip
- Federal Reserve G.19 Consumer Credit, Terms of Credit (release of November 6, 2026; `src/fetch_g19.py`): https://www.federalreserve.gov/releases/g19/20261106/default.htm, with the same series on FRED: https://fred.stlouisfed.org/series/RIFLPBCIANM60NM, https://fred.stlouisfed.org/series/RIFLPBCIANM72NM, https://fred.stlouisfed.org/series/RIELPCFANNM (public domain; citation requested)
- NCUA credit union locator, linked from the result: https://mapping.ncua.gov/
- EDGAR technical specifications: https://www.sec.gov/submit-filings/technical-specifications
- Field definitions, Regulation AB Schedule AL (17 CFR 229.1125): https://www.ecfr.gov/current/title-17/chapter-II/part-229/subpart-229.1100/section-229.1125
- US Treasury daily par yield curve rates (5-year), one CSV per year 2015–2026, e.g. https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2025/all?type=daily_treasury_yield_curve&field_tdr_date_value=2025&page&_format=csv (web view: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value=2025)

## Facts quoted
- DOJ press release on the 2013 Ally settlement: https://www.justice.gov/archives/opa/pr/justice-department-and-consumer-financial-protection-bureau-reach-98-million-settlementto
- CFPB, "What is dealer markup?": https://www.consumerfinance.gov/ask-cfpb/what-is-dealer-markup-en-759/
- CFPB and DOJ, 2016 resolution with Toyota Motor Credit (markup caps of 1.25 and 1 percentage points, used for the markup-size test): https://www.consumerfinance.gov/about-us/newsroom/cfpb-and-doj-reach-resolution-with-toyota-motor-credit-to-address-loan-pricing-policies-with-discriminatory-effects/
- F&I and Showroom, May 17 2018, on the order ending early: https://www.fi-magazine.com/news/freed-from-cfpb-order-toyota-financial-to-raise-markup-caps
- Regulation Z, 12 CFR 1026.17(a)(1) (the disclosures are grouped together) and 1026.22(a)(2) (an APR is accurate within 1/8 of a percentage point), used by the contract-box check: https://www.ecfr.gov/current/title-12/chapter-X/part-1026/subpart-C/section-1026.17 and https://www.ecfr.gov/current/title-12/chapter-X/part-1026/subpart-C/section-1026.22

## Libraries
pandas (https://pandas.pydata.org), NumPy (https://numpy.org), pyarrow (https://arrow.apache.org/docs/python/), lxml (https://lxml.de), requests (https://requests.readthedocs.io), scikit-learn (https://scikit-learn.org), joblib (https://joblib.readthedocs.io), SciPy (https://scipy.org), threadpoolctl (https://github.com/joblib/threadpoolctl), Jupyter / nbconvert (https://jupyter.org), Gradio (https://www.gradio.app), Starlette (https://www.starlette.io), Hugging Face Spaces (https://huggingface.co/spaces), Google Colab (https://colab.research.google.com).

## Design
- The app's look follows the AdmitPath design system (https://admitpath.ai): its slate-blue palette, card and button styles, and type. Its security headers and rate limit follow AdmitPath's server settings. A few colours are darker than AdmitPath's so all text meets WCAG AA contrast.
- Fonts: Inter (https://rsms.me/inter/), Lora (https://github.com/cyrealtype/Lora-Cyrillic) and JetBrains Mono (https://www.jetbrains.com/lp/mono/), all under the SIL Open Font License. The app serves Fontsource's Latin subsets (https://fontsource.org) itself, with the licence in `app/fonts/OFL.txt`; no font is loaded from another site.

## AI tools
- Claude (Anthropic), Claude Code with Opus 5.5 and Sonnet 5.5 (https://claude.com/claude-code): used to research and compare project ideas, check datasets, design the method, write, test and review code, translate the app into Spanish, and draft the write-up and video script. Our team reviewed every part and can explain it (see LEARN.md).
