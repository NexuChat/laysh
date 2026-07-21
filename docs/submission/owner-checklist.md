# Owner-only release and submission checklist

The build session intentionally leaves every external account action unchecked.
Tagging, pushing, hosting, video upload, and submission happen only after
explicit owner approval; the build session does not perform them.

## Repository and demo

- [ ] Give explicit owner approval to promote the tested v1.1 release candidate.
- [ ] Create the public GitHub repository; do not initialize it with replacement files.
- [ ] Choose and create the final v1.1 release tag from the exact tested commit; do not reuse a rejected tag.
- [ ] Add that remote locally and push the default branch plus the owner-approved tag.
- [ ] Confirm the public repository shows README, MIT license, font notice, and dated commits.
- [ ] Start the owner-managed Cloudflare tunnel or stable host; keep it available through judging.
- [ ] Recheck the live demo (`https://laysh.mlki.app`) and public repository
  (`https://github.com/NexuChat/laysh`) immediately before the final push.
- [ ] Test the public demo in a fresh browser with no Laysh account or payment.

## Share-link retention

- [ ] Disclose that verified share links have a 30-day default retention window and expire automatically.
- [ ] Confirm judging links are still live before submission; regenerate an expired link instead of promising permanent hosting.

## Video

- [ ] Record the real product using `video-outline.md` and English voiceover/translation.
- [ ] Keep the final cut at or below 3:00 and remove unlicensed music or third-party marks.
- [ ] Upload the final video to YouTube as **Public**.
- [ ] Replace `FINAL-YOUTUBE-URL` in the field sheet.

## Devpost

- [ ] Join OpenAI Build Week with the eligible owner/team profile.
- [ ] Create/open the project and select exactly **Education**.
- [ ] Paste the final description and every URL from `fields.md`.
- [ ] Paste primary Session ID `019f7998-9378-72b2-b590-ee10e632ce81`.
- [ ] Confirm Codex collaboration, builder decisions, GPT-5.6 runtime use, and prior Fahim disclosure are visible.
- [ ] Submit before **2026-07-21 17:00 PDT / 2026-07-22 00:00 UTC**.
- [ ] Reopen the saved submission and verify links, video playback, track, text, and Session ID.
