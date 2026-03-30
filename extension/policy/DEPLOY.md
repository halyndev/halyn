# Halyn Extension — Enterprise Policy Deployment

## What this does
Forces Chrome to install the Halyn audit extension and prevents users
(or AI agents) from disabling or removing it.

## Before deploying
Replace `EXTENSION_ID` with the actual Chrome Web Store ID of the
published extension. Until the extension is published, use the unpacked
extension ID from `chrome://extensions` (developer mode).

---

## Linux (Chrome / Chromium)

```bash
sudo mkdir -p /etc/opt/chrome/policies/managed/
sudo cp policy/linux/halyn.json /etc/opt/chrome/policies/managed/halyn.json
sudo chmod 644 /etc/opt/chrome/policies/managed/halyn.json
```

Verify: `chrome://policy` — look for `ExtensionInstallForcelist`

---

## macOS

```bash
sudo mkdir -p /Library/Managed\ Preferences/
sudo cp policy/macos/com.google.Chrome.plist /Library/Managed\ Preferences/
```

---

## Windows (Group Policy / Registry)

```powershell
# Run as Administrator
reg add "HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist" `
  /v 1 /t REG_SZ /d "EXTENSION_ID;https://clients2.google.com/service/update2/crx" /f

reg add "HKLM\SOFTWARE\Policies\Google\Chrome\ExtensionSettings\EXTENSION_ID" `
  /v "installation_mode" /t REG_SZ /d "force_installed" /f
```

Or apply via Group Policy Object (GPO):
`Computer Configuration > Administrative Templates > Google Chrome > Extensions`

---

## Verify (any OS)

1. Open Chrome
2. Navigate to `chrome://policy`
3. Confirm `ExtensionInstallForcelist` contains the Halyn extension ID
4. Navigate to `chrome://extensions`
5. Halyn extension should appear with "Installed by enterprise policy" label
   and no remove button

---

## Security guarantees

- Agent cannot call `chrome.management.uninstall()` on a force-installed extension
- Agent cannot disable it via `chrome.management.setEnabled(false, ...)`
- Policy is applied at OS level — requires admin to modify
- Content script runs at `document_start` — before any page JS executes
