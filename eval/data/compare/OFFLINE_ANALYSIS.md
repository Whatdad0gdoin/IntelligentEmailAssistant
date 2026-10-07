# Offline accuracy experiments (models: claude-haiku-4-5, claude-opus-5-5, claude-sonnet-5-5, gemini-3.1-flash-lite, gemini-3.1-pro-preview, gemini-3.5-flash-lite, gemini-3.8-flash, gpt-4o-mini, gpt-5-mini)

## 1. Reconstruction check (threshold 0.7 rebuilt from raw answers)

3384/3384 rows reproduce the saved verdict exactly; mismatches: 0.

## 2. Per-model confidence threshold, chosen on dev

| Model | Dev strict at 0.7 | Dev-chosen t | Dev strict at t | Test cov / acc / strict / F1 at 0.7 | Test at dev-chosen t | McNemar vs 0.7 on test |
|---|---|---|---|---|---|---|
| gpt-4o-mini | 70.2% | 0.8 | 70.2% | 90.7% | 85.6% | 77.7% | 0.816 | 88.8% | 86.4% | 76.7% | 0.814 | +0 / -2 rows, p=0.500 |
| claude-haiku-4-5 | 82.6% | 0.5 | 88.2% | 95.3% | 92.2% | 87.9% | 0.899 | 97.7% | 91.4% | 89.3% | 0.902 | +3 / -0 rows, p=0.250 |
| claude-opus-5-5 | 77.6% | 0.4 | 94.4% | 78.6% | 99.4% | 78.1% | 0.874 | 97.7% | 95.7% | 93.5% | 0.947 | +33 / -0 rows, p=0.000 |
| claude-sonnet-5-5 | 75.8% | 0.3 | 94.4% | 80.5% | 98.8% | 79.5% | 0.879 | 97.7% | 95.7% | 93.5% | 0.946 | +30 / -0 rows, p=0.000 |
| gemini-3.1-flash-lite | 85.7% | 0.6 | 87.0% | 99.1% | 92.0% | 91.2% | 0.915 | 99.5% | 92.1% | 91.6% | 0.918 | +1 / -0 rows, p=1.000 |
| gemini-3.1-pro-preview | 93.2% | 0.6 | 93.8% | 93.5% | 96.0% | 89.8% | 0.925 | 96.3% | 94.7% | 91.2% | 0.926 | +3 / -0 rows, p=0.250 |
| gemini-3.5-flash-lite | 87.0% | 0.4 | 90.1% | 94.0% | 93.1% | 87.4% | 0.897 | 98.6% | 90.6% | 89.3% | 0.898 | +4 / -0 rows, p=0.125 |
| gemini-3.8-flash | 90.7% | 0.6 | 91.3% | 99.5% | 93.9% | 93.5% | 0.937 | 100.0% | 94.0% | 94.0% | 0.939 | +1 / -0 rows, p=1.000 |
| gpt-5-mini | 85.7% | 0.5 | 88.8% | 92.1% | 93.4% | 86.0% | 0.895 | 96.7% | 93.3% | 90.2% | 0.918 | +9 / -0 rows, p=0.004 |

Search size: 8 thresholds per model, one choice per model, made on dev only.

### How often the evidence check discards a CORRECT label (test, r1)

| Model | Quote failed | ...of which the label was right | Share of the model's correct answers lost to the quote check |
|---|---|---|---|
| gpt-4o-mini | 15 | 10 | 5.6% |
| claude-haiku-4-5 | 5 | 5 | 2.5% |
| claude-opus-5-5 | 1 | 1 | 0.5% |
| claude-sonnet-5-5 | 2 | 2 | 1.0% |
| gemini-3.1-flash-lite | 0 | 0 | 0.0% |
| gemini-3.1-pro-preview | 2 | 1 | 0.5% |
| gemini-3.5-flash-lite | 3 | 3 | 1.5% |
| gemini-3.8-flash | 0 | 0 | 0.0% |
| gpt-5-mini | 2 | 2 | 1.0% |

## 3. Ensembles, chosen on dev

- Majority of 3, shipped threshold 0.7, all models (84 triples searched on dev): best = gemini-3.1-pro-preview + gemini-3.5-flash-lite + gemini-3.8-flash; dev strict 95.0%; TEST 95.3% | 95.6% | 91.2% | 0.932; vs gpt-4o-mini: +33 / -4 rows, p=0.000; vs gemini-3.8-flash: +4 / -9 rows, p=0.267
- Majority of 3, shipped threshold 0.7, cheap models only (20 triples searched on dev): best = gemini-3.5-flash-lite + gemini-3.8-flash + gpt-5-mini; dev strict 90.7%; TEST 95.8% | 94.7% | 90.7% | 0.925; vs gpt-4o-mini: +33 / -5 rows, p=0.000; vs gemini-3.8-flash: +3 / -9 rows, p=0.146
- Majority of 3, dev-calibrated thresholds, all models (84 triples searched on dev): best = claude-opus-5-5 + claude-sonnet-5-5 + gemini-3.1-pro-preview; dev strict 96.3%; TEST 98.1% | 95.7% | 94.0% | 0.948; vs gpt-4o-mini: +38 / -3 rows, p=0.000; vs gemini-3.8-flash: +5 / -4 rows, p=1.000
- Majority of 3, dev-calibrated thresholds, cheap models only (20 triples searched on dev): best = claude-haiku-4-5 + gemini-3.5-flash-lite + gpt-5-mini; dev strict 92.5%; TEST 98.1% | 93.8% | 92.1% | 0.928; vs gpt-4o-mini: +34 / -3 rows, p=0.000; vs gemini-3.8-flash: +6 / -9 rows, p=0.607

### Agreement gate (accept only when two models agree), chosen on dev

Best pair by dev accuracy-on-covered with coverage >= 80% (36 pairs searched): gemini-3.1-pro-preview + gemini-3.5-flash-lite; TEST 87.4% | 96.8% | 84.7% | 0.897 (coverage | accuracy | strict | F1)

## 4. Cascade: model A, and model B only when A abstains (test, shipped threshold)

| A | B | Escalated | Test strict | Cost per 1,000 emails (USD) | vs A alone |
|---|---|---|---|---|---|
| gpt-4o-mini | gemini-3.1-flash-lite | 9.3% | 84.7% | $0.079 | +15 / -0 rows, p=0.000 |
| claude-haiku-4-5 | gemini-3.1-flash-lite | 4.7% | 90.7% | $0.514 | +6 / -0 rows, p=0.031 |
| gemini-3.1-flash-lite | claude-haiku-4-5 | 0.9% | 91.2% | $0.227 | +0 / -0 rows, p=1.000 |
| gemini-3.5-flash-lite | gemini-3.8-flash | 6.0% | 92.1% | $0.242 | +10 / -0 rows, p=0.002 |
| gemini-3.8-flash | gemini-3.5-flash-lite | 0.5% | 93.5% | $0.418 | +0 / -0 rows, p=1.000 |
| gpt-5-mini | gemini-3.8-flash | 7.9% | 92.6% | $0.288 | +14 / -0 rows, p=0.000 |

Cascade cost treats the fallback as if priced per email at its batched rate; a real fallback call carries the system prompt alone, so this understates it slightly.

## 5. Classical baseline: TF-IDF + logistic regression trained on dev only

C chosen by 5-fold CV on dev: 30.0 (dev CV accuracy 83.9%). TEST (no abstention, so coverage 100%): accuracy 88.4%, macro-F1 0.886; real email only 84.5%.
  Work        precision 97.8%  recall 69.2%
  Personal    precision 70.1%  recall 97.9%
  Promotions  precision 91.7%  recall 91.7%
  Studies     precision 100.0%  recall 100.0%
- Hybrid gpt-4o-mini -> TF-IDF when Review: TEST strict 84.2% (model alone 77.7%); vs model alone: +14 / -0 rows, p=0.000
- Hybrid gemini-3.8-flash -> TF-IDF when Review: TEST strict 94.0% (model alone 93.5%); vs model alone: +1 / -0 rows, p=1.000
- Hybrid claude-sonnet-5-5 -> TF-IDF when Review: TEST strict 94.0% (model alone 79.5%); vs model alone: +31 / -0 rows, p=0.000
