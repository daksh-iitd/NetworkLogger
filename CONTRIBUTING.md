# Contributing to NetworkLogger

Thank you for your interest in contributing. Please read this guide before submitting changes.

---

## Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Test on a physical Android device (emulators do not return real cell data)
5. Submit a Pull Request with a clear description

---

## Branch Naming

| Type | Format | Example |
|------|--------|---------|
| Feature | `feature/description` | `feature/coverage-heatmap` |
| Bug fix | `fix/description` | `fix/duplicate-csv-files` |
| Documentation | `docs/description` | `docs/update-api-list` |

---

## Code Guidelines

- Language: **Kotlin only**
- Follow existing code style and naming conventions
- Wrap all telephony and file operations in try-catch
- Never use `IS_PENDING = 1` in MediaStore operations — this was the cause of a major bug
- Always test background changes on a release APK, not just debug mode
- Add `Log.d()` statements with meaningful tags for any new functionality

---

## Testing Requirements

Before submitting a Pull Request, test on:

- At least one non-rooted device
- Both Android 12 (API 31) or below AND Android 13/14 (API 33/34) if your change touches signal listening or foreground service code

---

## What Not to Do

- Do not add `IS_PENDING = 1` to MediaStore file creation — causes duplicate files
- Do not use `telephonyManager.listen()` without the `@Suppress("DEPRECATION")` annotation
- Do not use `catch (e: Exception)` for foreground service calls on Android 14 — use `catch (t: Throwable)` instead
- Do not test only on emulators — `allCellInfo` always returns empty on emulators

---

## Reporting Bugs

Open an issue with:
- Device model and Android version
- Steps to reproduce
- Expected vs actual behaviour
- Logcat output filtered by `CSV`, `NetworkWorker`, or `CellInfo` tag