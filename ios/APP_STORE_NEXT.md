# App Store — your next clicks (after Developer enrollment)

Project is prepared for signing:

| Setting | Value |
|---------|--------|
| Bundle ID | `com.shreyas2692.sleeptracker` |
| Version | `1.0.0` (build `1`) |
| Signing | Automatic |
| HealthKit | On (entitlements) |
| Encryption flag | Non-exempt encryption = **No** |

---

## A. Xcode account (2 minutes)

1. Open **Xcode → Settings… → Accounts**
2. **+** → **Apple ID** → sign in with the ID that has Developer Program
3. Select the account → confirm a **Team** appears (Personal Team is *not* enough for App Store; you need the paid program team)

---

## B. Fix signing on the target (3 minutes)

```bash
cd ios
xcodegen generate
open "Sleep Tracker.xcodeproj"
```

1. Left sidebar → **Sleep Tracker** (blue project) → target **Sleep Tracker**
2. **Signing & Capabilities**
3. ☑ **Automatically manage signing**
4. **Team** → pick your **paid** developer team  
5. Confirm Bundle Identifier is `com.shreyas2692.sleeptracker`
6. Capability **HealthKit** should already show (from entitlements). If Xcode offers to add it, accept.

If you see a red error about the App ID:

- Xcode usually creates it for you when you pick the Team  
- Or create manually: [developer.apple.com → Identifiers](https://developer.apple.com/account/resources/identifiers/list) → App IDs → + → bundle ID + enable HealthKit

---

## C. Run on a real iPhone (optional but smart)

1. Plug in iPhone → Trust computer  
2. Scheme device = your iPhone  
3. **⌘R**  
4. On phone: Settings → General → VPN & Device Management → trust your developer cert if asked  
5. Enter Render password on Connect sheet; try Health sync

---

## D. App Store Connect app record

1. https://appstoreconnect.apple.com → **My Apps** → **+**
2. **New App**
   - Platform: iOS  
   - Name: Sleep Tracker (or unique if taken)  
   - Primary language: English (U.S.)  
   - Bundle ID: `com.shreyas2692.sleeptracker`  
   - SKU: `sleeptracker-ios-1`  
3. Fill screenshots from `docs/app-store/screenshots/`  
4. Privacy Policy URL (host the draft in `docs/app-store/PRIVACY_POLICY_DRAFT.md`)  
5. App Privacy questionnaire (Health data, app functionality, not tracking)

Copy text from `docs/app-store/APP_STORE_PLAN.md` and review notes from `docs/app-store/APP_REVIEW_NOTES.md`.

---

## E. Archive & upload

1. Xcode scheme destination: **Any iOS Device (arm64)** — *not* a simulator  
2. **Product → Archive**  
3. Organizer window → **Distribute App** → **App Store Connect** → Upload  
4. Wait for email “Finished processing”  
5. App Store Connect → TestFlight → install on your phone  
6. When happy: **Add for Review** → Submit  

Bump `CURRENT_PROJECT_VERSION` in `project.yml` for every new upload (2, 3, …).

---

## F. Common errors

| Message | Fix |
|---------|-----|
| No accounts / No teams | Xcode Settings → Accounts → re-add Apple ID |
| Failed to register bundle ID | Bundle ID already taken → change in `project.yml` |
| Requires a development team | Select Team under Signing & Capabilities |
| HealthKit capability missing | Add capability or re-check entitlements file |
| Invalid binary / encryption | `ITSAppUsesNonExemptEncryption` is already false |

---

## G. Optional: lock Team ID into the project

After Xcode shows your Team ID (10 characters):

```yaml
# ios/project.yml → settings.base
DEVELOPMENT_TEAM: YOURTEAMID
```

Then `xcodegen generate` so CLI archives work without clicking Team each time.
