# Package 1B: Alpaca Free Market Scanner v1

This package adds the first real market-data layer.

It pulls Alpaca free/IEX 1-minute bars, calculates transparent market features, writes candidate rows, and then runs Package 1A if the normalizer exists.

## What it creates

```text
src/prediction_engine/scanners/alpaca_free_market_scanner.py
scripts/run_alpaca_free_market_scanner.py
scripts/validate_alpaca_free_market_scanner.py
.github/workflows/alpaca-free-market-scanner.yml
```

## Outputs

```text
state/prediction_engine/dynamic_alpaca_candidates.json
docs/data/prediction_engine/alpaca_market_scanner_health.json
docs/data/prediction_engine/free_scanner.json if Package 1A exists
docs/data/prediction_engine/signal_dashboard.json if Package 1A exists
```

## What it calculates

```text
price
open
previous close
volume
VWAP
gap %
day change %
relative volume
VWAP distance %
volume acceleration
candidate quality
data age
```

## Safety

```text
No paper orders
No live orders
No shorts
No options
No execution
IEX/free data only
```

## Required secrets

Add these to GitHub repo secrets:

```text
ALPACA_API_KEY
ALPACA_SECRET_KEY
```

## Manual run

```bash
PYTHONPATH=src:. python scripts/run_alpaca_free_market_scanner.py
```

## Expected result

If Alpaca keys are present and alpaca-py is installed:

```text
state/prediction_engine/dynamic_alpaca_candidates.json
```

will contain real candidate rows.

If keys are missing, the package writes a safe health file and no candidates. Package 1A can still show placeholders.
