#!/usr/bin/env python3
"""Validate a stable APK release, announce it once, and refresh the welcome post."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from content import CHANNEL_ID, CHANNEL_USERNAME, BOT_USERNAME, REPOSITORY, announcement, welcome

ROOT = Path(__file__).resolve().parent
STATE_PATH = "automation/telegram/state.json"
MAX_APK_SIZE = 64 * 1024 * 1024


class PublicationError(RuntimeError):
    pass


def gh(*arguments, input_value=None):
    result = subprocess.run(["gh", *arguments], text=True, input=input_value, capture_output=True, timeout=180)
    if result.returncode:
        # Do not echo environment, command output, or HTTP request diagnostics.
        raise PublicationError("GitHub operation failed; no credentials were logged.")
    return result.stdout


def api(endpoint, **kwargs):
    return json.loads(gh("api", f"repos/{REPOSITORY}/" + endpoint, **kwargs))


def validate_manifest(manifest, release, directory):
    version = manifest.get("versionName", "")
    if not isinstance(version, str) or not re.fullmatch(r"\d{1,5}(?:\.\d{1,5}){1,3}", version):
        raise PublicationError("Invalid release version.")
    if manifest.get("schema") != 1 or manifest.get("applicationId") != "il.idanplus":
        raise PublicationError("Unexpected update manifest.")
    if type(manifest.get("versionCode")) is not int or not 1 <= manifest["versionCode"] <= 2147483647:
        raise PublicationError("Invalid version code.")
    if type(manifest.get("minSdk")) is not int or not 23 <= manifest["minSdk"] <= 1000:
        raise PublicationError("Invalid Android version requirement.")
    if release.get("draft") or release.get("prerelease") or release.get("tag_name") != "v" + version:
        raise PublicationError("Only the matching published stable release may be announced.")
    expected = f"https://github.com/{REPOSITORY}/releases/download/v{version}/EasyVOD-{version}.apk"
    if manifest.get("apkUrl") != expected:
        raise PublicationError("APK link does not belong to this EasyVOD release.")
    if not isinstance(manifest.get("notes"), str) or len(manifest["notes"]) > 4000:
        raise PublicationError("Invalid release notes.")
    if type(manifest.get("sizeBytes")) is not int or not 1 <= manifest["sizeBytes"] <= MAX_APK_SIZE:
        raise PublicationError("Invalid APK size.")
    digest = manifest.get("sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PublicationError("Invalid APK digest.")
    for name in (f"EasyVOD-{version}.apk", "EasyVOD.apk"):
        assets = [asset for asset in release.get("assets", []) if asset.get("name") == name]
        if len(assets) != 1 or assets[0].get("state") != "uploaded" or assets[0].get("size") != manifest["sizeBytes"]:
            raise PublicationError("Release APK assets are incomplete.")
        path = Path(directory) / name
        if path.stat().st_size != manifest["sizeBytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise PublicationError("Downloaded APK failed verification.")


class Telegram:
    def __init__(self, token):
        if not re.fullmatch(r"[0-9]{5,15}:[A-Za-z0-9_-]{25,80}", token):
            raise PublicationError("Missing or invalid Telegram bot secret.")
        self.token = token

    def call(self, method, **parameters):
        allowed = {"getMe", "getChat", "getChatMember", "sendMessage", "editMessageText", "pinChatMessage"}
        if method not in allowed:
            raise PublicationError("Telegram operation is outside the channel publisher scope.")
        if method != "getMe" and (type(parameters.get("chat_id")) is not int or parameters["chat_id"] != CHANNEL_ID):
            raise PublicationError("Telegram access is restricted to @EasyVOD.")
        request = Request("https://api.telegram.org/bot" + self.token + "/" + method,
                          data=json.dumps(parameters, ensure_ascii=False).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=45) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                result = json.loads(error.read())
            except Exception:
                raise PublicationError("Telegram request failed.") from None
        except Exception:
            raise PublicationError("Telegram response was not received; do not blindly retry a pending announcement.") from None
        if not result.get("ok"):
            if method == "editMessageText" and "message is not modified" in result.get("description", "").lower():
                return True
            raise PublicationError("Telegram rejected " + method + " (code " + str(result.get("error_code", "unknown")) + ").")
        return result["result"]

    def verify(self):
        me = self.call("getMe")
        if not me.get("is_bot") or me.get("username", "").casefold() != BOT_USERNAME.casefold():
            raise PublicationError("The configured token belongs to a different bot.")
        channel = self.call("getChat", chat_id=CHANNEL_ID)
        if channel.get("id") != CHANNEL_ID or channel.get("username", "").casefold() != CHANNEL_USERNAME.casefold():
            raise PublicationError("Unexpected Telegram destination.")
        member = self.call("getChatMember", chat_id=CHANNEL_ID, user_id=me["id"])
        if member.get("status") != "administrator" or not member.get("can_post_messages") or not member.get("can_edit_messages"):
            raise PublicationError("Channel posting/editing permissions are missing.")


class State:
    def load(self):
        record = api("contents/" + STATE_PATH + "?ref=main")
        self.sha = record["sha"]
        state = json.loads(base64.b64decode(record["content"]))
        if state.get("schema") != 1 or state.get("channel_id") != CHANNEL_ID or not isinstance(state.get("releases"), dict):
            raise PublicationError("Unexpected announcement state.")
        return state

    def save(self, state):
        body = {"message": "Record EasyVOD Telegram publication state", "branch": "main", "sha": self.sha,
                "content": base64.b64encode((json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode()).decode()}
        record = json.loads(gh("api", "--method", "PUT", f"repos/{REPOSITORY}/contents/{STATE_PATH}", "--input", "-", input_value=json.dumps(body)))
        self.sha = record["content"]["sha"]


def publish_verified(manifest, release, telegram, store, welcome_id):
    state = store.load()
    tag = release["tag_name"]
    record = state["releases"].get(tag)
    if record and record.get("release_id") != release["id"]:
        raise PublicationError("Release identity changed; publication needs review.")
    if record and record.get("status") == "pending":
        raise PublicationError("A previous announcement is pending verification. Check @EasyVOD before reconciling its message ID in state.json; no duplicate was sent.")
    if not record:
        # Persist an atomic reservation before sending. An ambiguous Telegram
        # timeout must leave 'pending' so a rerun cannot duplicate the post.
        state["releases"][tag] = {"status": "pending", "release_id": release["id"],
            "version_code": manifest["versionCode"], "reserved_at": datetime.now(timezone.utc).isoformat()}
        store.save(state)
        result = telegram.call("sendMessage", chat_id=CHANNEL_ID, **announcement(manifest, welcome_id))
        if result.get("chat", {}).get("id") != CHANNEL_ID or type(result.get("message_id")) is not int:
            raise PublicationError("Unexpected Telegram acknowledgment; inspect the pending state before retrying.")
        print(json.dumps({"announcement_message_id": result["message_id"]}), flush=True)
        state["releases"][tag].update(status="sent", message_id=result["message_id"])
        store.save(state)
    elif record.get("status") != "sent":
        raise PublicationError("Unknown announcement state.")
    # These operations are safe to repeat after an interrupted run.
    telegram.call("editMessageText", chat_id=CHANNEL_ID, message_id=welcome_id, **welcome(manifest))
    telegram.call("pinChatMessage", chat_id=CHANNEL_ID, message_id=welcome_id, disable_notification=True)
    return {"release": tag, "message_id": state["releases"][tag]["message_id"], "already_announced": bool(record), "welcome_updated": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="", help="Published version tag; empty selects the latest stable release")
    parser.add_argument("--dry-run", action="store_true", help="Verify both APKs and preview without Telegram calls or state writes")
    args = parser.parse_args()
    if os.environ.get("GITHUB_REPOSITORY", REPOSITORY) != REPOSITORY:
        raise PublicationError("This publisher only runs for the EasyVOD update repository.")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()) if os.environ.get("GITHUB_EVENT_PATH") else {}
    tag = args.tag or event.get("release", {}).get("tag_name") or os.environ.get("REQUESTED_TAG", "")
    if tag and not re.fullmatch(r"v\d{1,5}(?:\.\d{1,5}){1,3}", tag):
        raise PublicationError("Only a stable EasyVOD version tag is accepted.")
    latest = api("releases/latest")
    release = api("releases/tags/" + tag) if tag else latest
    if release.get("draft") or release.get("prerelease") or release["id"] != latest["id"]:
        print(json.dumps({"skipped": "Only the current stable release is announced."})); return
    config = json.loads((ROOT / "channel.json").read_text())
    if config.get("channel_id") != CHANNEL_ID or type(config.get("welcome_message_id")) is not int or config["welcome_message_id"] < 1:
        raise PublicationError("The fixed EasyVOD welcome message is not configured.")
    with tempfile.TemporaryDirectory(prefix="easyvod-telegram-release-") as directory:
        gh("release", "download", release["tag_name"], "--repo", REPOSITORY,
           "--pattern", "latest.json", "--pattern", "EasyVOD*.apk", "--dir", directory)
        manifest = json.loads((Path(directory) / "latest.json").read_text())
        validate_manifest(manifest, release, directory)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "release": release["tag_name"], "both_apks_verified": True,
                          "announcement": announcement(manifest, config["welcome_message_id"]), "welcome": welcome(manifest)}, ensure_ascii=False)); return
    telegram = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram.verify()
    print(json.dumps(publish_verified(manifest, release, telegram, State(), config["welcome_message_id"])))


if __name__ == "__main__":
    try:
        main()
    except PublicationError as error:
        print(str(error), file=sys.stderr); raise SystemExit(1)
    except Exception as error:
        print("Publisher stopped (" + type(error).__name__ + "); no credentials were logged.", file=sys.stderr); raise SystemExit(1)
