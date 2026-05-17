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

## Run

scripts/oracle_vm_health_check.sh

## Safety

This package does not enable live trading.