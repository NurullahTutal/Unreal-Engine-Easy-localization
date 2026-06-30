# Unreal Engine Easy Localization (.po & .archive)

A batch localization tool with a modern web interface designed specifically for Unreal Engine. It automates the translation of standard `.po` files and Unreal Engine's native `.archive` (UTF-16LE JSON) files using free translation providers.

## 🚀 Features

- 📂 **Dual Format Support:** Automatically detects and translates both UE native `.archive` files and exported `.po` files.
- 🌍 **30+ Languages:** Supports translation between English, Turkish, German, French, Spanish, Chinese, Japanese, Korean, Russian, Arabic, and more.
- 🤖 **Smart Language Mapping:** Automatically extracts culture/language codes directly from Unreal Engine's folder hierarchy (e.g., `Content/Localization/Target/CultureCode/`).
- ⚡ **Free Translation Providers:**
  - **MyMemory API** (Completely free, no registration or API keys needed).
  - **LibreTranslate API** (Support for self-hosted instances or public API keys).
- 🛡️ **Safety & Control:**
  - Auto-generated backup files (`.bak-*`) before modifying any assets.
  - Smart logic to skip technical non-game strings (e.g., hash keys, metadata) using regex verification.
  - Adjustable delays between requests to prevent temporary API rate limits (IP blocks).
- 📈 **Real-Time Progress Tracking:** Shows a live progress bar, completion percentage, active file status, and output logs.

---

## 🛠️ Setup and Running

1. Download or clone this repository.
2. Double-click the **`Start.bat`** file or run the following command in your terminal:
   ```bash
   python app.py
   ```
3. Open the web interface in your browser:
   ```
   http://127.0.0.1:8766/
   ```

---

## 📖 How to Use / Step-by-Step Guide

### 1. Preparation in Unreal Engine
Before running the tool, ensure you have generated your localization directory:
- Open the **Localization Dashboard** in the Unreal Editor.
- Choose your localization target (usually `Game`), click **Gather Text** to harvest all strings from assets/code.
- Add target cultures (e.g. German, French, Japanese).
- Click **Export Text** if you prefer to translate `.po` files, or just run the default pipeline so that `.archive` files are generated under `Content/Localization/Game/{CultureCode}/`.

### 2. Scanning Folders
- Copy the absolute path of your `Content/Localization` directory (or a target directory like `Content/Localization/Game`).
- Paste it into the path input field on the web UI and click **Scan Folder**.
- The tool will scan all subdirectories, detect the format, map the corresponding target languages, and display them.

### 3. Translation and Progress Tracking
- Select your **Source Language** (e.g. English) and adjust the **Delay** (we recommend at least `500ms` for MyMemory to avoid rate limits).
- Click **Translate & Save All**.
- The progress bar at the top will animate, showing the overall percentage and the current file being translated.
- Live logs will update at the bottom showing successful translations or any API warnings.

### 4. Compile in Unreal Engine
- Once the translation is complete, go back to the Unreal Editor's **Localization Dashboard**.
- Click **Import Text** (if you processed `.po` files).
- Click **Compile Text**. **This step is mandatory** because Unreal Engine compiles the translated `.po`/`.archive` files into binary `.locres` files, which are the only files read by the engine at runtime.
