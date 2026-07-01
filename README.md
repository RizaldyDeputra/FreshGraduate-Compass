# Fresh Graduate Compass

I got tired of scrolling through JobStreet every day just to find out half the "matching" jobs wanted 2+ years of experience. So I built this instead.

It reads my JobStreet email alerts, runs them through Gemini to actually check if a listing fits a fresh grad, and dumps the good ones into a Notion database.

## What it does

1. Pulls JobStreet alert emails from Gmail (IMAP, read-only)
2. Sends the content to Gemini with a candidate profile + filtering rules
3. Gemini extracts each job listing, scores it, and flags whether it's actually worth applying to
4. Anything that passes gets written to a Notion database, with a direct link back to the posting
5. Runs once a day via GitHub Actions — you just open Notion, no scrolling

Everything here could runs on free tiers. 

## Why not just use the email alert as-is

Keyword-based alerts are dumb by design. "Business Analyst" matches a listing whether it wants a fresh grad or someone with 5 years and a PMP cert. This adds an actual reasoning step before the job ever reaches you, instead of relying on JobStreet's matching logic.

## Setup

You'll need accounts for Gmail, Google AI Studio, Notion, and GitHub. All free.

### 1. Gmail

Turn on IMAP (Settings → Forwarding and POP/IMAP → Enable IMAP), then generate an App Password at `myaccount.google.com/apppasswords`. You need 2FA on for this to show up.

### 2. Gemini API key

Grab one at `aistudio.google.com/app/apikey`. Free tier is 15 requests/min and 1M tokens/day, which is way more than a daily job scan needs.

### 3. Notion

- Create an integration at `notion.so/developers`, copy the token
- Build a database with these properties:

  | Property | Type |
  |---|---|
  | Name | Title |
  | Company | Text |
  | Location | Text |
  | Link | URL |
  | Score | Number |
  | Label | Select |
  | Experience Required | Text |
  | Reason | Text |
  | Highlight | Text |
  | Status | Select |
  | Date Found | Date |

- Open the database, click `...` → **Connect to** → select your integration. Skip this and you'll get an `object_not_found` error even with a correct token.
- Grab the database ID from the URL: `notion.com/workspace/DATABASE_ID?v=...`

### 4. Candidate profile

Copy `CANDIDATE_PROFILE.txt`, fill in your own background — degree, experience, target roles, salary floor, whatever you want Gemini to filter against. Keep it out of the repo (it's gitignored already). This is the thing that actually drives the filtering logic, so the more specific, the better.

### 5. GitHub

Push this repo, then add these as repository secrets (`Settings → Secrets and variables → Actions`):

```
GMAIL_USER
GMAIL_APP_PASSWORD
GEMINI_API_KEY
NOTION_TOKEN
NOTION_DATABASE_ID
CANDIDATE_PROFILE
```

The workflow runs daily at 09:00 WIB. Trigger it manually from the Actions tab first to make sure everything's wired up correctly before waiting a full day to find out something's broken.

### 6. JobStreet

Set up a saved search with your keywords, turn on daily email alerts. That's the input this whole pipeline runs on.

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python job_filter.py
```

## A few things worth knowing

- Duplicate jobs get filtered before hitting Notion, based on a fuzzy match on title + company. Not perfect, but good enough.
- The `Link` field pulls whatever URL Gemini finds attached to a listing in the email HTML — sometimes it's a tracking/redirect link rather than a clean one, but it still lands you on the right posting.
- If Gemini's JSON response comes back malformed, the script retries a couple times before giving up on that email and moving to the next one. It won't crash the whole run over one bad email.
- The filtering criteria live in `FILTER_PROMPT` inside `job_filter.py`. If you're getting too many false positives or negatives, that's the first place to tune.

## Repo structure

```
job_filter.py                        main script
requirements.txt                     dependencies
.env.example                         local config template
.github/workflows/daily_job_filter.yml
SETUP.md                             longer step-by-step walkthrough
```

## Why the profile isn't in the code

Earlier version had the candidate profile hardcoded directly in the script — university, internship, research title, salary expectations, all of it sitting in plain text. Fine for a private repo, not fine if this ever goes public as a portfolio piece. It's now pulled from an environment variable instead, same pattern as the API keys.

---

Built this mostly to save myself from decision fatigue during a job search, not as a general-purpose tool. Your mileage adjusting `FILTER_PROMPT` for a different target role or country will vary.
