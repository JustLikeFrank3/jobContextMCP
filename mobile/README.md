# jobContext mobile

Desktop creates. Mobile captures. Cloud synchronizes.

Expo (SDK 57 / React Native 0.86) companion app. Current surface:

- **Tabs**: Home (today view + activity), Pipeline, Interviews, People, Posts, Wellbeing — each with drill-in detail screens (job, interview, person, company, post, check-in), plus Search, Timeline, Activity feed, and Settings.
- **Share-sheet capture** — share a job URL from any app; the page is extracted **on-device** (`src/pageExtract.ts`, the phone can read pages that authwall datacenter IPs), then imported, queued, and assessed in the background via the server's durable `capture_url` work item → push notification with the score. Server-side scrape is the fallback.
- **Career Inbox / Activity** — chronological feed of everything that changed, served by `/api/events` off the sync journal.
- **Push** — Expo push service, no APNs/FCM console setup.
- **Settings** — cloud URL + API key (create it in the dashboard's API Keys tab), stored in the device keychain.
- **OTA updates** — EAS Update channels on the preview/production build profiles.

## Run it

```bash
cd mobile && npm install
npx expo start          # QR code → Expo Go on the iPhone (inbox + settings work)
```

Share-sheet capture and remote push need a dev build (Expo Go can't host
extensions):

```bash
npx eas build --profile development --platform ios      # install on iPhone
npx eas build --profile preview --platform android      # APK for the tester
```

TestFlight when ready: `npx eas build --platform ios && npx eas submit`.

## Ship it

```bash
npx eas-cli login                               # once (expo doctor forbids eas-cli as a project dep — npx eas-cli needs no install)
npx eas-cli build --profile development --platform ios   # dev build → your iPhone (share sheet + push work)
npx eas-cli build --profile preview --platform android   # installable APK link → the Windows/Android tester
npx eas-cli build --platform ios && npx eas-cli submit -p ios  # TestFlight
```

Add your API key inside the app (Settings tab) — create it from the dashboard's
API Keys tab first, then paste it in. No sign-in flow: a static key has no
inactivity expiry to trip over while the app sits unopened.

## Next
Voice debrief (on-device transcription → interview log), interview mode with
offline prep cache, widgets, business card OCR. See the session design notes.
