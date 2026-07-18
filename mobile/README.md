# jobContext mobile (P1)

Desktop creates. Mobile captures. Cloud synchronizes.

P1 surface: **Career Inbox** (chronological feed of everything that changed,
served by `/api/events` off the sync journal), **share-sheet capture**
(share a job URL → imported, queued, assessed in the background → push
notification with the score), **push registration** (Expo push service —
no APNs/FCM console setup), **Settings** (cloud URL + API key from the
dashboard's API Keys tab, stored in the device keychain).

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

## Next (P2/P3)
Pipeline glance + contact cards, voice debrief (on-device transcription →
log_interview), interview mode with offline prep cache, widgets, business
card OCR. See the session design notes.
