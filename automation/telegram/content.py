"""Public EasyVOD channel text and deterministic release-message rendering."""
from html import escape

REPOSITORY = "Nirsassy/EasyVOD-updates"
CHANNEL_ID = -1004460240173
CHANNEL_USERNAME = "EasyVOD"
BOT_USERNAME = "EasyVODUpdatesBot"
DOWNLOAD = f"https://github.com/{REPOSITORY}/releases/latest/download/EasyVOD.apk"
GUIDE = f"https://github.com/{REPOSITORY}"
ENGLISH = f"https://github.com/{REPOSITORY}/blob/main/README.en.md"
CHANNEL_TITLE = "EasyVOD | עדכונים והורדות"
CHANNEL_DESCRIPTION = (
    "🎬 טלוויזיה ישראלית, תוכניות, רדיו ופודקאסטים באפליקציה אחת ל־Android ול־Android TV.\n"
    "📲 הורדה והוראות התקנה בהודעה הנעוצה.\n"
    "📺 קוד Downloader: 7197499\n"
    "🌐 tinyurl.com/EasyVOD"
)


def welcome(manifest):
    version = escape(manifest["versionName"])
    text = (
        "🎬 <b>ברוכים הבאים ל־EasyVOD</b>\n\n"
        "טלוויזיה ישראלית, תוכניות לצפייה לפי דרישה, רדיו ופודקאסטים — "
        "בטלפון, בטאבלט וב־Android TV / Google TV.\n\n"
        "כאן תמצאו גרסאות חדשות, מה השתנה ואיך מתקינים. "
        "שמרו את ההודעה הזאת — כל הקישורים החשובים נמצאים כאן 👇\n\n"
        "<b>📲 התקנה בטלפון או בטאבלט</b>\n"
        "לחצו על ״הורדת EasyVOD״, פתחו את קובץ ה־APK ואשרו התקנה. "
        "אם Android מבקשת זאת, אפשרו התקנה מהאפליקציה שפתחה את הקובץ.\n\n"
        "<b>📺 התקנה בטלוויזיה</b>\n"
        "1. חפשו ב־Google Play את <b>Downloader by AFTVnews</b> והתקינו.\n"
        "2. פתחו את Downloader והזינו את הקוד <code>7197499</code>.\n"
        "3. בחרו Go, המתינו להורדה ואשרו Install. "
        "אם תתבקשו, אפשרו התקנה מ־Downloader בהגדרות הטלוויזיה.\n\n"
        "<b>🔄 כבר התקנתם?</b>\n"
        "בדקו עדכונים מתוך האפליקציה: <b>הגדרות ← עזרה ואודות ← בדיקת עדכונים</b>. "
        "אפשר גם להתקין מהקישור כאן מעל הגרסה הקיימת. "
        "אין צורך להסיר את האפליקציה — כך נשמרים המועדפים וההגדרות.\n\n"
        f"<b>הגרסה העדכנית: {version}</b>\n"
        "הממשק בעברית כברירת מחדל; אפשר לבחור אנגלית בהגדרות השפה.\n\n"
        "🌍 English installation guide is available below.\n"
        "נהנים מהאפליקציה? שתפו את הערוץ עם חברים 💛"
    )
    return {"text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [
                [{"text": "📲 הורדת EasyVOD", "url": DOWNLOAD}],
                [{"text": "📖 מדריך התקנה", "url": GUIDE}, {"text": "🌍 English guide", "url": ENGLISH}],
                [{"text": "💛 תמיכה ב־EasyVOD", "url": "https://paypal.me/easyvod"}],
            ]}}


def announcement(manifest, welcome_id):
    notes = manifest["notes"].strip()
    if len(notes) > 2000:
        notes = notes[:1999].rstrip() + "…"
    version = escape(manifest["versionName"])
    text = f"🚀 <b>EasyVOD {version} זמינה להורדה</b>\n\n"
    text += "<b>מה חדש?</b>\n" + escape(notes or "שיפורים ותיקונים לחוויית הצפייה.")
    text += "\n\n🔄 אפשר לעדכן מתוך האפליקציה או להוריד מהכפתור למטה. התקינו מעל הגרסה הקיימת כדי לשמור על הנתונים."
    return {"text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True},
            "reply_markup": {"inline_keyboard": [
                [{"text": "📲 הורדת העדכון", "url": manifest["apkUrl"]}],
                [{"text": "📌 התקנה ועזרה", "url": f"https://t.me/{CHANNEL_USERNAME}/{welcome_id}"},
                 {"text": "📋 פרטי הגרסה", "url": f"https://github.com/{REPOSITORY}/releases/tag/v{manifest['versionName']}"}],
            ]}}
