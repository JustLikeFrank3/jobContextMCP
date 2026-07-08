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
npx eas login                                   # once
npx eas build --profile development --platform ios    # dev build → your iPhone (share sheet + push work)
npx eas build --profile preview --platform android    # installable APK link → the Windows/Android tester
npx eas build --platform ios && npx eas submit -p ios # TestFlight
```

Sign in with Microsoft inside the app (Settings tab) — it self-registers
against the cloud's OAuth proxy; the API-key field under "Advanced" is a
fallback.

## Next (P2/P3)
Pipeline glance + contact cards, voice debrief (on-device transcription →
log_interview), interview mode with offline prep cache, widgets, business
card OCR. See the session design notes.
