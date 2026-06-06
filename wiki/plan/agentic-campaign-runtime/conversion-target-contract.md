# Conversion Target Contract

## Goal

Make the campaign's desired conversion destination a first-class runtime object.

## Core Problem

The runtime can plan and execute campaign actions, but it does not yet have one durable contract for where successful leads should end up.

## Supported Destination Families

The first contract should support:

- Telegram user DM
- Telegram bot
- Telegram group
- Telegram channel
- external website or landing page

## First Questions To Lock

- what minimum normalized fields the runtime needs
- how raw operator input is preserved alongside normalized interpretation
- how destination type changes qualification and handoff behavior
- how success is recorded for each target family

## Expected Deliverables

- a durable conversion target record or campaign-owned equivalent
- normalized destination typing
- operator-facing summary of the current conversion destination
- downstream compatibility for qualification, handoff, and reporting

## File-Level Direction

Expected touchpoints will likely include:

- `telegram_app/intake.py`
- `telegram_app/models/`
- `telegram_app/campaign_memory/`
- orchestrator prompt context
- later qualification and live-ops surfaces
