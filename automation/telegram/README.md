# EasyVOD Telegram publishing

This publisher announces verified stable releases in [@EasyVOD](https://t.me/EasyVOD)
and refreshes the pinned installation guide. It runs in GitHub Actions after a
release is **published**. Drafts and prereleases are ignored. It needs no running
desktop session, AI agent, webhook or message-polling process.

The destination is fixed in code and checked against Telegram before publishing.
The publisher never polls messages or sends private messages. The user-account
Telegram session is not uploaded to GitHub.

## Configuration

- Repository Actions secret: `TELEGRAM_BOT_TOKEN` for `@EasyVODUpdatesBot`.
- Channel and pinned post: `channel.json`.
- Announcement history and reservations: `state.json`.
- Workflow: `.github/workflows/telegram.yml`.

The bot needs **Post Messages** and **Edit Messages** in the EasyVOD channel.
Editing permission also permits channel pins. It does not need permission to
delete messages, ban users, invite people, change the channel or add admins.

## Behavior

1. Select the latest published stable release and reject an obsolete release event.
2. Check `latest.json`, its application/version and exact APK URL.
3. Download both APK assets and verify their sizes and SHA-256 hashes.
4. Reserve the announcement in `state.json` using GitHub's content SHA as a lease.
5. Post the separate one-line Hebrew summary (`notesTelegram`, up to 240 characters) with APK, installation and release details buttons. The release details button opens the full changelog on GitHub. Older releases without a summary display the title and buttons.
6. Save the Telegram message ID, update the welcome post's version, and keep it pinned.

The welcome post covers Android installation, Android TV / Google TV setup using
Downloader code **9977511**, in-app updates, English instructions and support.
The download link always points to the latest stable APK. Announcement buttons
point to their own immutable versioned APK.

## Verification and manual runs

```bash
python3 -m unittest discover -s automation/telegram -p 'test_*.py' -v
python3 automation/telegram/publish.py --tag v0.18.4 --dry-run
gh workflow run telegram.yml --repo nirz8/EasyVOD-updates -f tag=v0.18.4
```

The dry run verifies GitHub assets and renders the messages without contacting
Telegram or changing announcement state. The workflow can be dispatched again
to repair the pinned guide; a recorded announcement is not posted twice.

The workflow needs `contents: write` only in its publishing job to maintain its
state. Pull-request and push checks have read-only permissions and no bot secret.
Its GitHub-token state commits do not recursively trigger another workflow.

## Interrupted publication

Telegram does not provide an idempotency key for `sendMessage`. If the process
loses the response after Telegram accepted a post, automatically retrying could
duplicate the announcement. A `pending` record therefore blocks another send.

Check the EasyVOD channel and the workflow log's `announcement_message_id` first.
If the post exists, change that release record to `status: "sent"` and record its
verified `message_id`, keeping the release identity/version unchanged, then rerun.
If no post exists, confirm the original job has stopped before removing only that
release's pending entry and rerunning. Never reset pending state blindly.

Changing the channel branding or bot profile is a one-time administrative action;
the release workflow does not alter either profile or read channel history.
