from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import ast
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request


PORT = 8766
ROOT = Path(__file__).resolve().parent


LANG_NAMES = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "es-419": "Spanish (Latin America)",
    "fi": "Finnish",
    "fr": "French",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pt-BR": "Portuguese (Brazil)",
    "ro": "Romanian",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
}


def normalize_lang_code(code):
    """Normalize a UE culture code to a short language code for translation APIs.
    e.g. 'zh-Hans' -> 'zh', 'pt-BR' -> 'pt', 'en' -> 'en'
    """
    if not code:
        return ""
    # Keep exact code if it's in our lang names (e.g. zh-Hans, pt-BR)
    if code in LANG_NAMES:
        return code
    # Otherwise take the base language part
    base = code.split("-")[0].split("_")[0].lower()
    return base if base in LANG_NAMES else code


class PoToken:
    def __init__(self, key, start_line, value):
        self.key = key
        self.start_line = start_line
        self.end_line = start_line
        self.values = [value]

    @property
    def text(self):
        return "".join(self.values)


class PoEntry:
    def __init__(self, start_line):
        self.start_line = start_line
        self.end_line = start_line
        self.msgid = None
        self.msgid_plural = None
        self.msgstr = None
        self.msgstrs = []


def read_po_string(raw):
    raw = raw.strip()
    if not raw.startswith('"'):
        return ""
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def format_po_string(value):
    value = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{value}"'


def parse_po(text):
    lines = text.splitlines()
    entries = []
    entry = None
    active = None

    def finish():
        nonlocal entry, active
        if entry and entry.msgid and entry.msgstr:
            entries.append(entry)
        entry = None
        active = None

    for index, line in enumerate(lines):
        if line.strip() == "":
            finish()
            continue

        if entry is None:
            entry = PoEntry(index)

        entry.end_line = index

        if line.startswith("#"):
            continue

        match = re.match(r"^(msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+(.*)$", line)
        if match:
            key = match.group(1)
            token = PoToken(key, index, read_po_string(match.group(2)))

            if key == "msgid":
                entry.msgid = token
            elif key == "msgid_plural":
                entry.msgid_plural = token
            elif key.startswith("msgstr"):
                entry.msgstrs.append(token)
                if entry.msgstr is None:
                    entry.msgstr = token

            active = token
            continue

        if active and re.match(r'^\s*".*"\s*$', line):
            active.values.append(read_po_string(line.strip()))
            active.end_line = index

    finish()
    return entries


def looks_like_game_text(text):
    trimmed = text.strip()
    if not trimmed:
        return False
    if not re.search(r"\s", trimmed) and re.search(r"[./:_]", trimmed):
        return False
    if not re.search(r"\s", trimmed) and re.match(r"^[A-F0-9]{16,}$", trimmed):
        return False
    if re.match(r"^\{[^}\s]+\}$", trimmed):
        return False
    if trimmed.startswith("NSLOCTEXT("):
        return False
    return bool(re.search(r"[A-Za-z0-9]", trimmed))


def should_translate(entry, overwrite=False, skip_tagged=True):
    msgid = entry.msgid.text if entry.msgid else ""
    msgstr = entry.msgstr.text if entry.msgstr else ""
    if not msgid.strip():
        return False
    if entry.msgid_plural or len(entry.msgstrs) > 1:
        return False
    if not overwrite and msgstr.strip():
        return False
    if skip_tagged and not looks_like_game_text(msgid):
        return False
    return True


def detect_newline(text):
    return "\r\n" if "\r\n" in text else "\n"


def detect_language(text, path):
    """Detect language for a .po file.

    UE Localization folder structure:
      Content/Localization/{TargetName}/{CultureCode}/{TargetName}.po

    The immediate parent directory of the .po file IS the culture/language code.
    We prioritize this over the PO header because the header is not always present
    or may be generic.
    """
    # Strategy 1: The parent directory of the .po file is the culture code in UE.
    # This is the most reliable method for UE projects.
    parent_name = path.parent.name
    if parent_name:
        # Try exact match first (handles zh-Hans, pt-BR, es-419 etc.)
        if parent_name in LANG_NAMES:
            return parent_name
        # Try normalized (lowercase, base code)
        normalized = parent_name.split("-")[0].split("_")[0].lower()
        if normalized in LANG_NAMES:
            return normalized

    # Strategy 2: Parse the Language header from the PO file itself
    match = re.search(r'"Language:\s*([A-Za-z0-9_-]+)\\n"', text)
    if match:
        lang_header = match.group(1)
        if lang_header in LANG_NAMES:
            return lang_header
        base = lang_header.split("-")[0].split("_")[0].lower()
        if base in LANG_NAMES:
            return base

    return ""


def read_text(path):
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    return data.decode("utf-8", errors="replace"), "utf-8"


def read_archive(path):
    """Read a UE .archive file. These are JSON encoded as UTF-16LE."""
    data = path.read_bytes()
    # UTF-16 with BOM
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16")
    # UTF-16LE without BOM (starts with ASCII char + 0x00)
    elif len(data) >= 2 and data[1:2] == b"\x00":
        text = data.decode("utf-16-le")
    # UTF-8 with BOM
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig")
    else:
        text = data.decode("utf-8")
    return json.loads(text)


def detect_archive_encoding(path):
    """Detect the encoding of an archive file for write-back."""
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le-bom"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be-bom"
    if len(data) >= 2 and data[1:2] == b"\x00":
        return "utf-16-le"
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def write_archive(path, archive_data, original_encoding):
    """Write archive JSON back preserving original encoding."""
    output = json.dumps(archive_data, ensure_ascii=False, indent="\t")
    # UE uses \r\n on Windows
    output = output.replace("\n", "\r\n") + "\r\n"
    if original_encoding == "utf-16-le-bom":
        path.write_bytes(b"\xff\xfe" + output.encode("utf-16-le"))
    elif original_encoding == "utf-16-be-bom":
        path.write_bytes(b"\xfe\xff" + output.encode("utf-16-be"))
    elif original_encoding == "utf-16-le":
        path.write_bytes(output.encode("utf-16-le"))
    elif original_encoding == "utf-8-sig":
        path.write_text(output, encoding="utf-8-sig")
    else:
        path.write_text(output, encoding="utf-8")


def collect_archive_entries(node, namespace=""):
    """Recursively collect all translatable entries from archive JSON.
    UE archive can have nested Namespace/Children structures."""
    entries = []
    ns = node.get("Namespace", namespace)
    for child in node.get("Children", []):
        if "Source" in child and "Key" in child:
            entries.append({
                "source": child["Source"].get("Text", ""),
                "translation": child.get("Translation", {}).get("Text", ""),
                "node": child,
            })
        elif "Children" in child:
            entries.extend(collect_archive_entries(child, child.get("Namespace", ns)))
    return entries


def scan_archive_files(root_path, source_lang, overwrite=False, skip_tagged=True):
    """Scan .archive files under a UE Localization folder."""
    files = []
    totals = {"files": 0, "entries": 0, "todo": 0, "languages": 0}
    languages = set()

    for path in sorted(root_path.rglob("*.archive")):
        if ".bak-" in path.name:
            continue
        language = detect_language("", path)
        try:
            archive_data = read_archive(path)
            entries = collect_archive_entries(archive_data)
        except Exception:
            continue

        if language == source_lang:
            todo = 0
        else:
            todo = sum(
                1
                for e in entries
                if e["source"].strip()
                and (overwrite or not e["translation"].strip())
                and (not skip_tagged or looks_like_game_text(e["source"]))
            )

        files.append(
            {
                "path": str(path),
                "relative": str(path.relative_to(root_path)),
                "language": language,
                "languageName": LANG_NAMES.get(language, language or "Unknown"),
                "entries": len(entries),
                "todo": todo,
                "format": "archive",
            }
        )
        totals["files"] += 1
        totals["entries"] += len(entries)
        totals["todo"] += todo
        if language:
            languages.add(language)

    totals["languages"] = len(languages)
    return {"root": str(root_path), "files": files, "totals": totals, "format": "archive"}


def scan_po_files_only(root_path, overwrite=False, skip_tagged=True):
    """Scan .po files under a directory."""
    files = []
    totals = {"files": 0, "entries": 0, "todo": 0, "languages": 0}
    languages = set()

    for path in sorted(root_path.rglob("*.po")):
        if ".bak-" in path.name:
            continue
        text, _encoding = read_text(path)
        entries = parse_po(text)
        language = detect_language(text, path)
        todo = sum(1 for entry in entries if should_translate(entry, overwrite, skip_tagged))
        files.append(
            {
                "path": str(path),
                "relative": str(path.relative_to(root_path)),
                "language": language,
                "languageName": LANG_NAMES.get(language, language or "Unknown"),
                "entries": len(entries),
                "todo": todo,
                "format": "po",
            }
        )
        totals["files"] += 1
        totals["entries"] += len(entries)
        totals["todo"] += todo
        if language:
            languages.add(language)

    totals["languages"] = len(languages)
    return {"root": str(root_path), "files": files, "totals": totals, "format": "po"}


def scan_files(root, source_lang="en", overwrite=False, skip_tagged=True):
    """Scan for localization files. Tries .archive first, falls back to .po."""
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise ValueError("Directory not found.")
    if not root_path.is_dir():
        raise ValueError("You must provide a folder path.")

    # Try .archive first (UE native format)
    result = scan_archive_files(root_path, source_lang, overwrite, skip_tagged)
    if result["files"]:
        return result

    # Fall back to .po
    result = scan_po_files_only(root_path, overwrite, skip_tagged)
    if result["files"]:
        return result

    # Nothing found
    return {"root": str(root_path), "files": [], "totals": {"files": 0, "entries": 0, "todo": 0, "languages": 0}, "format": "none"}


GLOBAL_CACHE = {}


def translate_mymemory(text, source_lang, target_lang):
    params = urllib.parse.urlencode({"q": text, "langpair": f"{source_lang}|{target_lang}"})
    request = urllib.request.Request(
        f"https://api.mymemory.translated.net/get?{params}",
        headers={"User-Agent": "UE-PO-Localizer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    translated = data.get("responseData", {}).get("translatedText")
    if not translated:
        raise RuntimeError("Empty response")
    return restore_placeholders(text, html_unescape(translated))


def translate_libre(text, source_lang, target_lang, libre_url, api_key):
    payload = {
        "q": text,
        "source": source_lang,
        "target": target_lang,
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        libre_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "UE-PO-Localizer/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    translated = data.get("translatedText")
    if not translated:
        raise RuntimeError("Empty response")
    return restore_placeholders(text, translated)


def html_unescape(value):
    return (
        value.replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def restore_placeholders(source, translated):
    placeholders = re.findall(r"\{[^}\s]+\}|%[sdif]|\[[^\]\s]+\]", source)
    result = translated.strip()
    for placeholder in placeholders:
        if placeholder not in result:
            result += " " + placeholder
    return result


def translate_text(text, settings, target_lang):
    source_lang = settings.get("sourceLang", "en")
    provider = settings.get("provider", "mymemory")
    # Normalize lang codes for translation APIs (zh-Hans -> zh, pt-BR -> pt)
    api_source = source_lang.split("-")[0].split("_")[0].lower()
    api_target = target_lang.split("-")[0].split("_")[0].lower()
    if provider == "libre":
        return translate_libre(
            text,
            api_source,
            api_target,
            settings.get("libreUrl") or "https://libretranslate.com/translate",
            settings.get("apiKey") or "",
        )
    return translate_mymemory(text, api_source, api_target)


def process_po_file(path, settings, cache, stamp):
    text, encoding = read_text(path)
    newline = detect_newline(text)
    lines = text.splitlines()
    entries = parse_po(text)
    language = detect_language(text, path)
    overwrite = bool(settings.get("overwrite"))
    skip_tagged = bool(settings.get("skipTagged", True))
    limit = int(settings.get("maxItems") or 0)
    delay = max(0, int(settings.get("delayMs") or 0)) / 1000
    backup = bool(settings.get("backup", True))

    result = {
        "path": str(path),
        "language": language,
        "entries": len(entries),
        "todo": 0,
        "translated": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "changed": False,
        "backup": "",
    }

    if not language:
        result["errors"].append("Language could not be detected.")
        return result

    if language == settings.get("sourceLang", "en"):
        result["skipped"] = len(entries)
        result["errors"].append("Source language file skipped.")
        return result

    candidates = [entry for entry in entries if should_translate(entry, overwrite, skip_tagged)]
    if limit > 0:
        candidates = candidates[:limit]
    result["todo"] = len(candidates)

    replacements = []
    for entry in candidates:
        source = entry.msgid.text
        cache_key = (source, settings.get("sourceLang", "en"), language, settings.get("provider", "mymemory"))
        try:
            if cache_key not in cache:
                cache[cache_key] = translate_text(source, settings, language)
                if delay:
                    time.sleep(delay)
            replacements.append((entry.msgstr.start_line, entry.msgstr.end_line, cache[cache_key]))
            result["translated"] += 1
        except Exception as exc:
            result["failed"] += 1
            result["errors"].append(f"{source[:70]} -> {exc}")

    if replacements:
        for start, end, translated in sorted(replacements, reverse=True):
            lines[start : end + 1] = [f"msgstr {format_po_string(translated)}"]

        if backup:
            backup_path = path.with_name(f"{path.name}.bak-{stamp}")
            shutil.copy2(path, backup_path)
            result["backup"] = str(backup_path)

        path.write_text(newline.join(lines) + (newline if text.endswith(("\n", "\r\n")) else ""), encoding=encoding)
        result["changed"] = True

    return result


def process_archive_file(path, settings, cache, stamp):
    """Process a single .archive file for translation."""
    language = detect_language("", path)
    overwrite = bool(settings.get("overwrite"))
    skip_tagged = bool(settings.get("skipTagged", True))
    limit = int(settings.get("maxItems") or 0)
    delay = max(0, int(settings.get("delayMs") or 0)) / 1000
    backup = bool(settings.get("backup", True))
    source_lang = settings.get("sourceLang", "en")

    result = {
        "path": str(path),
        "language": language,
        "entries": 0,
        "todo": 0,
        "translated": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "changed": False,
        "backup": "",
    }

    if not language:
        result["errors"].append("Language could not be detected.")
        return result

    if language == source_lang:
        result["errors"].append("Source language file skipped.")
        return result

    try:
        archive_data = read_archive(path)
        entries = collect_archive_entries(archive_data)
    except Exception as exc:
        result["errors"].append(f"File could not be read: {exc}")
        return result

    result["entries"] = len(entries)

    candidates = [
        e
        for e in entries
        if e["source"].strip()
        and (overwrite or not e["translation"].strip())
        and (not skip_tagged or looks_like_game_text(e["source"]))
    ]
    if limit > 0:
        candidates = candidates[:limit]
    result["todo"] = len(candidates)

    changed = False
    for entry in candidates:
        source = entry["source"]
        cache_key = (source, source_lang, language, settings.get("provider", "mymemory"))
        try:
            if cache_key not in cache:
                cache[cache_key] = translate_text(source, settings, language)
                if delay:
                    time.sleep(delay)
            entry["node"]["Translation"]["Text"] = cache[cache_key]
            result["translated"] += 1
            changed = True
        except Exception as exc:
            result["failed"] += 1
            result["errors"].append(f"{source[:70]} -> {exc}")

    if changed:
        if backup:
            backup_path = path.with_name(f"{path.name}.bak-{stamp}")
            shutil.copy2(path, backup_path)
            result["backup"] = str(backup_path)

        original_encoding = detect_archive_encoding(path)
        write_archive(path, archive_data, original_encoding)
        result["changed"] = True

    return result


def translate_folder(settings):
    source_lang = settings.get("sourceLang", "en")
    scan = scan_files(
        settings.get("root", ""),
        source_lang,
        bool(settings.get("overwrite")),
        bool(settings.get("skipTagged", True)),
    )
    file_format = scan.get("format", "none")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    totals = {
        "files": len(scan["files"]),
        "changedFiles": 0,
        "entries": 0,
        "todo": 0,
        "translated": 0,
        "failed": 0,
    }

    for item in scan["files"]:
        path = Path(item["path"])
        if file_format == "archive":
            result = process_archive_file(path, settings, GLOBAL_CACHE, stamp)
        else:
            result = process_po_file(path, settings, GLOBAL_CACHE, stamp)
        results.append(result)
        totals["entries"] += result["entries"]
        totals["todo"] += result["todo"]
        totals["translated"] += result["translated"]
        totals["failed"] += result["failed"]
        if result["changed"]:
            totals["changedFiles"] += 1

    return {"root": scan["root"], "totals": totals, "files": results}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        return

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw or "{}")
            if parsed.path == "/api/scan":
                self.send_json(scan_files(
                    payload.get("root", ""),
                    payload.get("sourceLang", "en"),
                    bool(payload.get("overwrite")),
                    bool(payload.get("skipTagged", True)),
                ))
            elif parsed.path == "/api/translate-folder":
                self.send_json(translate_folder(payload))
            elif parsed.path == "/api/translate-file":
                path = Path(payload.get("path", ""))
                file_format = payload.get("format", "po")
                settings = payload.get("settings", {})
                stamp = payload.get("stamp", "")
                if file_format == "archive":
                    res = process_archive_file(path, settings, GLOBAL_CACHE, stamp)
                else:
                    res = process_po_file(path, settings, GLOBAL_CACHE, stamp)
                self.send_json(res)
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def send_json(self, data, status=200):
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Unreal Localization Tool running at: http://127.0.0.1:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutdown.")


if __name__ == "__main__":
    sys.exit(main())
