> For agents running the skill. People: read [docs/outreach.md](../../docs/outreach.md) instead.

# Outreach help (only when the founder asks)

Read this when the founder asks for help with a customer test: an audience card, message drafts or a prospect list. Mission Control gives them prompts that ask for exactly these. Do none of it on your own initiative.

Everything goes in `research/greenfield/<slug>/outreach/<experiment>/`, where `<experiment>` is the experiment id from `evaluation.json` (for example `EXP-1`). Mission Control ticks a room when its file exists.

## What you may write

- **`audience.md`**: a one-page audience card built from the findings already in the run. Name one narrow segment, where those people can be reached, and what rules someone out. Cite the claims it rests on. Do not invent a segment the research does not support.
- **`messages.md`**: three variants of what the founder will send. Each is under 90 words, makes one ask, and ends with a plain way to opt out. Claim nothing about the product that the research does not support, and promise nothing that does not exist yet.
- **`prospects.csv`**: people who fit `audience.md`, found on public pages. Columns, in this order: `id, name, role, company, source_url, contact`. Give each row a short id (`P001`). `source_url` is the public page the row came from; a row without one does not go in. Tell the founder before you write the first row that this file holds personal data and that you have to read it to work on it.

## What you never do

- Never send a message, post, fill in a web form, sign up for a service or create an account.
- Never write `log.csv`. The founder keeps it, because it records what really happened.
- Never write to `materials/` or run `greenfield evidence add`: recording a result is the founder's step.
- Never take contact details from behind a login, a paywall or a page that forbids collection.
- Never count a draft, a list or your own estimate as a result. Evidence levels do not move until a person records a receipt.

## What the founder does

The founder reads and approves every message, sends from their own mailbox, and keeps `log.csv` with the columns `id, sent_on, variant, replied, result`. It refers to people by `id` only and has `yes` under `result` for each person who did what the test counts. Because it holds no contact details, it can be recorded as the receipt. Print the command for the founder to run in their own terminal; do not run it:

```bash
# the founder runs this in their own terminal
greenfield evidence add research/greenfield/<slug>/outreach/EXP-1/log.csv --as signups --pillar problem --experiment EXP-1 --result pass --consent own_data --attester "<the founder's name>"
```

If the founder asks about sending limits or the law, point them to `docs/outreach.md`. Give no legal advice.
