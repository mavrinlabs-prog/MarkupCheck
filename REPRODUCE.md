# Reproduce MarkupCheck from scratch

The repository already contains the parsed loan tables (`data/parquet/`), the Treasury benchmark and the trained app models, so the notebook runs without downloading anything. These steps rebuild everything from the public sources.

## 1. Environment
```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. SEC downloads (about 2.2 GB of XML)
SEC's archive refuses automated downloads unless the User-Agent names a contact. Use your own:
```bash
export SEC_UA="MarkupCheck research your-email@example.com"
```
Keep requests under 10 per second, as SEC's fair-access policy asks.

- **CarMax.** Download each deal's first pool file into `data/raw/carmax/`, then parse it:
  ```bash
  for u in https://www.sec.gov/Archives/edgar/data/2003263/000125938024000005/cart20241u.xml https://www.sec.gov/Archives/edgar/data/2049715/000125938025000004/cart20251u.xml https://www.sec.gov/Archives/edgar/data/2094950/000125938026000007/cart20261u.xml; do curl -sSL -A "$SEC_UA" -o "data/raw/carmax/$(basename "$u")" "$u"; sleep 1; done
  ```
  ```bash
  .venv/bin/python -I data/raw/carmax/parse_carmax.py parse carmax_2024-1 carmax_2025-1 carmax_2026-1
  ```
  ```bash
  .venv/bin/python -I data/raw/carmax/parse_carmax.py manifest
  ```
- **Ally.** `build_ally.py` downloads and parses each deal named on the command line (it reads `SEC_UA`); `make_manifest.py` then writes the manifest.
  ```bash
  .venv/bin/python -I data/raw/ally/build_ally.py ally_2024-1 ally_2025-1 ally_2026-1
  ```
  ```bash
  .venv/bin/python -I data/raw/ally/make_manifest.py
  ```
- **Santander.** Set the User-Agent string in `data/raw/santander/sec_get.py` to your own contact, download the three files listed in `data/raw/santander/deals.json` with `download.py <url> <file name>`, then parse each deal and build the manifest:
  ```bash
  for u in https://www.sec.gov/Archives/edgar/data/2004812/000095013124000008/sdart241ex102_0105-1902lp.xml https://www.sec.gov/Archives/edgar/data/2049903/000095013125000028/sdart251ex102_0108-1612lp.xml https://www.sec.gov/Archives/edgar/data/2105961/000119312526045549/sdart261ex102_0210-1935lp.xml; do .venv/bin/python -I data/raw/santander/download.py "$u" "$(basename "$u")"; sleep 1; done
  ```
  ```bash
  for s in santander_2024-1 santander_2025-1 santander_2026-1; do .venv/bin/python -I data/raw/santander/parse_santander.py $s; done
  ```
  ```bash
  .venv/bin/python -I data/raw/santander/build_manifest.py
  ```
- **Repayment history (optional; the parsed files are already in `data/parquet/<lender>/perf_*.parquet`).** Each script reads the first 12 monthly EX-102 files of its lender's 2024-1 deal and deletes each XML after parsing it.
  ```bash
  .venv/bin/python -I data/raw/ally/perf_ally.py
  ```
  ```bash
  .venv/bin/python -I data/raw/santander/perf_santander.py
  ```
  For CarMax, download each monthly EX-102 file listed on the trust's EDGAR page (CIK 0002003263) with your `SEC_UA`, parse each into one folder, then combine them:
  ```bash
  .venv/bin/python -I data/raw/carmax/parse_perf.py parse <monthly.xml> data/raw/carmax/perf_parts/<month>.parquet
  ```
  ```bash
  .venv/bin/python -I data/raw/carmax/parse_perf.py combine data/raw/carmax/perf_parts data/parquet/carmax/perf_carmax_2024-1.parquet
  ```

Each lender folder has a `validate.py` that checks its Parquet files against `CONTRACT.md`.


### v2: seven more lenders
Same rule as above (each deal's first pool filing; the deal files are listed in SOURCES.md). Download each lender's files with your `SEC_UA`, then parse:
- **toyota.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/toyota/$(basename "https://www.sec.gov/Archives/edgar/data/2002262/000095013124000229/taot24aex102_0111-1650lp.xml")" "https://www.sec.gov/Archives/edgar/data/2002262/000095013124000229/taot24aex102_0111-1650lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/toyota/$(basename "https://www.sec.gov/Archives/edgar/data/2047571/000095013125000124/taot25aex102_0113-1648lp.xml")" "https://www.sec.gov/Archives/edgar/data/2047571/000095013125000124/taot25aex102_0113-1648lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/toyota/$(basename "https://www.sec.gov/Archives/edgar/data/2099539/000119312526003680/taot26aex102_1215-2121lp.xml")" "https://www.sec.gov/Archives/edgar/data/2099539/000119312526003680/taot26aex102_1215-2121lp.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/toyota/parse_toyota.py parse toyota_2024-A toyota_2025-A toyota_2026-A && .venv/bin/python -I data/raw/toyota/parse_toyota.py manifest
  ```
- **honda.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/honda/$(basename "https://www.sec.gov/Archives/edgar/data/2008953/000095013124000414/harot241ex102_0206-1655lp.xml")" "https://www.sec.gov/Archives/edgar/data/2008953/000095013124000414/harot241ex102_0206-1655lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/honda/$(basename "https://www.sec.gov/Archives/edgar/data/2052479/000095013125000398/harot251ex102_0128-1550lp.xml")" "https://www.sec.gov/Archives/edgar/data/2052479/000095013125000398/harot251ex102_0128-1550lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/honda/$(basename "https://www.sec.gov/Archives/edgar/data/2100818/000119312526034352/harot261ex102_0202-1729lp.xml")" "https://www.sec.gov/Archives/edgar/data/2100818/000119312526034352/harot261ex102_0202-1729lp.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/honda/parse_honda.py parse honda_2024-1 honda_2025-1 honda_2026-1 && .venv/bin/python -I data/raw/honda/parse_honda.py manifest
  ```
- **hyundai.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/hyundai/$(basename "https://www.sec.gov/Archives/edgar/data/2010834/000110465924031026/hca-autoloanex102_021420241u.xml")" "https://www.sec.gov/Archives/edgar/data/2010834/000110465924031026/hca-autoloanex102_021420241u.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/hyundai/$(basename "https://www.sec.gov/Archives/edgar/data/2056104/000110465925016986/hca-autoloanex102_021020251m.xml")" "https://www.sec.gov/Archives/edgar/data/2056104/000110465925016986/hca-autoloanex102_021020251m.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/hyundai/$(basename "https://www.sec.gov/Archives/edgar/data/2104134/000110465926009139/hca-autoloanex102_011620261.xml")" "https://www.sec.gov/Archives/edgar/data/2104134/000110465926009139/hca-autoloanex102_011620261.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/hyundai/parse_hyundai.py parse hyundai_2024-A hyundai_2025-A hyundai_2026-A && .venv/bin/python -I data/raw/hyundai/parse_hyundai.py manifest
  ```
- **nissan.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/nissan/$(basename "https://www.sec.gov/Archives/edgar/data/2017943/000095013124001680/narot24aex102_0506-1852lp.xml")" "https://www.sec.gov/Archives/edgar/data/2017943/000095013124001680/narot24aex102_0506-1852lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/nissan/$(basename "https://www.sec.gov/Archives/edgar/data/2063629/000095013125002079/narot25aex102_0516-1634lp.xml")" "https://www.sec.gov/Archives/edgar/data/2063629/000095013125002079/narot25aex102_0516-1634lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/nissan/$(basename "https://www.sec.gov/Archives/edgar/data/2091790/000119312525287965/narot25bex102_1118-1657lp.xml")" "https://www.sec.gov/Archives/edgar/data/2091790/000119312525287965/narot25bex102_1118-1657lp.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/nissan/parse_nissan.py parse nissan_2024-A nissan_2025-A nissan_2025-B && .venv/bin/python -I data/raw/nissan/parse_nissan.py manifest
  ```
- **ford.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/ford/$(basename "https://www.sec.gov/Archives/edgar/data/2014176/000112998724000006/autoloaninitial1153lp.xml")" "https://www.sec.gov/Archives/edgar/data/2014176/000112998724000006/autoloaninitial1153lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/ford/$(basename "https://www.sec.gov/Archives/edgar/data/2057342/000112998725000004/autoloaninitial1183lp.xml")" "https://www.sec.gov/Archives/edgar/data/2057342/000112998725000004/autoloaninitial1183lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/ford/$(basename "https://www.sec.gov/Archives/edgar/data/2092555/000112998725000019/autoloaninitial1209.xml")" "https://www.sec.gov/Archives/edgar/data/2092555/000112998725000019/autoloaninitial1209.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/ford/parse_ford.py parse ford_2024-A ford_2025-A ford_2025-C && .venv/bin/python -I data/raw/ford/parse_ford.py manifest
  ```
- **gmf.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/gmf/$(basename "https://www.sec.gov/Archives/edgar/data/2003007/000134718524000003/exh1024600112023lp.xml")" "https://www.sec.gov/Archives/edgar/data/2003007/000134718524000003/exh1024600112023lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/gmf/$(basename "https://www.sec.gov/Archives/edgar/data/2047316/000134718525000003/exh1024740112024_lp.xml")" "https://www.sec.gov/Archives/edgar/data/2047316/000134718525000003/exh1024740112024_lp.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/gmf/$(basename "https://www.sec.gov/Archives/edgar/data/2099048/000134718526000003/exh1024860112025_mp.xml")" "https://www.sec.gov/Archives/edgar/data/2099048/000134718526000003/exh1024860112025_mp.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/gmf/parse_gmf.py parse gmf_2024-1 gmf_2025-1 gmf_2026-1 && .venv/bin/python -I data/raw/gmf/parse_gmf.py manifest
  ```
- **capone.**
  ```bash
  curl -sSL -A "$SEC_UA" -o "data/raw/capone/$(basename "https://www.sec.gov/Archives/edgar/data/2039534/000095013124004424/copart241ex102_1112-1953.xml")" "https://www.sec.gov/Archives/edgar/data/2039534/000095013124004424/copart241ex102_1112-1953.xml"; sleep 1; curl -sSL -A "$SEC_UA" -o "data/raw/capone/$(basename "https://www.sec.gov/Archives/edgar/data/2089663/000119312525247047/copart251ex102_1021-1943lp.xml")" "https://www.sec.gov/Archives/edgar/data/2089663/000119312525247047/copart251ex102_1021-1943lp.xml"; sleep 1
  ```
  ```bash
  .venv/bin/python -I data/raw/capone/parse_capone.py parse capone_2024-1 capone_2025-1 && .venv/bin/python -I data/raw/capone/parse_capone.py manifest
  ```

## 3. Treasury benchmark
```bash
.venv/bin/python src/benchmark.py
```

## 4. Notebook, models and results
```bash
.venv/bin/python src/build_notebook.py
```
```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/MarkupCheck.ipynb
```
This writes `app/model/`, `reports/results.json` and `RESULTS.md`.

## 5. The app's checks
NCUA's credit-union and bank car-loan averages (one public page):
```bash
.venv/bin/python src/fetch_ncua.py
```
Then the similar-loan counts, the Treasury rate in the newest data month and the repayment rates by lender:
```bash
.venv/bin/python src/build_extras.py
```
This writes `app/model/extras.json`: the counts, rates and repayment figures for the checks, each state's same-lender gap for the Explore tab's map, and monthly median APRs for its tracker. It checks that it used the same loans (554,021 in v2) and the same states as the notebook.

Order matters once: the notebook's last section prints the Jordan and Sam examples through the app's own code, which also reads `extras.json`, `rule_of_thumb.json` and `forward_summary.json`. After the data changes, run the whole chain (notebook, then this section's scripts, then the forward test, `src/recalibrate.py --apply` and `src/build_forward_summary.py`) twice, so those example printouts use the new files. The model files and every reported number come out the same both times.

The credit-tier rule of thumb shown beside each result (it stops unless the rule's test error matches the notebook's 3.709):
```bash
.venv/bin/python src/build_rule_of_thumb.py
```
Newer reference rates: each credit union's posted rate from NCUA's June 2026 Call Report (an 8 MB zip) and the Federal Reserve's G.19 bank rates. Both write into `app/model/rates_extra.json`; rerunning them gives an identical file.
```bash
.venv/bin/python src/fetch_ncua_callreport.py
.venv/bin/python src/fetch_g19.py
```
The forward test on loans the model never saw (CarMax 2026-2 to 2026-4 and Capital One Prime 2026-1; about 900 MB of SEC XML). Download them with your `SEC_UA` from section 2, then parse, score and write the numbers the app shows:
```bash
mkdir -p data/raw/carmax_forward/xml data/raw/carmax_forward/capone; for u in https://www.sec.gov/Archives/edgar/data/2117307/000125938026000017/cart20262u.xml https://www.sec.gov/Archives/edgar/data/2142044/000125938026000027/cart20263u.xml https://www.sec.gov/Archives/edgar/data/2150706/000125938026000035/cart20264u.xml; do curl -sSL -A "$SEC_UA" -o "data/raw/carmax_forward/xml/$(basename "$u")" "$u"; sleep 1; done; curl -sSL -A "$SEC_UA" -o data/raw/carmax_forward/capone/copart261ex102_0831-1940lp.xml https://www.sec.gov/Archives/edgar/data/2149906/000119312526379485/copart261ex102_0831-1940lp.xml
```
```bash
.venv/bin/python -I src/forward_test.py parse
.venv/bin/python -I src/forward_test.py parse_capone
.venv/bin/python -I src/forward_test.py score
.venv/bin/python src/build_forward_summary.py
```
`score` writes `reports/forward_test.json` and `reports/FORWARD_TEST.md`; rerunning it gives identical files.

Later deals for the lenders with no test-month loans (Toyota 2026-C, Nissan 2026-A and 2026-B, about 660 MB), then the monthly recalibration check (it applies nothing today; LEARN.md step 21) and the app's per-lender notes:
```bash
cd data/raw/later_deals; for u in https://www.sec.gov/Archives/edgar/data/2099541/000119312526297081/taot26cex102_0623-1819lp.xml https://www.sec.gov/Archives/edgar/data/2130293/000119312526216202/narot26aex102_0508-1653lp.xml https://www.sec.gov/Archives/edgar/data/2153094/000119312526392069/narot26bex102_0914-1302lp.xml; do curl -sSL -A "$SEC_UA" -O "$u"; sleep 1; done; cd ../../..
```
```bash
.venv/bin/python -I src/later_deals.py parse
.venv/bin/python -I src/later_deals.py score
.venv/bin/python -I src/recalibrate.py --apply
.venv/bin/python src/build_extras.py
```
`later_deals.py score` writes `reports/later_deals.json`; `build_extras.py` copies its per-lender results into `app/model/extras.json`.

The two calibration fixes we tested (neither is used by the app; LEARN.md step 21 says why):
```bash
.venv/bin/python src/eval_group_calibration.py
.venv/bin/python -I src/eval_recalibration.py
```
They write `reports/group_calibration.json` and `reports/recalibration.json`.

## 6. Tests and the app
```bash
.venv/bin/python tests/test_mc_synthetic.py
```
```bash
.venv/bin/python app/test_app.py
```
```bash
.venv/bin/python app/test_tabs.py
```
```bash
.venv/bin/python app/test_charts.py
```
```bash
.venv/bin/python app/test_i18n.py
```
```bash
.venv/bin/python app/app.py
```
