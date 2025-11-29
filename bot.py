# bot.py
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import MongoClient
from dotenv import load_dotenv
from utils.crypto import encrypt_bytes, decrypt_bytes

load_dotenv()
"API_TOKEN" = os.getenv("8253352811:AAF4qVJuJtCr2c7YYeXoezguDlxPHggSKXw")
ADMIN_IDS = [int(x) for x in os.getenv("7894840999","").split(",") if x.strip()]
MONGODB_URI = os.getenv("MONGODB_URI")
DEFAULT_UPI = os.getenv("DEFAULT_UPI","9288367268@naviaxis")
SCHEDULER_TYPE = os.getenv("SCHEDULER_TYPE","apscheduler")

logging.basicConfig(level=os.getenv("7894840999","INFO"))
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
client = MongoClient(MONGODB_URI)
db = client.autoyhack
users = db.users

# Helper: create user doc if not exists
def ensure_user(uid, username=None):
    u = users.find_one({"user_id": uid})
    if not u:
        u = {
            "user_id": uid,
            "telegram_username": username,
            "trial_start": None,
            "trial_expiry": None,
            "subscription_expiry": None,
            "plan": None,
            "payment_status": None,
            "client_secret_stored": False,
            "upload_frequency_hours": 3,
            "mode": "auto_niche",
            "niche": "default",
            "custom_links": [],
            "last_upload_time": None,
            "logs": []
        }
        users.insert_one(u)
    return users.find_one({"user_id": uid})

# Start command
@dp.message(Command(commands=["start"]))
async def cmd_start(msg: types.Message):
    u = ensure_user(msg.from_user.id, msg.from_user.username)
    # If first time, start trial
    if not u.get("trial_start"):
        now = datetime.utcnow()
        users.update_one({"user_id": msg.from_user.id},{"$set":{
            "trial_start": now,
            "trial_expiry": now + timedelta(days=1)
        }})
        await msg.reply(
            "🎉 Aapko 1-day FREE trial mil gaya! Ab apna client_secrets.json upload karein (file)."
            f"\n\nPayment UPI: {DEFAULT_UPI}\nPlans: 7 days ₹99 | 30 days ₹349\n\nSend client_secrets.json to start."
        )
    else:
        te = u.get("trial_expiry")
        se = u.get("subscription_expiry")
        msg_text = f"Trial expiry: {te}\nSubscription expiry: {se}\nUse /settings to configure."
        await msg.reply(msg_text)

# Accept client_secrets.json file
@dp.message()
async def handle_files(message: types.Message):
    # client_secrets.json upload
    if message.document:
        fname = message.document.file_name
        if fname.endswith("client_secrets.json"):
            # download file
            file = await bot.get_file(message.document.file_id)
            file_path = file.file_path
            save_path = f"./uploads/{message.from_user.id}_client_secrets.json"
            await message.document.download(destination=save_path)
            # encrypt & store in DB (binary)
            with open(save_path,"rb") as f:
                data = f.read()
            enc = encrypt_bytes(data)
            users.update_one({"user_id": message.from_user.id},{"$set":{
                "client_secret_stored": True,
                "client_secret_enc": enc,
                "client_secret_uploaded_at": datetime.utcnow()
            }})
            await message.reply("Client secrets received. Bot will attempt to use it for OAuth when needed. Trial active for 24 hours.")
            # start scheduler job for this user
            register_user_job(message.from_user.id)
            return

    # Payment screenshot (image)
    if message.photo or message.document and (message.document.mime_type and "image" in message.document.mime_type):
        # treat as payment screenshot if user had pending payment prompt
        u = ensure_user(message.from_user.id, message.from_user.username)
        # store screenshot URL forward to admin
        f = None
        if message.photo:
            f = message.photo[-1]
        else:
            f = message.document
        file_info = await bot.get_file(f.file_id)
        dl_path = f"./uploads/{message.from_user.id}_payment_{int(datetime.utcnow().timestamp())}.jpg"
        await f.download(destination=dl_path)
        # record in DB
        users.update_one({"user_id": message.from_user.id},{"$push":{
            "payment_screenshots": {"path": dl_path, "ts": datetime.utcnow()},
            "payment_status": "pending"
        }})
        # forward to admin(s) with inline approve/reject buttons
        caption = f"📌 Payment verification request\nUser: @{message.from_user.username} (ID:{message.from_user.id})\nUse Approve / Reject."
        for adm in ADMIN_IDS:
            keyboard = types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton(text="Approve ✅", callback_data=f"approve|{message.from_user.id}"),
                types.InlineKeyboardButton(text="Reject ❌", callback_data=f"reject|{message.from_user.id}")
            )
            await bot.send_photo(adm, FSInputFile(dl_path), caption=caption, reply_markup=keyboard)
        await message.reply("Payment screenshot received. Admin will verify shortly.")
        return

    # if text: settings / link mode / niche etc.
    text = (message.text or "").strip().lower()
    if text.startswith("/settings"):
        await message.reply("Use commands:\n/setfreq <3|6|12|24>\n/setmode auto|link\n/setniche <text>\n/addlink <url>")
        return
    if text.startswith("/setfreq"):
        parts = text.split()
        if len(parts)>=2 and parts[1].isdigit():
            h = int(parts[1])
            users.update_one({"user_id": message.from_user.id},{"$set":{"upload_frequency_hours":h}})
            register_user_job(message.from_user.id)
            await message.reply(f"Upload frequency set to {h} hours.")
            return
    if text.startswith("/setmode"):
        parts = text.split()
        if len(parts)>=2:
            mode = "auto_niche" if parts[1].lower()=="auto" else "user_link"
            users.update_one({"user_id": message.from_user.id},{"$set":{"mode":mode}})
            await message.reply(f"Mode set to {mode}")
            return
    if text.startswith("/setniche"):
        parts = text.split(maxsplit=1)
        if len(parts)>=2:
            users.update_one({"user_id": message.from_user.id},{"$set":{"niche":parts[1]}})
            await message.reply(f"Niche set to: {parts[1]}")
            return
    if text.startswith("/addlink"):
        parts = text.split(maxsplit=1)
        if len(parts)>=2:
            users.update_one({"user_id": message.from_user.id},{"$push":{"custom_links":{"link":parts[1],"added_on":datetime.utcnow(),"status":"pending"}}})
            await message.reply("Link added to your upload queue.")
            return

# Admin callback handling
@dp.callback_query()
async def cb_handler(cb: types.CallbackQuery):
    data = cb.data
    if not data: return
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Unauthorized", show_alert=True)
        return
    action, user_id = data.split("|")
    user_id = int(user_id)
    if action == "approve":
        # extend by default 7 days (admin can change later)
        expiry = datetime.utcnow() + timedelta(days=7)
        users.update_one({"user_id": user_id},{"$set":{"subscription_expiry": expiry, "payment_status":"approved", "plan":"7days"}})
        await cb.message.edit_caption(cb.message.caption + "\n\n✅ Approved by admin.")
        # notify user
        try:
            await bot.send_message(user_id, f"✅ Payment approved. Subscription active until {expiry}.")
        except Exception as e:
            logging.exception(e)
        await cb.answer("User approved")
    elif action == "reject":
        users.update_one({"user_id": user_id},{"$set":{"payment_status":"rejected"}})
        await cb.message.edit_caption(cb.message.caption + "\n\n❌ Rejected by admin.")
        try:
            await bot.send_message(user_id, "❌ Your payment was rejected. Please re-send screenshot or contact admin.")
        except:
            pass
        await cb.answer("User rejected")

# Scheduler job: register per-user
def register_user_job(user_id):
    # remove if exists
    job_id = f"user_{user_id}"
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception:
        pass
    u = users.find_one({"user_id": user_id})
    if not u:
        return
    # only if client_secrets stored
    if not u.get("client_secret_stored"):
        return
    freq = int(u.get("upload_frequency_hours",3))
    scheduler.add_job(run_upload_for_user, "interval", hours=freq, args=[user_id], id=job_id, next_run_time=datetime.utcnow()+timedelta(seconds=10))
    logging.info(f"Registered job {job_id} every {freq}h")

async def run_upload_for_user(user_id):
    # check trial/subscription
    u = users.find_one({"user_id": user_id})
    now = datetime.utcnow()
    if u.get("trial_expiry") and now < u.get("trial_expiry"):
        allowed = True
    elif u.get("subscription_expiry") and now < u.get("subscription_expiry"):
        allowed = True
    else:
        allowed = False
    if not allowed:
        try:
            await bot.send_message(user_id, "⚠️ Trial/subscription expired. Please renew to continue uploads.")
        except:
            pass
        # remove job to stop running until renewed
        try:
            scheduler.remove_job(f"user_{user_id}")
        except:
            pass
        return

    # choose video source
    if u.get("mode") == "user_link" and u.get("custom_links"):
        # get next pending link
        link = None
        for l in u.get("custom_links",[]):
            if l.get("status")=="pending":
                link = l.get("link"); break
        if link:
            # mark as processing
            users.update_one({"user_id": user_id, "custom_links.link": link},{"$set":{"custom_links.$.status":"processing"}})
            video_path = await download_video(link, user_id)
            # upload to youtube (stub)
            res = await upload_to_youtube_for_user(user_id, video_path, source_link=link)
            # on success mark link done
            users.update_one({"user_id": user_id, "custom_links.link": link},{"$set":{"custom_links.$.status":"done"}})
            return
    # else auto-niche mode: fetch clip (stub function)
    video_path = await fetch_clip_for_niche(u.get("niche","default"), user_id)
    if video_path:
        await upload_to_youtube_for_user(user_id, video_path, source_link=None)

# stub: download video via yt-dlp
async def download_video(link, user_id):
    # simple synchronous call via asyncio.to_thread
    import subprocess, shlex, os
    out_file = f"./tmp/{user_id}_{int(datetime.utcnow().timestamp())}.mp4"
    cmd = f'yt-dlp -f best -o "{out_file}" "{link}"'
    await asyncio.to_thread(subprocess.run, shlex.split(cmd), {"check":False})
    return out_file if os.path.exists(out_file) else None

# stub: fetch clip for niche (placeholder)
async def fetch_clip_for_niche(niche, user_id):
    # implement real scraper or use curated source
    # For demo, return None
    return None

# stub: youtube upload - IMPORTANT: You must complete OAuth exchange + build credentials
async def upload_to_youtube_for_user(user_id, video_path, source_link=None):
    # Steps to implement (README explains fully):
    # 1) decrypt stored client_secrets.json and create credentials (using google-auth or oauthlib)
    # 2) call youtube.videos().insert(...) with media upload
    # For now we'll just notify user/admin and remove file.
    if not video_path:
        return False
    await bot.send_message(user_id, f"Uploading video (demo): {video_path}")
    for adm in ADMIN_IDS:
        await bot.send_message(adm, f"User {user_id} would upload video: {video_path}")
    # cleanup
    try:
        import os
        os.remove(video_path)
    except:
        pass
    users.update_one({"user_id": user_id},{"$set":{"last_upload_time": datetime.utcnow()}})
    return True

# startup
async def on_startup():
    if not os.path.exists("./uploads"): os.makedirs("./uploads")
    if not os.path.exists("./tmp"): os.makedirs("./tmp")
    scheduler.start()
    # register jobs for existing users
    for u in users.find({"client_secret_stored":True}):
        register_user_job(u["user_id"])
    print("Bot started.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(on_startup())
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
