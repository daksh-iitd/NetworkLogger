# Setting Up & Building NetworkLogger from Source Code

This guide is written for someone who has not used Android Studio recently. Every step is explained from scratch — no prior Android knowledge assumed.

**Estimated time:** 30–45 minutes (most of it is downloading)

---

## What You Will Need

- A Windows, Mac, or Linux laptop/desktop
- A stable internet connection (downloads are around 1–2 GB total)
- An Android phone (for running the app after building)
- A USB cable that supports data transfer (not just charging)

---

## Step 1 — Install Android Studio

Android Studio is the official tool for building Android apps. It includes everything needed — the editor, the build system, and the Android SDK.

1. Go to: **https://developer.android.com/studio**
2. Click the big **Download Android Studio** button
3. Run the downloaded installer
4. During installation, keep clicking **Next** and accept all default settings
5. When it asks about installing the Android SDK, say **Yes / Install**

> The first launch of Android Studio will download additional components. This can take 10–20 minutes depending on your internet speed. Let it complete before proceeding.

When you see this screen, the installation is done:

```
Welcome to Android Studio
```

---

## Step 2 — Get the Project Source Code

There are two ways to get the code:

### Option A — Download as ZIP (simpler)

1. Go to the project repository on GitHub
2. Click the green **Code** button
3. Click **Download ZIP**
4. Unzip the downloaded file to a folder on your desktop (e.g. `Desktop/NetworkLogger`)

### Option B — Clone using Git (if you have Git installed)

Open a terminal and run:
```bash
git clone <repository-url>
```

---

## Step 3 — Open the Project in Android Studio

1. Open Android Studio
2. Click **Open** (or **File → Open** if Android Studio is already open)
3. Navigate to the folder where you unzipped/cloned the project
4. Select the **NetworkLogger** folder (the one that contains the `app` folder inside it)
5. Click **OK**

Android Studio will now open the project. You will see a progress bar at the bottom that says **"Gradle sync in progress"** — this is Android Studio downloading the project's dependencies. Wait for it to finish.

> This sync can take 3–10 minutes the first time. You will see **"Gradle sync finished"** at the bottom when it is done.

---

## Step 4 — Set Up Your Android Phone

Your phone needs to be in **Developer Mode** so Android Studio can install the app on it.

### Enable Developer Mode on the phone

1. Open **Settings** on the phone
2. Go to **About Phone**
3. Find **Build Number** (it may be inside "Software Information" on some phones)
4. Tap **Build Number 7 times** in a row
5. You will see the message: **"You are now a developer!"**

### Enable USB Debugging

1. Go back to **Settings**
2. You will now see a new option called **Developer Options** (usually near the bottom of Settings)
3. Open **Developer Options**
4. Find **USB Debugging** and turn it **ON**
5. It will ask "Allow USB debugging?" — tap **OK**

### Connect phone to laptop

1. Connect the phone to your laptop using the USB cable
2. A popup may appear on the phone asking **"Allow USB debugging from this computer?"** — tap **Always allow** and then **OK**

---

## Step 5 — Verify Android Studio Sees Your Phone

In Android Studio, look at the top toolbar. There is a dropdown that shows the connected device.

It should now show your phone's name (e.g. **Realme RMX3241** or **Samsung Galaxy**) instead of **"No devices"**.

If it shows **"No devices"** even after plugging in:
- Try a different USB cable (some cables only charge and don't transfer data)
- Try a different USB port on the laptop
- Restart the phone and replug

---

## Step 6 — Build and Run the App

1. In Android Studio, click the **green triangle ▶ Run button** at the top (or press `Shift + F10`)
2. A dialog may appear asking which device to install on — select your phone and click **OK**
3. Android Studio will compile the code and install the app on your phone (takes 1–3 minutes)
4. The app will automatically open on your phone

---

## Step 7 — Grant Permissions on First Launch

When the app opens for the first time, it will ask for permissions one by one:

**1. Location permission**
- A dialog will appear: *"Allow NetworkLogger to access this device's location?"*
- Tap **Allow** (or "Allow only while using the app")
- This is needed to read cell tower data and GPS coordinates

**2. Phone permission**
- A dialog will appear: *"Allow NetworkLogger to make and manage phone calls?"*
- Despite the wording, this does **not** allow the app to make calls — this is Android's generic label for the "Phone" permission group
- The app only uses this to read network type and signal data
- Tap **Allow**

**3. Battery optimization**
- A dialog will appear asking to allow the app to run in the background
- Tap **Allow**
- This is needed so the background logging keeps working even when the phone screen is off

---

## Step 8 — Additional Phone Settings (Important)

These steps ensure the background logging works correctly and does not get stopped by the phone:

1. Go to **Settings → Apps → NetworkLogger → Battery**
2. Select **No Restrictions** (or "Unrestricted")

If your phone has an **Autostart** option (common on Realme, Xiaomi, OPPO phones):
1. Search **"Autostart"** in Settings
2. Find **NetworkLogger** and turn it **ON**

> Without these settings, some phones stop background apps when the battery drops below 20%, which can interrupt background logging.

---

## Step 9 — Using the App

Once the app is open and permissions are granted:

**To start logging:**
- Tap the green **START LOGGING** button
- The app will begin recording network data every 5 seconds
- You will see the logging duration timer counting up

**To stop logging:**
- Tap the red **STOP LOGGING** button
- The screen will show how long logging ran

**To find the recorded data:**
- Open the **Files** app on the phone
- Go to **Downloads**
- You will find two files:
    - `network_logs.csv` — cell tower and GPS data (recorded while logging was active)
    - `background_logs.csv` — battery, RAM, storage, network data (recorded automatically every 15 minutes)

**To open the CSV files on a laptop:**
- Connect phone to laptop
- Copy the files from the phone's Downloads folder to your laptop
- Open in Microsoft Excel, Google Sheets, or any text editor

---

## What the App Shows on Screen

| Field | What it means |
|-------|--------------|
| **Location** | GPS coordinates (latitude, longitude) |
| **Network** | Current network type — 4G, 5G, etc. |
| **Signal** | Signal strength label (Very Weak to Very Strong) |
| **Cell Tower Info** | Technical parameters of the connected cell tower |
| **DURATION** | How long logging has been running (HH:MM:SS) |
| **DEVICE** | Whether the phone is Rooted or Non-Rooted |
| **File paths** | Where the CSV files are being saved on the phone |

---

## Troubleshooting

### "Gradle sync failed" when opening the project

This usually means a dependency could not be downloaded.

- Check your internet connection
- In Android Studio: **File → Invalidate Caches → Invalidate and Restart**
- After restart, let the sync run again

---

### Phone not appearing in Android Studio

- Make sure USB Debugging is enabled (Step 4)
- Try a different USB cable
- Try unplugging and replugging
- On the phone, if a popup appears asking about the USB connection type, select **File Transfer** (not "Charging only")
- Restart Android Studio

---

### App installs but crashes immediately on opening

- Make sure all permissions were granted (Step 7)
- Uninstall the app from the phone, then click Run ▶ again in Android Studio
- Check the **Logcat** tab at the bottom of Android Studio — filter by the word `fatal` to see the exact error

---

### "Cell Info: Not Available" shown on screen

This is normal and temporary. The phone's modem refreshes cell tower data every few seconds. The app will automatically show real data within one cycle (5 seconds). It does not affect what is saved in the CSV file.

---

### Background_logs.csv has very few rows

The background worker runs every 15 minutes automatically. If you only ran the app for a short time, there will only be 1–2 rows. Leave the phone running for an hour to see multiple rows.

If the phone's battery drops below approximately 20%, some phones stop all background tasks regardless of settings. This is a phone OS restriction, not an app bug.

---

## Generating a Signed APK (to install without Android Studio)

If you want to share the app as an APK file that can be installed directly on any Android phone without needing Android Studio:

1. In Android Studio: **Build → Generate Signed Bundle / APK**
2. Select **APK** and click **Next**
3. If you don't have a keystore yet, click **Create new** and fill in any details
4. Keep note of the keystore file location and password
5. Select **release** build variant and click **Finish**
6. The APK will be generated at: `app/release/app-release.apk`
7. Transfer this file to any Android phone and open it to install

> To install an APK directly, the phone needs **"Install unknown apps"** or **"Install from unknown sources"** enabled in Settings.

---

## Quick Reference — Key Folders

| Folder / File | What's inside |
|--------------|--------------|
| `app/src/main/java/.../MainActivity.kt` | Main screen logic, GPS, cell tower reading, root detection |
| `app/src/main/java/.../NetworkWorker.kt` | Background worker — battery, RAM, storage, network |
| `app/src/main/res/layout/activity_main.xml` | The UI layout of the app screen |
| `app/src/main/AndroidManifest.xml` | App permissions and configuration |
| `app/build.gradle.kts` | Project dependencies and SDK versions |

---

Feel free to ping if you get stuck at any step — happy to help.