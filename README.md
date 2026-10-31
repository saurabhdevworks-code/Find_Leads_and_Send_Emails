# UP Digital Agency Lead CRM

A GitHub-backed CRM scaffold for researching publicly listed digital marketing agencies in Uttar Pradesh and managing compliant, low-volume business outreach.

## Current status
- CRM structure initialized.
- No lead records have been collected or emailed.
- No email automation is active.
- The repository is currently public. All committed files, including future lead records, are publicly visible. Do not commit credentials, private correspondence, or personal data.

## Repository layout
- `data/leads.csv` — verified business leads and contact provenance.
- `data/email-logs.csv` — outreach event history.
- `data/follow-ups.csv` — follow-up queue.
- `data/suppression.csv` — opt-outs, complaints, and do-not-contact records.
- `districts/district-progress.json` — district rotation state.
- `config/settings.json` — non-secret workflow settings.

## Lead quality rules
1. Only record businesses supported by a public source URL.
2. Never guess or generate an email address or phone number.
3. Keep unverified contacts out of the send queue.
4. Deduplicate by normalized email and website/domain; retain source details.
5. Respect opt-outs, bounce events, and do-not-contact requests.
6. Outreach must identify the sender, be relevant to the business, and provide a clear opt-out method.
7. Do not bypass website access controls, CAPTCHAs, login walls, or published access restrictions. Follow applicable website terms and laws.

## Secrets
Never store Gmail credentials, OAuth tokens, API keys, or app passwords in this repository. Use GitHub Actions Secrets only after the workflow has been reviewed and tested.

## Automation status
This repository is a data scaffold only. A scheduled workflow must not be enabled until discovery, verification, suppression checks, send limits, and error handling are implemented and tested.
