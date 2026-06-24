# Reward Farming Paper Go/No-Go

## Final decision

**VERIFY FORMULA FIRST**

Live reward farming remains **NO-GO**. Passive market-making remains paused.

## Hard gates

|Gate|Status|
|---|---|
|official reward formula verified|FAIL|
|data-path error rate acceptable|PASS|
|reward candidates available|PASS|
|pessimistic scenario positive EV|FAIL|
|adverse fill risk does not dominate reward|PASS|
|gas does not dominate reward|FAIL|
|small-account capital sufficient|FAIL|
|simulator confidence medium/high|FAIL|
|no live-order assumptions untested|FAIL|

## Best pessimistic market

|Field|Value|
|---|---|
|Market|Will France win the 2026 FIFA World Cup?|
|Pro-rata reward/day|$0.3333|
|Adverse loss/day|$0.0150|
|Gas/day|$5.7600|
|Net EV/day|$-5.4485|
|Confidence|low|

## Formula status

Reward formula remains partially unverified; live reward farming remains NO-GO.

## Exact next action

Verify the official reward scoring/payout formula before any further live-deployment discussion. If docs remain inaccessible, keep reward farming in paper-only mode or pivot to cross-venue pricing research.
