# 05: Pricing Data Register

> **Status: INCOMPLETE (CONFIRMED, BD-017). NOT ACTIVE. NOT FOR CUSTOMER USE.**
> This register transcribes the pricing data supplied by Mixt Academy in the brief of 2026-11-09, **unchanged**. Updated 2026-11-09 (v0.2) with Mixt's clarification: statuses changed, **no figure changed**.
> Additional pricing sheets are still being collected. Nothing below is active, and nothing below may be quoted to a customer until it passes the activation gate in [04 §5](04-pricing-engine.md#5-lifecycle-and-the-activation-gate).
> Original schedules are preserved: any correction is added as a **new version** next to the original, never written over it (BD-018, ADR-14).

**Column meanings**
- **Package total**: as supplied (CONFIRMED figure). The only amount that can ever be charged.
- **Minor units**: the same total as stored in the database (pence, fils, halalas, dirhams, sen, cents).
- **Derived rate/unit**: total ÷ quantity. **DERIVED, information only, not an official hourly rate** (see Q-PRC-08).
- **Proposed code**: the internal price-book code. Names describe currency/tier only; a code does **not** assign a market.

---

## 1. Summary of supplied price books

| # | Proposed code | Currency | Tier / plan label (as supplied) | Unit | Entries | Market assignment | What is CONFIRMED | Activation status: still blocked by |
|---|---------------|----------|-------------------------------|------|---------|-------------------|-------------------|-------------------------------------|
| 1 | `UK-GBP-TIER-A` | GBP | Tier A | hour | 7 | United Kingdom | Valid, separate UK tier (BD-012) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-14 |
| 2 | `UK-GBP-TIER-B` | GBP | Tier B | hour | 8 | United Kingdom | Valid, separate UK tier (BD-012) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-16 |
| 3 | `USD-SCHEDULE-A` | USD | Schedule A | hour | 8 | **None: unconfirmed.** Never US (BD-006). | Exists as a USD currency record | **Not active**: Q-MKT-01, Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-16 |
| 4 | `USD-SCHEDULE-B` | USD | Schedule B | hour | 7 | **None: unconfirmed.** Never US (BD-006). | Exists as a USD currency record | **Not active**: Q-MKT-01, Q-PAY-04, Q-PRC-09, Q-PRC-20 |
| 5 | `AE-AED-TIER-A` | AED | Tier A | hour | 8 | United Arab Emirates | Valid, separate UAE tier (BD-013) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-15, Q-PRC-16 |
| 6 | `AE-AED-TIER-B` | AED | Tier B | hour | 8 | United Arab Emirates | Valid, separate UAE tier (BD-013) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-15, Q-PRC-16 |
| 7 | `SA-SAR` | SAR | *(no tier label supplied)* | hour | 8 | Saudi Arabia | Market (BD-004) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-16 |
| 8 | `QA-QAR` | QAR | *(no tier label supplied)* | hour | 8 | Qatar | Market (BD-004) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-16 |
| 9 | `MY-MYR` | MYR | *(no tier label supplied)* | hour | 8 | Malaysia | Totals have been mathematically corrected (BD-015) | **Not active**: **Q-PRC-21**, Q-PAY-04, Q-PRC-09, Q-PRC-20 |
| 10 | `IE-EUR-SCHEDULE-A` | EUR | Schedule A | **class** (1 class = 1 hour) | 7 | Ireland | Separate Ireland schedule (BD-014); 1 class = 1 hour (BD-011) | **Not active**: Q-PRC-03, Q-PAY-04, Q-PRC-09, Q-PRC-20 |
| 11 | `IE-EUR-SCHEDULE-B` | EUR | Schedule B | hour | 6 | Ireland | Separate Ireland schedule (BD-014) | **Not active**: Q-PRC-03, Q-PAY-04, Q-PRC-09, Q-PRC-20, Q-PRC-16 |
| 12 | `HK-HKD-STANDARD` | HKD | Standard | hour | 4 | Hong Kong | Separate Standard plan (BD-016) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20 |
| 13 | `HK-HKD-PREMIUM` | HKD | Premium | hour | 4 | Hong Kong | Separate Premium plan (BD-016) | **Not active**: Q-PAY-04, Q-PRC-09, Q-PRC-20 |

**Tier and schedule selection:** UK, UAE and Ireland each have two books. Until Mixt defines how customers are placed on each (Q-PRC-02, Q-PRC-03), the market's `tier_selection_mode` is `manual`: a person picks the tier/schedule per customer, with a reason; the AI never picks (ADR-12). Ireland additionally stays inactive until the relationship between its schedules is confirmed.

**Plan type:** Hong Kong's Standard and Premium plans are CONFIRMED (BD-016). The other books are stored as `standard` internally, but **no plan name is shown to customers** until confirmed (Q-PRC-06, setting `pricing.plan_label_display`).

**Promotions:** none of these books is a promotional book. Promotional terms are kept separate from standard pricing (BD-021, ADR-15); no promotion exists yet (Q-PRC-05).

**Markets with no pricing supplied:** Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea.
→ The engine returns `NO_APPROVED_PRICING_FOR_MARKET` for these and escalates. No other book (USD included) is used as a stand-in.

---

## 2. Entries as supplied

### 2.1 `UK-GBP-TIER-A`: UK, GBP, Tier A
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | £285 | 28500 | £19.00 |
| 20h | 20 | hour | £360 | 36000 | £18.00 |
| 30h | 30 | hour | £510 | 51000 | £17.00 |
| 40h | 40 | hour | £640 | 64000 | £16.00 |
| 60h | 60 | hour | £840 | 84000 | £14.00 |
| 80h | 80 | hour | £960 | 96000 | £12.00 |
| 100h | 100 | hour | £1,000 | 100000 | £10.00 |

### 2.2 `UK-GBP-TIER-B`: UK, GBP, Tier B
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | £315 | 31500 | £21.00 |
| 20h | 20 | hour | £400 | 40000 | £20.00 |
| 30h | 30 | hour | £570 | 57000 | £19.00 |
| 40h | 40 | hour | £720 | 72000 | £18.00 |
| 60h | 60 | hour | £1,020 | 102000 | £17.00 |
| 100h | 100 | hour | £1,500 | 150000 | £15.00 |
| 150h | 150 | hour | £1,950 | 195000 | £13.00 |
| 200h | 200 | hour | £2,200 | 220000 | £11.00 |

### 2.3 `USD-SCHEDULE-A`: USD-denominated, market UNCONFIRMED (never US)
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 10h | 10 | hour | USD 260 | 26000 | USD 26.00 |
| 20h | 20 | hour | USD 480 | 48000 | USD 24.00 |
| 30h | 30 | hour | USD 660 | 66000 | USD 22.00 |
| 50h | 50 | hour | USD 1,000 | 100000 | USD 20.00 |
| 70h | 70 | hour | USD 1,190 | 119000 | USD 17.00 |
| 100h | 100 | hour | USD 1,500 | 150000 | USD 15.00 |
| 150h | 150 | hour | USD 1,950 | 195000 | USD 13.00 |
| 200h | 200 | hour | USD 2,200 | 220000 | USD 11.00 |

### 2.4 `USD-SCHEDULE-B`: USD-denominated, market UNCONFIRMED (never US)
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 10h | 10 | hour | USD 290 | 29000 | USD 29.00 |
| 20h | 20 | hour | USD 540 | 54000 | USD 27.00 |
| 30h | 30 | hour | USD 750 | 75000 | USD 25.00 |
| 40h | 40 | hour | USD 920 | 92000 | USD 23.00 |
| 60h | 60 | hour | USD 1,200 | 120000 | USD 20.00 |
| 100h | 100 | hour | USD 1,700 | 170000 | USD 17.00 |
| 200h | 200 | hour | USD 2,800 | 280000 | USD 14.00 |

### 2.5 `AE-AED-TIER-A`: UAE, AED, Tier A
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | AED 1,050 | 105000 | AED 70.00 |
| 20h | 20 | hour | AED 1,300 | 130000 | AED 65.00 |
| 30h | 30 | hour | AED 1,800 | 180000 | AED 60.00 |
| 40h | 40 | hour | AED 2,280 | 228000 | AED 57.00 |
| 60h | 60 | hour | AED 3,180 | 318000 | AED 53.00 |
| 100h | 100 | hour | AED 4,900 | 490000 | AED 49.00 |
| 150h | 150 | hour | AED 6,600 | 660000 | AED 44.00 |
| 200h | 200 | hour | AED 7,600 | 760000 | AED 38.00 |

### 2.6 `AE-AED-TIER-B`: UAE, AED, Tier B
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | AED 1,125 | 112500 | AED 75.00 |
| 20h | 20 | hour | AED 1,400 | 140000 | AED 70.00 |
| 30h | 30 | hour | AED 1,950 | 195000 | AED 65.00 |
| 40h | 40 | hour | AED 2,400 | 240000 | AED 60.00 |
| 60h | 60 | hour | AED 3,300 | 330000 | AED 55.00 |
| 100h | 100 | hour | AED 4,900 | 490000 | AED 49.00 |
| 150h | 150 | hour | AED 6,600 | 660000 | AED 44.00 |
| 200h | 200 | hour | AED 7,600 | 760000 | AED 38.00 |

### 2.7 `SA-SAR`: Saudi Arabia, SAR
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | SAR 1,125 | 112500 | SAR 75.00 |
| 20h | 20 | hour | SAR 1,400 | 140000 | SAR 70.00 |
| 30h | 30 | hour | SAR 1,950 | 195000 | SAR 65.00 |
| 40h | 40 | hour | SAR 2,400 | 240000 | SAR 60.00 |
| 60h | 60 | hour | SAR 3,300 | 330000 | SAR 55.00 |
| 100h | 100 | hour | SAR 4,900 | 490000 | SAR 49.00 |
| 150h | 150 | hour | SAR 6,600 | 660000 | SAR 44.00 |
| 200h | 200 | hour | SAR 7,600 | 760000 | SAR 38.00 |

### 2.8 `QA-QAR`: Qatar, QAR
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | QAR 1,050 | 105000 | QAR 70.00 |
| 20h | 20 | hour | QAR 1,300 | 130000 | QAR 65.00 |
| 30h | 30 | hour | QAR 1,800 | 180000 | QAR 60.00 |
| 40h | 40 | hour | QAR 2,280 | 228000 | QAR 57.00 |
| 60h | 60 | hour | QAR 3,180 | 318000 | QAR 53.00 |
| 100h | 100 | hour | QAR 4,900 | 490000 | QAR 49.00 |
| 150h | 150 | hour | QAR 6,600 | 660000 | QAR 44.00 |
| 200h | 200 | hour | QAR 7,600 | 760000 | QAR 38.00 |

### 2.9 `MY-MYR`: Malaysia, MYR

> **Version 1, received 2026-11-09.** Mixt confirmed that the Malaysia package totals "have been mathematically corrected" (BD-015). The figures below are exactly those received on 2026-11-09, and every one is internally consistent (each total = a whole-number rate × hours). **Not yet confirmed:** whether these are the corrected totals, or whether a further corrected set is to be supplied (Q-PRC-21). If a new set arrives, it becomes version 2 with `change_type = correction`; this version 1 stays in the history unchanged.

| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15h | 15 | hour | RM 1,170 | 117000 | RM 78.00 |
| 20h | 20 | hour | RM 1,480 | 148000 | RM 74.00 |
| 30h | 30 | hour | RM 2,100 | 210000 | RM 70.00 |
| 40h | 40 | hour | RM 2,640 | 264000 | RM 66.00 |
| 60h | 60 | hour | RM 3,480 | 348000 | RM 58.00 |
| 100h | 100 | hour | RM 5,400 | 540000 | RM 54.00 |
| 150h | 150 | hour | RM 7,350 | 735000 | RM 49.00 |
| 200h | 200 | hour | RM 9,000 | 900000 | RM 45.00 |

### 2.10 `IE-EUR-SCHEDULE-A`: Ireland, EUR, Schedule A (denominated in **classes**)
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 15 classes | 15 | class | €315 | 31500 | €21.00 |
| 20 classes | 20 | class | €400 | 40000 | €20.00 |
| 30 classes | 30 | class | €540 | 54000 | €18.00 |
| 40 classes | 40 | class | €640 | 64000 | €16.00 |
| 60 classes | 60 | class | €900 | 90000 | €15.00 |
| 80 classes | 80 | class | €1,040 | 104000 | €13.00 |
| 100 classes | 100 | class | €1,200 | 120000 | €12.00 |

**CONFIRMED (BD-011):** one class = one hour for this class-based schedule, unless a package-specific exception is confirmed later. Stored as `unit_type = class`, `session_minutes_per_unit = 60`.

### 2.11 `IE-EUR-SCHEDULE-B`: Ireland, EUR, Schedule B
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 10h | 10 | hour | €250 | 25000 | €25.00 |
| 20h | 20 | hour | €480 | 48000 | €24.00 |
| 30h | 30 | hour | €660 | 66000 | €22.00 |
| 50h | 50 | hour | €1,000 | 100000 | €20.00 |
| 75h | 75 | hour | €1,350 | 135000 | €18.00 |
| 100h | 100 | hour | €1,500 | 150000 | €15.00 |

The two Ireland schedules are **separate** (CONFIRMED, BD-014). How they relate and which customers are eligible for each are **OPEN** (Q-PRC-03).

### 2.12 `HK-HKD-STANDARD`: Hong Kong, HKD, Standard
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 10h | 10 | hour | HKD 3,200 | 320000 | HKD 320.00 |
| 20h | 20 | hour | HKD 6,000 | 600000 | HKD 300.00 |
| 30h | 30 | hour | HKD 8,400 | 840000 | HKD 280.00 |
| 40h | 40 | hour | HKD 10,000 | 1000000 | HKD 250.00 |

### 2.13 `HK-HKD-PREMIUM`: Hong Kong, HKD, Premium
| Package | Quantity | Unit | Package total | Minor units | Derived rate/unit |
|---------|---------:|------|--------------:|------------:|------------------:|
| 60h | 60 | hour | HKD 13,800 | 1380000 | HKD 230.00 |
| 100h | 100 | hour | HKD 18,000 | 1800000 | HKD 180.00 |
| 150h | 150 | hour | HKD 24,000 | 2400000 | HKD 160.00 |
| 200h | 200 | hour | HKD 28,000 | 2800000 | HKD 140.00 |

---

## 3. Points to double-check before activation

These are **observations, not corrections**. The figures above stay exactly as supplied. Each needs a yes/no from Mixt so the data-review checklist (activation gate G-01) can be signed off.

| # | Observation | Books | Question |
|---|-------------|-------|----------|
| DC-01 | UK Tier A: 80h is £960 and 100h is £1,000. The extra 20 hours cost £40 (£2/hour), and the effective rate drops from £12 to £10. | `UK-GBP-TIER-A` | Q-PRC-14 |
| DC-02 | AED Tier A and Tier B have **identical** totals at 100h (4,900), 150h (6,600) and 200h (7,600), but differ at 15h–60h. | `AE-AED-TIER-A/B` | Q-PRC-15 |
| DC-03 | Saudi SAR figures are **numerically identical** to UAE AED Tier B at every package. | `SA-SAR`, `AE-AED-TIER-B` | Q-PRC-16 |
| DC-04 | Qatar QAR figures are **numerically identical** to UAE AED Tier A at every package. | `QA-QAR`, `AE-AED-TIER-A` | Q-PRC-16 |
| DC-05 | USD Schedule A 150h (1,950) and 200h (2,200) equal UK Tier B 150h (£1,950) and 200h (£2,200) numerically. | `USD-SCHEDULE-A`, `UK-GBP-TIER-B` | Q-PRC-16 |
| DC-06 | Ireland Schedule B 20h/30h/50h/100h (480/660/1,000/1,500) equal USD Schedule A at the same durations; 10h differs (€250 vs USD 260). | `IE-EUR-SCHEDULE-B`, `USD-SCHEDULE-A` | Q-PRC-16 |
| DC-07 | Package sizes differ between books (e.g. UK Tier A stops at 100h and has 80h; Tier B has no 80h but goes to 200h; USD A has 50h/70h; Ireland B has 75h; HK Standard stops at 40h, Premium starts at 60h). | All | Q-PRC-17 (are any rows missing?) |
| DC-08 | Every derived rate is a whole number, which suggests the sheets were built from per-hour rates. | All | Q-PRC-08 (store as official advertised rates?) |
| DC-09 | Ireland Schedule A is in "classes"; Schedule B in hours. | `IE-EUR-*` | **Resolved 2026-11-09:** 1 class = 1 hour (BD-011) |
| DC-10 | Malaysia totals were corrected; the register holds the set received 2026-11-09. | `MY-MYR` | Q-PRC-21 |

UK Tier A/B and UAE Tier A/B are now CONFIRMED as **valid, separate tiers** (BD-012, BD-013). That confirms the tiers themselves; the specific figure checks DC-01 to DC-05 are still OPEN until answered individually.

Identical figures may well be intentional (e.g. same price points across Gulf markets). The system just needs that confirmed rather than assumed.

## 4. Benefits and policies as supplied (stored per scope, not yet attached)

| Scope (as supplied) | Items | Storage plan |
|---------------------|-------|--------------|
| General ("supplied so far") | Past papers and curated study resources; dedicated academic support; flexible scheduling; no expiry on purchased hours *in applicable packages*; multiple subjects across grades; sibling/family hour sharing | Benefit **definitions only**; attached to no package until Q-PKG-01 is answered |
| Ireland packages | 18-month validity; pause and resume; recorded sessions; fortnightly progress reports; parent check-in calls; dedicated WhatsApp coordinator; Irish-curriculum-trained tutors; advertised first-paid-session refund or free tutor swap guarantee | Benefit definitions only; **not attached to either Ireland schedule** until Q-PKG-03 says which schedule(s) they belong to |
| HK Standard | No expiry; up to four subjects; family sharing; flexible scheduling | Draft on `HK-HKD-STANDARD` |
| HK Premium | Recorded sessions; unlimited subjects across grades; no expiry; bi-monthly parent-teacher consultations; bi-weekly progress reports; academic support team; teacher chat access | Draft on `HK-HKD-PREMIUM` (wording for "bi-monthly"/"bi-weekly" to confirm: Q-PKG-04) |

## 5. Machine check of this register

The derived-rate column was checked by script: for every row, `minor units = package total × 100` and `derived rate = package total ÷ quantity`. All 13 books and 91 entries match the brief exactly, and every minor-unit and derived-rate value is consistent. The check was re-run after the v0.2 update to prove no figure changed. The same check will become the golden test suite in Phase 2.

Benefits are never shown with a price until they are attached to that exact version and approved (setting `benefits.claims_mode = approved_only`).

## 6. Version history of this register

| Date | Register version | Change | Figures changed? |
|------|------------------|--------|------------------|
| 2026-11-09 | 0.1 | 13 books / 91 entries transcribed from the brief (all `version 1`, draft, inactive) | — (initial) |
| 2026-11-09 | 0.2 | Statuses updated from Mixt's clarification: UK and UAE tiers valid (BD-012, BD-013); Ireland schedules separate (BD-014); 1 class = 1 hour (BD-011); HK Standard/Premium separate (BD-016); Malaysia correction noted (BD-015, Q-PRC-21); catalogue still incomplete (BD-017) | **No** (verified by script) |
| 2026-11-10 | 0.3 | Loaded into the database by migration 0004 as **version 1 of each book, draft, figures locked, supplied-unverified, tax unknown**; the two USD books with no market. A test reads this register independently and checks every stored entry against it | **No** (verified by the golden test on every CI run) |

Future corrections (e.g. a new Malaysia set) are added as **new price-book versions**. The original version stays listed here and in the pricing history screen.
