# UP Digital Agency Lead CRM

A GitHub-backed CRM scaffold for researching publicly listed digital marketing agencies in Uttar Pradesh and managing compliant, low-volume business outreach.

## Current status
- CRM structure initialized.
- A first public-source discovery engine is implemented using OpenStreetMap Nominatim and Overpass.
- Discovery is manual; no scheduled run or email automation is active.
- Results are uploaded as a downloadable GitHub Actions artifact and are not committed to this public repository.
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

## Custom lead-search form

Open the repository's **Actions** tab, choose **Configure Lead Search**, click **Run workflow**, and enter:
- Industry / business type
- Location and district
- Number of leads (1–100)
- Custom fields as a comma-separated list (for example: `owner_name,instagram,linkedin,company_size`)
- Any extra filters or instructions

The workflow saves your request to `config/search-request.json`.

### Run discovery
1. First run **Configure Lead Search** and confirm the saved request.
2. Open **Actions** → **Run Lead Discovery** → **Run workflow**.
3. Open the completed run and download the `lead-discovery-results` artifact.
4. The artifact contains a CSV and `run-summary.json`.

The first discovery source is OpenStreetMap. It only returns businesses mapped with relevant industry tags; coverage can be incomplete. Public map data is not proof that a business is currently active. Email addresses are only syntax-checked, not deliverability-verified. Requested custom fields that are not present in the source are left blank. No emails are sent.

**Public-repository safety:** lead results are deliberately uploaded as a temporary workflow artifact (14-day retention), not committed to `data/leads.csv`, because this repository is public. Make the repository private before enabling persistent CRM storage of real lead/contact data.
