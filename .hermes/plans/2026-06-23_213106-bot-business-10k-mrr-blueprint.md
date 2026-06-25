# Bot Business to $10K MRR Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build and monetize a focused bot/SaaS business from zero to $10,000/month in recurring revenue without overbuilding, by validating a high-value niche, shipping a reliable AI workflow bot, and scaling acquisition through repeatable founder-led growth.

**Architecture:** Start with a narrow, painful B2B workflow where a bot can save time or generate revenue measurably, then package it as a managed AI automation service before gradually productizing into SaaS. Use a single core bot platform with integrations, audit logs, human-in-the-loop controls, and templates for repeatable vertical deployments.

**Tech Stack:** Python/FastAPI or Node.js/TypeScript backend, Postgres, Redis/queue, hosted LLM APIs, Playwright/browser automation where needed, webhook-first integrations, Stripe, PostHog, Sentry, Render/Fly.io/Railway or AWS/GCP, customer-facing dashboard in Next.js, CRM in HubSpot/Attio, docs in Notion/Markdown.

---

## Executive Summary

The fastest path to $10K MRR is **not** building a generic chatbot. The fastest path is selling a specific bot that performs a valuable recurring business workflow with measurable ROI.

Recommended initial wedge:

> **AI Revenue/Ops Bot for niche service businesses:** monitors inbound leads, qualifies prospects, drafts/sends follow-ups, updates CRM, books calls, and reports missed revenue opportunities.

Why this wedge:

- Clear ROI: more booked calls, faster response time, fewer missed leads.
- Customers already pay for leads/CRM/VA/admin help.
- Bot can be sold as a managed service before self-serve SaaS exists.
- Early deployments can be semi-manual behind the scenes while product is hardened.
- $500–$2,000/month pricing is credible if it books revenue or saves staff time.

Target $10K MRR math:

| Pricing Model | Customers Needed |
|---|---:|
| $499/month starter | 21 customers |
| $999/month growth | 11 customers |
| $1,500/month managed | 7 customers |
| $2,000/month premium | 5 customers |

Recommended path: land first 3 design partners at $500–$1,000/month, then move to $999–$1,500/month once case studies exist.

---

## Current Context / Assumptions

- The founder can build or coordinate AI/software implementation.
- The business starts with no existing revenue.
- The goal is recurring revenue, not one-off agency projects.
- The first product should avoid regulated use cases requiring heavy compliance.
- Initial customers should be reachable through direct outbound, communities, referrals, or founder network.
- Product should be useful even if LLMs are imperfect by including human review, logs, retries, and approval gates.

---

## Strategic Positioning

### Avoid

- Generic chatbot for websites.
- Generic AI agent marketplace.
- Consumer bot apps with weak willingness to pay.
- Fully autonomous trading/finance/medical/legal bots as the first monetized product.
- Custom automation agency work with no reusable product layer.

### Focus

Build a bot that is:

1. **Vertical-specific** — speaks the customer’s workflow language.
2. **Revenue-linked or cost-saving** — obvious budget justification.
3. **Recurring** — runs daily/weekly, not a one-time task.
4. **Auditable** — every action has logs and approval controls.
5. **Integration-first** — plugs into tools customers already use.
6. **Templateable** — each customer setup improves future deployments.

### Recommended Beachhead Niches

Pick one niche for the first 90 days:

| Niche | Pain | Bot Workflow | Buyer | Pricing Potential |
|---|---|---|---|---:|
| Local home services | Missed inbound leads | Lead triage + follow-up + booking | Owner/operator | $499–$1,500/mo |
| Recruiting agencies | Candidate sourcing/admin | Source, enrich, outreach, CRM update | Agency owner | $1,000–$3,000/mo |
| B2B agencies | Slow lead response | Lead qualification + proposal prep | Founder/ops lead | $750–$2,000/mo |
| Real estate teams | Lead nurture | Follow-up, showing scheduling, CRM hygiene | Team lead | $500–$1,500/mo |
| Clinics/wellness, non-medical admin only | Admin burden | Appointment reminders + intake routing | Practice manager | $500–$1,500/mo |

Recommended starting niche: **B2B agencies or local home services**, because lead response has direct ROI and low technical integration complexity.

---

## Product Blueprint

### Product Name Placeholder

`LeadOps Bot` / `ReplyPilot` / `BookedBot` / `OpsPilot`

### Core Promise

> “We respond to every inbound lead in under 2 minutes, qualify them, book the right calls, update your CRM, and show you exactly how much pipeline was saved.”

### Initial Feature Set

MVP must include only:

1. Inbound lead capture from email/forms/webhooks.
2. Lead enrichment from available public/context data.
3. Qualification rules configured per customer.
4. AI-drafted reply/follow-up sequence.
5. Human approval mode for first 2–4 weeks.
6. Calendar booking link insertion.
7. CRM/spreadsheet update.
8. Daily/weekly performance report.
9. Audit log of every lead, draft, sent message, and outcome.
10. Fail-safe alerts when bot confidence is low or integration breaks.

Do **not** initially build:

- Multi-tenant self-serve admin complexity beyond essentials.
- Complex autonomous voice calls.
- Marketplace of bot templates.
- Custom no-code workflow builder.
- Fine-tuned models.
- Mobile app.

---

## Monetization Strategy

### Pricing Ladder

| Plan | Price | Ideal Customer | Includes |
|---|---:|---|---|
| Pilot | $500 one-time or first month | Design partner | Setup + 30-day proof-of-value |
| Starter | $499/mo | Small business | 1 inbox/source, 1 workflow, approval mode, weekly report |
| Growth | $999/mo | Active lead flow | 3 sources, CRM sync, follow-up sequences, dashboard |
| Managed | $1,500–$2,500/mo | High-value leads | Done-for-you optimization, custom rules, monthly strategy review |
| Setup fee | $500–$2,000 | All non-pilot customers | Integration and workflow configuration |

Recommended early offer:

> “$500 setup + $1,000/month. If we don’t save or generate at least 3 qualified opportunities in 30 days, next month is free.”

### Expansion Revenue

- Add more inboxes/locations: +$250–$500/mo each.
- Add CRM automation/reporting: +$300–$700/mo.
- Add outbound reactivation campaigns: +$500–$1,500/mo.
- Add human QA/managed ops: +$1,000+/mo.

### Revenue Milestones

| Milestone | Target |
|---|---:|
| First paid pilot | Week 2–4 |
| $1K MRR | 1–2 customers |
| $3K MRR | 3–5 customers |
| $5K MRR | 5–7 customers |
| $10K MRR | 8–15 customers depending ARPA |

---

## KPI Framework

### Business KPIs

| KPI | Target by Month 1 | Target by Month 3 | Target by Month 6 |
|---|---:|---:|---:|
| MRR | $500–$1,500 | $3K–$7K | $10K+ |
| Active paying customers | 1–2 | 4–8 | 8–15 |
| ARPA | $500–$1,000 | $750–$1,500 | $1,000–$2,000 |
| Logo churn | 0% early | <5% monthly | <3% monthly |
| Gross margin | >60% | >75% | >80% |
| Sales calls booked/week | 5–10 | 10–20 | 20+ |
| Close rate from qualified calls | 20%+ | 25%+ | 30%+ |

### Product KPIs

| KPI | Good Target |
|---|---:|
| Lead response time | <2 minutes automated/drafted |
| AI draft approval rate | >80% after onboarding |
| Bot task success rate | >95% |
| Integration error rate | <2% |
| Human intervention rate | Starts high, trends below 20% |
| Qualified leads recovered/booked | Customer-specific ROI target |
| Weekly report delivery | 100% |

### Growth KPIs

| KPI | Target |
|---|---:|
| Cold email positive reply rate | 3–8% |
| LinkedIn reply rate | 5–15% |
| Demo show rate | 70%+ |
| Pilot-to-paid conversion | 50%+ |
| Referral asks sent | 100% of satisfied customers |

---

## Timeline Overview

### Phase 0 — Choose Wedge and Offer (Days 1–3)

Goal: pick one niche, one painful workflow, one paid pilot offer.

Deliverables:

- Niche selection memo.
- ICP definition.
- Landing page copy.
- 100-prospect lead list.
- Demo script.
- Pilot contract/payment link.

### Phase 1 — Concierge MVP (Days 4–21)

Goal: close 1–3 design partners and manually/semiautomatically deliver the workflow.

Deliverables:

- Bot workflow prototype.
- Manual QA console/log sheet.
- First customer integration.
- First weekly ROI report.
- Case study draft.

### Phase 2 — Productize Repeated Workflow (Days 22–60)

Goal: reduce manual delivery, harden integrations, charge recurring.

Deliverables:

- Multi-customer backend structure.
- Dashboard/audit log.
- Stripe recurring billing.
- CRM/email/calendar integrations.
- Onboarding checklist.

### Phase 3 — Repeatable Acquisition (Days 61–120)

Goal: scale from founder-led sales to predictable pipeline.

Deliverables:

- 2–3 case studies.
- Outbound engine.
- Partner/referral channel.
- Content proof assets.
- Sales CRM and conversion dashboard.

### Phase 4 — $10K MRR and Defensibility (Days 121–180)

Goal: reach/retain $10K MRR and create moat via workflow data, templates, and outcomes.

Deliverables:

- 8–15 paying customers.
- Churn/retention dashboard.
- Vertical templates.
- Customer success playbook.
- Roadmap for next adjacent workflow.

---

## Step-by-Step Plan

### Task 1: Select the Beachhead Niche

**Objective:** Choose the first market based on pain intensity, budget, reachability, and implementation simplicity.

**Files:**
- Create: `.hermes/plans/research/niche-scorecard.md`

**Step 1: Create a scoring table**

Use this table:

```markdown
# Niche Scorecard

| Niche | Pain Urgency 1-5 | Budget 1-5 | Reachability 1-5 | Workflow Repeatability 1-5 | Integration Simplicity 1-5 | Total | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| Local home services | | | | | | | |
| B2B agencies | | | | | | | |
| Recruiting agencies | | | | | | | |
| Real estate teams | | | | | | | |
| Non-medical clinic admin | | | | | | | |
```

**Step 2: Pick one niche**

Decision rule:

- Pick the highest total score.
- If tied, pick the niche where the founder can reach 100 prospects fastest.

**Step 3: Define ICP**

Document:

```markdown
## ICP

- Company size:
- Monthly lead volume:
- Current tools:
- Buyer title:
- Trigger event:
- Pain language:
- Current workaround:
- Willingness to pay signal:
```

**Step 4: Commit**

```bash
git add .hermes/plans/research/niche-scorecard.md
git commit -m "docs: define bot business beachhead niche"
```

---

### Task 2: Write the Paid Pilot Offer

**Objective:** Create a concrete offer that sells outcomes, not technology.

**Files:**
- Create: `.hermes/plans/business/pilot-offer.md`

**Step 1: Draft the one-line offer**

Use this template:

```markdown
# Paid Pilot Offer

We help [ICP] [desired outcome] by [bot workflow] without [common objection].

Example:
We help B2B agencies respond to every inbound lead in under 2 minutes, qualify the prospect, and book sales calls without hiring another coordinator.
```

**Step 2: Define the 30-day pilot**

```markdown
## 30-Day Pilot

Price: $500 setup + $1,000/month, cancellable after 30 days.

Included:
- Connect 1 lead source
- Create qualification rules
- Draft/respond to inbound leads
- Sync qualified leads to CRM/sheet
- Weekly ROI report
- Human approval mode until customer signs off

Success criteria:
- Response time under 2 minutes for eligible leads
- At least 80% acceptable AI drafts
- At least 3 qualified opportunities recovered/booked, or next month free
```

**Step 3: Add risk reversal**

```markdown
## Guarantee

If we do not recover or create at least 3 qualified opportunities in the first 30 days, the next month is free. Customer still owns all workflow documentation and data exports.
```

**Step 4: Commit**

```bash
git add .hermes/plans/business/pilot-offer.md
git commit -m "docs: write paid pilot offer"
```

---

### Task 3: Build the Prospect List

**Objective:** Create a targeted list of 100 prospects for founder-led sales.

**Files:**
- Create: `growth/prospects.csv`

**Step 1: Create CSV structure**

```csv
company,website,buyer_name,buyer_title,email,linkedin,niche,lead_source,current_tools,pain_hypothesis,status,last_contact,next_step,notes
```

**Step 2: Fill 100 rows**

Sources:

- Google Maps/local directories for local services.
- Clutch/UpCity for agencies.
- LinkedIn Sales Navigator/manual search.
- Industry associations.
- Communities and Slack groups.

**Step 3: Segment the list**

Set `pain_hypothesis` to one of:

- Slow lead response
- Missed after-hours leads
- Manual CRM updates
- No structured follow-up
- Founder still handles sales admin

**Step 4: Commit**

```bash
git add growth/prospects.csv
git commit -m "growth: add initial prospect list"
```

---

### Task 4: Write Outbound Messaging

**Objective:** Create short, specific outreach sequences for email and LinkedIn.

**Files:**
- Create: `growth/outbound-copy.md`

**Step 1: Write cold email v1**

```markdown
## Cold Email 1

Subject: quick lead response idea for {{company}}

Hi {{first_name}},

Noticed {{company}} gets inbound leads through {{channel}}.

I’m building a small AI ops bot that replies to new leads in under 2 minutes, qualifies them, updates the CRM, and books the right call — with human approval before anything sends.

For teams like yours, the goal is fewer missed leads without hiring another coordinator.

Would it be worth a 15-minute look if I can show the exact workflow?

— {{sender}}
```

**Step 2: Write follow-up 1**

```markdown
## Follow-up 1

Subject: Re: quick lead response idea for {{company}}

Worth clarifying: this is not a website chatbot.

It watches actual inbound leads, drafts/sends follow-ups, books calls, and creates a weekly report showing leads saved, response time, and booked opportunities.

If useful, I can mock up the workflow for {{company}} before we talk.
```

**Step 3: Write LinkedIn DM**

```markdown
## LinkedIn DM

Saw you’re running {{company}}. I’m testing an AI lead-ops bot for {{niche}} teams: instant lead reply, qualification, CRM update, booking, weekly ROI report. Not a generic chatbot. Open to me sending a 2-min workflow mockup?
```

**Step 4: Commit**

```bash
git add growth/outbound-copy.md
git commit -m "growth: draft outbound sequence"
```

---

### Task 5: Create Landing Page Copy

**Objective:** Create copy for a simple landing page before building a full app.

**Files:**
- Create: `growth/landing-page-copy.md`

**Step 1: Add headline section**

```markdown
# Landing Page Copy

## Hero

Headline: Never miss another qualified inbound lead.

Subheadline: An AI lead-ops bot that responds in under 2 minutes, qualifies prospects, books calls, updates your CRM, and sends a weekly pipeline-saved report.

CTA: Book a 15-minute workflow audit
```

**Step 2: Add problem bullets**

```markdown
## Problems

- Leads arrive while your team is busy or offline.
- Follow-up depends on manual discipline.
- CRM updates fall behind.
- Owners cannot see how many opportunities are leaking.
```

**Step 3: Add product bullets**

```markdown
## What the bot does

- Watches your lead sources
- Drafts or sends fast personalized replies
- Applies your qualification rules
- Routes good leads to the right next step
- Updates CRM/spreadsheets
- Reports response time, leads handled, qualified opportunities, and booked calls
```

**Step 4: Commit**

```bash
git add growth/landing-page-copy.md
git commit -m "growth: write landing page copy"
```

---

### Task 6: Define MVP Technical Architecture

**Objective:** Specify the simplest production-ready architecture for the first bot deployments.

**Files:**
- Create: `docs/mvp-architecture.md`

**Step 1: Write architecture overview**

```markdown
# MVP Architecture

## Components

- Webhook/API ingestion service
- Customer/workflow configuration store
- Queue worker for bot tasks
- LLM drafting/classification service
- Integration adapters for email, CRM, calendar, and Slack/Telegram alerts
- Audit log
- Minimal dashboard
- Stripe billing
```

**Step 2: Choose stack**

```markdown
## Stack

Backend: FastAPI + Python 3.11
Worker: Celery/RQ or simple async worker initially
Database: Postgres
Cache/Queue: Redis
Frontend: Next.js dashboard
LLM: OpenAI/Anthropic with abstraction layer
Auth: Clerk/Auth.js/Supabase Auth
Billing: Stripe
Analytics: PostHog
Errors: Sentry
Hosting: Render/Fly.io/Railway for speed; move later only if needed
```

**Step 3: Add data model sketch**

```markdown
## Core Tables

customers(id, name, plan, status, created_at)
workflows(id, customer_id, name, rules_json, approval_required, active)
lead_events(id, customer_id, source, payload_json, status, received_at)
bot_actions(id, lead_event_id, action_type, draft_text, status, confidence, created_at, approved_at, sent_at)
integrations(id, customer_id, type, encrypted_credentials, status)
weekly_reports(id, customer_id, metrics_json, sent_at)
```

**Step 4: Commit**

```bash
git add docs/mvp-architecture.md
git commit -m "docs: define mvp architecture"
```

---

### Task 7: Define Bot Workflow Spec

**Objective:** Make the bot behavior deterministic enough to implement and sell.

**Files:**
- Create: `docs/bot-workflow-spec.md`

**Step 1: Write state machine**

```markdown
# Bot Workflow Spec

## Lead Event States

1. received
2. enriched
3. qualified
4. draft_created
5. awaiting_approval
6. sent
7. booked
8. disqualified
9. failed
```

**Step 2: Add confidence gates**

```markdown
## Confidence Gates

- If confidence >= 0.85 and customer has approved autonomous mode: send.
- If confidence 0.60–0.84: queue for human approval.
- If confidence < 0.60: alert human and do not draft-send.
- If integration fails: retry 3 times, then alert human.
```

**Step 3: Add audit requirements**

```markdown
## Audit Log Requirements

Every action records:
- input payload
- prompt/template version
- model used
- generated draft
- confidence score
- approval user if applicable
- sent timestamp
- external API response or error
```

**Step 4: Commit**

```bash
git add docs/bot-workflow-spec.md
git commit -m "docs: specify bot workflow"
```

---

### Task 8: Implement Concierge MVP Without Full SaaS

**Objective:** Deliver value manually/semiautomatically before building a complete product.

**Files:**
- Create: `ops/concierge-runbook.md`
- Create: `ops/customer-onboarding-checklist.md`

**Step 1: Create concierge runbook**

```markdown
# Concierge MVP Runbook

Daily:
1. Check connected lead sources.
2. Review new lead events.
3. Generate/inspect AI drafts.
4. Approve/send responses.
5. Update CRM/sheet.
6. Log outcomes.
7. Note failures for productization.

Weekly:
1. Count leads handled.
2. Count qualified leads.
3. Count booked calls.
4. Calculate response time improvement.
5. Send customer report.
```

**Step 2: Create onboarding checklist**

```markdown
# Customer Onboarding Checklist

- Customer name:
- Lead sources:
- CRM/spreadsheet:
- Calendar link:
- Offer/service details:
- Qualification rules:
- Disqualification rules:
- Tone examples:
- Approval contact:
- Reporting cadence:
- Success criteria:
```

**Step 3: Commit**

```bash
git add ops/concierge-runbook.md ops/customer-onboarding-checklist.md
git commit -m "ops: add concierge mvp runbooks"
```

---

### Task 9: Build First Technical Prototype

**Objective:** Build the smallest bot that can process one lead source end-to-end.

**Files:**
- Create: `app/main.py`
- Create: `app/models.py`
- Create: `app/bot/draft.py`
- Create: `tests/test_lead_workflow.py`

**Step 1: Write failing test**

```python
def test_inbound_lead_creates_draft(client):
    response = client.post('/webhooks/lead', json={
        'customer_id': 'test_customer',
        'name': 'Jane Buyer',
        'email': 'jane@example.com',
        'message': 'I need help next week and want pricing.'
    })

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'draft_created'
    assert body['draft']
    assert 'Jane' in body['draft']
```

**Step 2: Run test to verify failure**

Run:

```bash
pytest tests/test_lead_workflow.py -v
```

Expected: FAIL because endpoint does not exist.

**Step 3: Implement minimal endpoint**

```python
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr

app = FastAPI()

class LeadPayload(BaseModel):
    customer_id: str
    name: str
    email: EmailStr
    message: str

@app.post('/webhooks/lead')
def receive_lead(payload: LeadPayload):
    first_name = payload.name.split()[0]
    draft = (
        f"Hi {first_name}, thanks for reaching out. "
        "Happy to help — here is a link to book a quick call: {{calendar_link}}"
    )
    return {'status': 'draft_created', 'draft': draft}
```

**Step 4: Run test to verify pass**

Run:

```bash
pytest tests/test_lead_workflow.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/main.py tests/test_lead_workflow.py
git commit -m "feat: add inbound lead draft endpoint"
```

---

### Task 10: Add Human Approval Queue

**Objective:** Prevent unsafe autonomous messages during early customer deployments.

**Files:**
- Modify: `app/main.py`
- Create: `app/approval.py`
- Create: `tests/test_approval_queue.py`

**Step 1: Write failing test**

```python
def test_low_confidence_lead_requires_approval(client):
    response = client.post('/webhooks/lead', json={
        'customer_id': 'test_customer',
        'name': 'Unclear Lead',
        'email': 'lead@example.com',
        'message': 'maybe maybe something random'
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'awaiting_approval'
```

**Step 2: Implement confidence heuristic**

```python
def estimate_confidence(message: str) -> float:
    buying_terms = ['pricing', 'quote', 'book', 'call', 'available', 'help', 'need']
    hits = sum(term in message.lower() for term in buying_terms)
    return min(1.0, 0.4 + hits * 0.15)
```

**Step 3: Gate sending/drafting status**

```python
confidence = estimate_confidence(payload.message)
status = 'draft_created' if confidence >= 0.85 else 'awaiting_approval'
```

**Step 4: Run tests**

```bash
pytest tests/test_lead_workflow.py tests/test_approval_queue.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/main.py app/approval.py tests/test_approval_queue.py
git commit -m "feat: add human approval gate"
```

---

### Task 11: Add Audit Logging

**Objective:** Make every bot decision inspectable for customer trust and debugging.

**Files:**
- Create: `app/audit.py`
- Modify: `app/main.py`
- Create: `tests/test_audit_log.py`

**Step 1: Write failing test**

```python
def test_lead_event_writes_audit_log(client, audit_store):
    response = client.post('/webhooks/lead', json={
        'customer_id': 'test_customer',
        'name': 'Jane Buyer',
        'email': 'jane@example.com',
        'message': 'I need pricing.'
    })

    assert response.status_code == 200
    events = audit_store.list_events(customer_id='test_customer')
    assert len(events) == 1
    assert events[0]['action_type'] == 'lead_draft_created'
```

**Step 2: Implement simple audit store**

```python
class InMemoryAuditStore:
    def __init__(self):
        self.events = []

    def record(self, event: dict) -> None:
        self.events.append(event)

    def list_events(self, customer_id: str):
        return [e for e in self.events if e.get('customer_id') == customer_id]
```

**Step 3: Record audit event from endpoint**

```python
audit_store.record({
    'customer_id': payload.customer_id,
    'action_type': 'lead_draft_created',
    'input': payload.model_dump(),
    'draft': draft,
    'confidence': confidence,
})
```

**Step 4: Run tests**

```bash
pytest tests/test_audit_log.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/audit.py app/main.py tests/test_audit_log.py
git commit -m "feat: add audit logging"
```

---

### Task 12: Add Weekly ROI Report

**Objective:** Convert product activity into customer-perceived business value.

**Files:**
- Create: `app/reports.py`
- Create: `tests/test_weekly_report.py`

**Step 1: Write failing test**

```python
def test_weekly_report_summarizes_leads_and_bookings():
    events = [
        {'status': 'sent', 'qualified': True, 'booked': True, 'response_time_sec': 45},
        {'status': 'sent', 'qualified': True, 'booked': False, 'response_time_sec': 90},
        {'status': 'disqualified', 'qualified': False, 'booked': False, 'response_time_sec': 60},
    ]

    report = build_weekly_report(events)

    assert report['leads_handled'] == 3
    assert report['qualified_leads'] == 2
    assert report['booked_calls'] == 1
    assert report['avg_response_time_sec'] == 65
```

**Step 2: Implement report function**

```python
def build_weekly_report(events: list[dict]) -> dict:
    total = len(events)
    qualified = sum(1 for e in events if e.get('qualified'))
    booked = sum(1 for e in events if e.get('booked'))
    avg_response = int(sum(e.get('response_time_sec', 0) for e in events) / total) if total else 0
    return {
        'leads_handled': total,
        'qualified_leads': qualified,
        'booked_calls': booked,
        'avg_response_time_sec': avg_response,
    }
```

**Step 3: Run tests**

```bash
pytest tests/test_weekly_report.py -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add app/reports.py tests/test_weekly_report.py
git commit -m "feat: add weekly roi report"
```

---

### Task 13: Close First Design Partners

**Objective:** Turn prospect conversations into paid pilots.

**Files:**
- Modify: `growth/prospects.csv`
- Create: `sales/demo-script.md`
- Create: `sales/discovery-notes-template.md`

**Step 1: Write demo script**

```markdown
# Demo Script

1. Confirm pain: “How fast do new leads get a response today?”
2. Quantify leak: “How many leads per week? What is one qualified lead worth?”
3. Show workflow: inbound lead → bot draft → approval/send → CRM update → report.
4. Ask: “If this recovered 3+ qualified opportunities/month, would $1,000/month make sense?”
5. Close pilot: “We can set this up for one source this week.”
```

**Step 2: Track statuses**

Use statuses:

- not_contacted
- contacted
- replied
- call_booked
- pilot_sent
- closed_won
- closed_lost

**Step 3: Weekly sales target**

- Contact 100 prospects/week.
- Book 5–10 calls/week.
- Close 1 paid pilot every 10–20 qualified calls.

**Step 4: Commit**

```bash
git add growth/prospects.csv sales/demo-script.md sales/discovery-notes-template.md
git commit -m "sales: add design partner sales assets"
```

---

### Task 14: Onboard First Customer Manually

**Objective:** Deliver the workflow to one paying customer with maximum learning and minimum product scope.

**Files:**
- Create: `customers/<customer_slug>/onboarding.md`
- Create: `customers/<customer_slug>/workflow-rules.md`
- Create: `customers/<customer_slug>/weekly-report-001.md`

**Step 1: Capture setup details**

```markdown
# Customer Onboarding

- Lead source:
- CRM/spreadsheet:
- Calendar URL:
- Offer description:
- Good lead criteria:
- Bad lead criteria:
- Tone examples:
- Approval channel:
- Reporting day/time:
```

**Step 2: Write workflow rules**

```markdown
# Workflow Rules

Qualified if:
- [rule]
- [rule]

Disqualified if:
- [rule]
- [rule]

Default reply style:
- concise
- helpful
- direct CTA to calendar
```

**Step 3: Send first weekly report**

```markdown
# Weekly Report 001

- Leads handled:
- Qualified leads:
- Replies sent:
- Calls booked:
- Avg response time:
- Issues found:
- Next optimization:
```

**Step 4: Commit**

```bash
git add customers/<customer_slug>/
git commit -m "ops: onboard first pilot customer"
```

---

### Task 15: Convert Pilot to Recurring Subscription

**Objective:** Move from validation to MRR.

**Files:**
- Create: `sales/renewal-script.md`
- Modify: `customers/<customer_slug>/weekly-report-004.md`

**Step 1: Prepare ROI summary**

```markdown
# Pilot ROI Summary

In 30 days:
- Leads handled:
- Qualified opportunities:
- Booked calls:
- Average response time:
- Manual hours saved:
- Estimated pipeline value:
```

**Step 2: Use renewal script**

```markdown
Based on the pilot, the bot handled {{leads}} leads, recovered {{qualified}} qualified opportunities, and booked {{booked}} calls.

The ongoing plan is ${{price}}/month and includes monitoring, optimization, weekly reporting, and support.

Should we keep it running for next month?
```

**Step 3: Send Stripe subscription link**

Create product:

- Name: LeadOps Bot Growth
- Price: $999/month
- Optional setup fee for future customers: $500–$2,000

**Step 4: Commit**

```bash
git add sales/renewal-script.md customers/<customer_slug>/weekly-report-004.md
git commit -m "sales: add pilot renewal process"
```

---

### Task 16: Build Case Study Asset

**Objective:** Turn the first successful deployment into proof for acquisition.

**Files:**
- Create: `growth/case-study-template.md`
- Create: `growth/case-studies/<customer_slug>.md`

**Step 1: Create template**

```markdown
# Case Study: {{Customer}}

## Before

- Lead response process:
- Missed opportunity problem:
- Manual workload:

## Implementation

- Sources connected:
- Workflow rules:
- Approval process:

## Results

- Leads handled:
- Qualified opportunities:
- Booked calls:
- Response time improvement:
- Customer quote:

## Takeaway

{{One-sentence ROI story}}
```

**Step 2: Ask customer for quote**

```markdown
Would you be comfortable with a short quote like:

“The bot helped us respond faster and gave us visibility into leads we were previously missing.”
```

**Step 3: Commit**

```bash
git add growth/case-study-template.md growth/case-studies/<customer_slug>.md
git commit -m "growth: add first case study"
```

---

### Task 17: Build Repeatable Growth Engine

**Objective:** Create weekly acquisition operations that reliably produce sales calls.

**Files:**
- Create: `growth/weekly-growth-system.md`

**Step 1: Define weekly cadence**

```markdown
# Weekly Growth System

Monday:
- Add 50 new prospects
- Send 50 first-touch emails

Tuesday:
- Send 50 first-touch emails
- Follow up with prior week replies

Wednesday:
- Publish one proof post/case study snippet
- Send LinkedIn DMs to 25 prospects

Thursday:
- Run demos/sales calls
- Ask customers/referrals for introductions

Friday:
- Review metrics
- Improve copy
- Update CRM
```

**Step 2: Define metrics review**

```markdown
## Weekly Metrics

- Prospects added
- Emails sent
- Positive replies
- Calls booked
- Calls completed
- Pilots offered
- Pilots closed
- New MRR
- Churn risk
```

**Step 3: Commit**

```bash
git add growth/weekly-growth-system.md
git commit -m "growth: define weekly acquisition system"
```

---

### Task 18: Productize Onboarding

**Objective:** Reduce setup time per customer from days to hours.

**Files:**
- Create: `ops/onboarding-sop.md`
- Create: `app/templates/default_workflows.json`

**Step 1: Create onboarding SOP**

```markdown
# Onboarding SOP

Target: customer live within 48 hours.

1. Collect lead source access.
2. Collect CRM/calendar details.
3. Import qualification rules.
4. Configure default prompts.
5. Run 5 test leads.
6. Review drafts with customer.
7. Enable approval mode.
8. Schedule first weekly report.
```

**Step 2: Create workflow templates**

```json
{
  "b2b_agency": {
    "qualified_terms": ["pricing", "proposal", "call", "audit", "strategy", "availability"],
    "disqualified_terms": ["job", "internship", "guest post"],
    "default_cta": "book a quick fit call"
  },
  "home_services": {
    "qualified_terms": ["quote", "estimate", "repair", "install", "emergency", "available"],
    "disqualified_terms": ["vendor", "job", "partnership"],
    "default_cta": "schedule an estimate"
  }
}
```

**Step 3: Commit**

```bash
git add ops/onboarding-sop.md app/templates/default_workflows.json
git commit -m "ops: productize onboarding templates"
```

---

### Task 19: Add Billing and Plan Enforcement

**Objective:** Make recurring revenue operationally reliable.

**Files:**
- Create: `docs/billing-plans.md`
- Create: `app/billing.py`
- Create: `tests/test_billing_limits.py`

**Step 1: Document plans**

```markdown
# Billing Plans

Starter: $499/month
- 1 lead source
- 1 workflow
- approval mode
- weekly report

Growth: $999/month
- 3 lead sources
- CRM sync
- autonomous mode after approval
- weekly report

Managed: $1,500+/month
- custom workflows
- monthly optimization
- priority support
```

**Step 2: Write failing test**

```python
def test_starter_plan_limited_to_one_lead_source():
    assert can_add_lead_source(plan='starter', existing_sources=0) is True
    assert can_add_lead_source(plan='starter', existing_sources=1) is False
```

**Step 3: Implement limit function**

```python
PLAN_LIMITS = {
    'starter': {'lead_sources': 1},
    'growth': {'lead_sources': 3},
    'managed': {'lead_sources': 999},
}

def can_add_lead_source(plan: str, existing_sources: int) -> bool:
    return existing_sources < PLAN_LIMITS[plan]['lead_sources']
```

**Step 4: Run tests**

```bash
pytest tests/test_billing_limits.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add docs/billing-plans.md app/billing.py tests/test_billing_limits.py
git commit -m "feat: add billing plan limits"
```

---

### Task 20: Build Retention and Customer Success System

**Objective:** Keep churn low by proving ROI every week.

**Files:**
- Create: `ops/customer-success-playbook.md`
- Create: `ops/churn-risk-scorecard.md`

**Step 1: Define health score**

```markdown
# Churn Risk Scorecard

| Signal | Healthy | Risk |
|---|---|---|
| Weekly report opened/responded | yes | no for 2 weeks |
| Bot handled leads | increasing/stable | no activity |
| Qualified opportunities | meets expectation | below target |
| Draft approval rate | >80% | <60% |
| Integration errors | <2% | repeated failures |
| Customer sentiment | positive | neutral/negative |
```

**Step 2: Define monthly review**

```markdown
# Customer Success Playbook

Monthly agenda:
1. Review leads handled.
2. Review booked calls/opportunities.
3. Show response time improvement.
4. Identify bad drafts or missed rules.
5. Add one optimization.
6. Ask for referral/testimonial if healthy.
```

**Step 3: Commit**

```bash
git add ops/customer-success-playbook.md ops/churn-risk-scorecard.md
git commit -m "ops: add retention system"
```

---

## Files Likely to Change

Business/growth files:

- `.hermes/plans/research/niche-scorecard.md`
- `.hermes/plans/business/pilot-offer.md`
- `growth/prospects.csv`
- `growth/outbound-copy.md`
- `growth/landing-page-copy.md`
- `growth/weekly-growth-system.md`
- `growth/case-study-template.md`
- `growth/case-studies/<customer_slug>.md`
- `sales/demo-script.md`
- `sales/discovery-notes-template.md`
- `sales/renewal-script.md`

Ops files:

- `ops/concierge-runbook.md`
- `ops/customer-onboarding-checklist.md`
- `ops/onboarding-sop.md`
- `ops/customer-success-playbook.md`
- `ops/churn-risk-scorecard.md`
- `customers/<customer_slug>/onboarding.md`
- `customers/<customer_slug>/workflow-rules.md`
- `customers/<customer_slug>/weekly-report-*.md`

Technical files:

- `docs/mvp-architecture.md`
- `docs/bot-workflow-spec.md`
- `docs/billing-plans.md`
- `app/main.py`
- `app/models.py`
- `app/bot/draft.py`
- `app/approval.py`
- `app/audit.py`
- `app/reports.py`
- `app/billing.py`
- `app/templates/default_workflows.json`
- `tests/test_lead_workflow.py`
- `tests/test_approval_queue.py`
- `tests/test_audit_log.py`
- `tests/test_weekly_report.py`
- `tests/test_billing_limits.py`

---

## Validation Plan

### Business Validation

Run weekly review:

```markdown
# Weekly Business Review

- MRR:
- New MRR:
- Churned MRR:
- Prospects contacted:
- Positive replies:
- Calls booked:
- Calls completed:
- Pilots closed:
- Pilot-to-paid conversion:
- Customer ROI evidence:
- Biggest objection:
- Next copy/test change:
```

### Product Validation

For every customer:

- Verify lead ingestion works.
- Verify drafts are generated correctly.
- Verify approval gate works.
- Verify no autonomous send happens before customer approval.
- Verify CRM/sheet update.
- Verify weekly report accuracy.
- Verify audit logs for every action.

### Technical Validation Commands

```bash
pytest tests/ -q
ruff check app tests
mypy app
```

If using TypeScript/Next.js:

```bash
npm run lint
npm run typecheck
npm test
```

---

## Growth Tactics

### Founder-Led Outbound

- 100 targeted prospects/week.
- Personalized first line based on lead flow/tooling.
- Offer a workflow mockup, not “AI automation.”
- Follow up twice.
- Track every response in CRM.

### Proof-Led Content

Post weekly:

- “Before/after response time” screenshots.
- Anonymized workflow diagrams.
- Missed-lead calculator.
- Case study snippets.
- Lessons from bad AI drafts and how approval gates fixed them.

### Partnerships

Partner with:

- CRM consultants.
- Web design agencies.
- Paid ad agencies.
- Local business coaches.
- Niche SaaS implementers.

Offer:

- 15–25% recurring commission for referred customers.
- Co-branded workflow audit.

### Referral Loop

After every positive weekly report:

```markdown
Glad this is helping. Do you know one other owner/team that loses leads because follow-up is too slow? Happy to do a free workflow audit for them.
```

---

## Contingency Plans

### If cold outbound fails

Symptoms:

- Positive reply rate <2% after 300 targeted sends.

Actions:

1. Narrow ICP further.
2. Replace generic AI language with pain-specific language.
3. Offer free workflow audit instead of demo.
4. Use Loom teardown of their current lead flow.
5. Switch channel to LinkedIn/community/referrals.

### If demos do not close

Symptoms:

- <10% close rate from qualified calls.

Actions:

1. Add stronger guarantee.
2. Lower upfront friction with $500 paid audit/pilot.
3. Show mockup before the call.
4. Quantify missed lead economics during discovery.
5. Ask explicitly: “What would make this a no-brainer?”

### If bot quality is unreliable

Symptoms:

- Draft approval rate <60%.
- Customer edits every message heavily.

Actions:

1. Add stricter templates.
2. Reduce autonomy.
3. Use retrieval from customer FAQ/tone examples.
4. Add disallowed claims list.
5. Keep human approval until >80% approval rate.

### If integration work becomes too custom

Symptoms:

- Each customer takes >1 week to onboard.

Actions:

1. Standardize on email + Google Sheets first.
2. Charge setup fees.
3. Reject unsupported tools temporarily.
4. Build only the top 2 repeated integrations.
5. Create templates per niche.

### If churn risk appears

Symptoms:

- Customer stops engaging.
- Reports show low volume or unclear ROI.

Actions:

1. Schedule ROI review.
2. Add adjacent workflow with more volume.
3. Adjust qualification rules.
4. Move them to lower plan rather than lose logo.
5. Ask for direct reason if cancellation is likely.

---

## 180-Day Financial Model

| Month | Customers | ARPA | MRR | Primary Focus |
|---:|---:|---:|---:|---|
| 1 | 1 | $500 | $500 | Validate pain and workflow |
| 2 | 3 | $750 | $2,250 | Convert pilots to recurring |
| 3 | 5 | $1,000 | $5,000 | Case studies + repeat outbound |
| 4 | 7 | $1,100 | $7,700 | Productize onboarding |
| 5 | 9 | $1,200 | $10,800 | Retention + referrals |
| 6 | 12 | $1,250 | $15,000 | Expand channels/templates |

---

## Open Questions

1. Which niche can the founder reach fastest with credible context?
2. Does the founder prefer a managed-service wedge or pure SaaS from day one?
3. Which integrations are mandatory for the chosen niche?
4. What is the strongest measurable ROI event: booked call, qualified lead, saved admin hours, or recovered revenue?
5. What level of autonomy will early customers tolerate?
6. Is the founder willing to manually QA messages for the first 30–60 days?

---

## Final Recommendation

Start with a **managed AI lead-ops bot** for one narrow niche. Sell paid pilots immediately. Use manual operations behind the scenes where necessary. Productize only the repeated parts. Do not build a generic platform until at least 5 customers are paying for the same workflow.

The path to $10K MRR is:

1. Pick one niche.
2. Sell one outcome.
3. Close paid pilots.
4. Deliver with human-in-the-loop reliability.
5. Report ROI weekly.
6. Convert to recurring.
7. Use proof to repeat outbound and referrals.
8. Productize only after repetition is proven.
