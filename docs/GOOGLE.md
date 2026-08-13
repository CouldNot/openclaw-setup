# Google authorization

Enable the Gmail API and Google Calendar API in the OAuth client's Google Cloud project. Install the OAuth desktop-client JSON locally; never add it to this repository.

For each account, request Gmail read-only plus Calendar read/write:

```bash
gog auth add ACCOUNT_EMAIL \
  --services gmail,calendar \
  --gmail-scope readonly \
  --extra-scopes=https://www.googleapis.com/auth/calendar \
  --force-consent --remote --step 1
```

Open the generated URL, approve access, then exchange the complete localhost callback URL with the matching `--remote --step 2 --auth-url=...` command.

Verify without writing an event:

```bash
gog calendar calendars --account ACCOUNT_EMAIL --json --no-input
gog gmail search newer_than:1d --account ACCOUNT_EMAIL --max 1 --json --no-input
```

OAuth refresh tokens are stored only in the local credential/keyring backend.
