# Running a customer test: the outreach folder

A verdict of **Validate before build** means the next step is a test with real people. Mission Control shows each test as five rooms. This page says what is behind them, what your assistant will and will not do, and how to send without hurting your email reputation.

The tool never sends anything. It has no mail integration and makes no request on your behalf. Your assistant can draft and research when you ask; you read, approve and send.

## The folder

Each test has a folder inside your run, `research/greenfield/<slug>/outreach/<experiment>/`, where `<experiment>` is the id from `greenfield plan` (for example `EXP-1`). The run folder is git-ignored.

| Room | File | Who writes it |
| --- | --- | --- |
| Who | `audience.md`: one narrow group, where to reach them, who to rule out | Your assistant, from the research in the run |
| What to say | `messages.md`: three short variants | Your assistant drafts, you edit and approve |
| Find people | `prospects.csv`: `id, name, role, company, source_url, contact` | Your assistant from public pages, or your own list |
| Send and track | `log.csv`: `id, sent_on, variant, replied, result` | You |
| Record result | the receipt in the ledger | You, with `greenfield evidence add` |

Each room in Mission Control gives you a prompt to paste or a command to copy. A room is ticked when its file exists.

## Personal data

- **`prospects.csv` holds personal data**: names and contact details taken from public pages. Keep it in the run folder, share it with nobody, and delete the file when the test is over. `greenfield doctor` lists any it finds.
- **Your assistant reads it.** To build or use the list, the assistant has to read the file, so its contents reach your AI provider. If that is not acceptable, build the list yourself and do not ask the assistant to open it.
- **`log.csv` holds no contact details.** It names people by `id` only. That is what lets you record it as the receipt. `greenfield evidence status` warns if an email or a phone number turns up in it.

## Rules for cold messages

Mission Control shows these beside the message and sending rooms.

1. **You read and approve every message** before it goes.
2. **Send from your own mailbox, a few a day.** There is no published safe number for a new sender, so start low and raise it only while nobody complains. The pace calculator in the page does the arithmetic for the number you choose.
3. **Authenticate your domain.** Gmail and Yahoo require SPF or DKIM from every sender. Above 5,000 messages a day to Gmail accounts, Gmail also requires both, plus DMARC and one-click unsubscribe. A test of 300 people is far below that, but the first rule applies to you.
4. **Give a plain way to opt out, and honour it.** Yahoo asks senders to honour unsubscribes within 2 days. A reply of "no thanks" is enough at this size; keep a note in `log.csv` and do not write again.
5. **Stop if people complain.** Gmail and Yahoo both expect spam reports to stay under 0.3% of messages, and Gmail recommends staying under 0.1%. At 300 messages a single report is already over 0.3%.
6. **Check the law where you and your recipients are.** In the United States that is CAN-SPAM; in the EU and the UK, GDPR and the e-privacy rules. This page is not legal advice.

Sources, read on 2026-11-10: Google, [Email sender guidelines](https://support.google.com/a/answer/81126); Yahoo, [Sender best practices](https://senders.yahooinc.com/best-practices/).

Email is not always the right channel. If your buyers are local businesses or consumers, the same rooms apply to a visit, a call or a post in a group you already belong to: log each person by id in the same way.

## Recording the result

When the test is over, judge it against the pass mark you set before you started, and do not change the mark afterwards. The Record result room shows the exact `greenfield evidence add` command for your test. You run it in your own terminal and type the confirmation code; your assistant cannot. See [evidence and the ledger](evidence.md) for why.

## Sending more than a few hundred

`prospects.csv` and `messages.md` are everything a sending service needs: import the list, paste the variant you approved, and export the results back into `log.csv` by id. Greenfield has no integration with any service and does not need one.
