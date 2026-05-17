# Package 23: Oracle VM Deployment Finalization

Finalizes Oracle VM deployment support for the Jini engine.

## Purpose

This package helps run Jini on an Oracle Cloud Always Free VM.

## Adds

- Oracle VM environment checker
- Runtime service health check
- Start services script
- Stop services script
- Service status script
- Package validator

## Required safe defaults

PAPER_ORDER_SUBMISSION_ENABLED=false
MANUAL_APPROVAL_REQUIRED=true
ENGINE_KILL_SWITCH=false

## Required .env values on Oracle VM

ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
SEC_USER_AGENT=your_email@example.com
ALPACA_DATA_FEED=sip
PAPER_ORDER_SUBMISSION_ENABLED=false
MANUAL_APPROVAL_REQUIRED=true
ENGINE_KILL_SWITCH=false
RUNTIME_INTERVAL_SECONDS=60

## Install services on Oracle VM

chmod +x scripts/install_oracle_vm_service.sh
./scripts/install_oracle_vm_service.sh

## Start services

scripts/oracle_vm_start_services.sh

## Stop services

scripts/oracle_vm_stop_services.sh

## Check status

scripts/oracle_vm_status.sh

## Full health check

scripts/oracle_vm_health_check.sh

## Safety

This package does not enable live trading.

order_submission=false
live_trading=false
manual_approval_required=true
