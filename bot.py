# ==========================================
#  BOT ABSENSI TELEGRAM - VERSI RENDER.COM
#  Siap jalan 24 jam non-stop tanpa komputer
# ==========================================

import os, sys, time, uuid, sqlite3, random, threading
from datetime import datetime, timedelta
import telebot
from telebot import types
from keep_alive import keep_alive  # Menjaga agar tetap hidup di Render

# ==================== KONFIGURASI ====================
TOKEN = "8058919854:AAFkGGVpBrm8Y5cbeQjH5D8t1IbRJaRkvdo"  # Token yang kamu berikan
DB_FILE = "attendance.db"
ADMIN_TAG = "@chitato888"

WORK_START = "09:00"
WORK_END = "21:00"
TOLERANSI = 2

IZIN_LIMITS_TIME = {"PIPIS":10,"ROKOK":10,"BOKER":15,"MAKAN":30}
IZIN_LIMITS_COUNT = {"PIPIS":3,"ROKOK":3,"BOKER":3,"MAKAN":3}
DENDA = 2

PANTUN_LIST = [
    "🌸 Jangan malas, jangan galau, izinmu kelewatan nanti kena tegur 😆",
    "🍃 Santai boleh, tapi kerja tetap fokus, izinmu molor nanti bos marah 😎",
    "🌻 Izin sudah cukup, jangan ulangi, nanti ada pantun lucu untukmu 😂"
]

IZIN_MESSAGES = {
    "PIPIS":["🚽 Pipis sebentar, jangan kangen!","⏳ Toilet time, tunggu sebentar ya."],
    "ROKOK":["🚬 Ngopi + rokok bentar...","💨 Asap mengepul sebentar ya!"],
    "BOKER":["💩 Lagi numpang WC, jangan diganggu.","🚾 Misi besar sedang berlangsung."],
    "MAKAN":["🍽 Lagi makan, isi energi!","😋 Makan dulu biar semangat kerja!"]
}

WORK_MESSAGES = ["👷 Siap kerja penuh semangat!","🔥 Gaspol kerja hari ini!","💪 Let's go kerja produktif!"]
OFFWORK_MESSAGES = ["🏠 Kerja selesai, saatnya istirahat!","✅ Tugas hari ini beres!","🎉 Waktunya pulang!"]

bot = telebot.TeleBot(TOKEN)

# ================= MIGRASI DATABASE ==================
REQUIRED_COLUMNS = {
    "chat_id": "INTEGER",
    "warned": "INTEGER DEFAULT 0",
    "end_time": "TEXT",
    "izin_count": "INTEGER DEFAULT 0",
    "orig_start_time": "TEXT",
    "late": "INTEGER DEFAULT 0"
}

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            fullname TEXT,
            status TEXT,
            start_time TEXT
        )
    """)
    cur.execute("PRAGMA table_info(attendance)")
    existing_cols = [row[1] for row in cur.fetchall()]
    for col, col_type in REQUIRED_COLUMNS.items():
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE attendance ADD COLUMN {col} {col_type}")
            print(f"✅ Kolom {col} ditambahkan ({col_type})")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS instance_lock (
            id INTEGER PRIMARY KEY CHECK (id=1),
            instance_id TEXT,
            timestamp DATETIME
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            fullname TEXT,
            chat_id INTEGER
        )
    """)
    conn.commit()
    conn.close()
    print("🎉 Migrasi database selesai, aman dipakai bot")

# ============== SINGLE INSTANCE GUARD ================
INSTANCE_ID = str(uuid.uuid4())
LOCK_TIMEOUT = 60

def acquire_lock():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT instance_id, timestamp FROM instance_lock WHERE id=1")
    row = cur.fetchone()
    now = int(time.time())
    if row:
        old_instance, ts = row
        ts = int(ts)
        if now - ts < LOCK_TIMEOUT:
            print(f"⚠️ Bot instance lain masih aktif. Keluar...")
            conn.close()
            sys.exit(1)
        else:
            cur.execute("UPDATE instance_lock SET instance_id=?, timestamp=? WHERE id=1", (INSTANCE_ID, now))
    else:
        cur.execute("INSERT INTO instance_lock (id, instance_id, timestamp) VALUES (1, ?, ?)", (INSTANCE_ID, now))
    conn.commit()
    conn.close()
    print(f"🔒 Lock diambil oleh instance {INSTANCE_ID}")

def refresh_lock():
    while True:
        time.sleep(LOCK_TIMEOUT // 2)
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("UPDATE instance_lock SET timestamp=? WHERE id=1 AND instance_id=?", (int(time.time()), INSTANCE_ID))
        conn.commit()
        conn.close()

# ================== UTILITAS ==================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def minutes_diff(start, end):
    return int((end - start).total_seconds() // 60)

def register_user(user, chat_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, username, fullname, chat_id) VALUES (?,?,?,?)",
                (user.id, getattr(user,'username','unknown'), user.full_name, chat_id))
    conn.commit()
    conn.close()

# ================== RESET IZIN ==================
def reset_izin_count():
    while True:
        if datetime.now().strftime("%H:%M") == "00:01":
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("UPDATE attendance SET izin_count=0")
            conn.commit()
            conn.close()
            print("🔄 Reset izin harian selesai")
        time.sleep(30)

# ================== MONITOR IZIN ==================
def monitor_izin():
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT id,user_id,fullname,status,start_time,chat_id,warned FROM attendance WHERE status IN ('PIPIS','ROKOK','BOKER','MAKAN') AND end_time IS NULL")
            rows = cur.fetchall()
            for aid, uid, name, stype, stime, chat, warned in rows:
                try:
                    dur = minutes_diff(datetime.strptime(stime,"%Y-%m-%d %H:%M:%S"), datetime.now())
                except:
                    dur = 0
                limit = IZIN_LIMITS_TIME.get(stype,0)
                if dur > limit and warned == 0:
                    keyboard = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton(text="Selesai ✅", callback_data=f"finish_{aid}")
                    keyboard.add(btn)
                    bot.send_message(chat,
                        f"⚠️ [{name}] Izin {stype.lower()} sudah {dur} menit! Limit {limit} menit.\n💵 Denda: {DENDA}$\n📜 Pantun: {random.choice(PANTUN_LIST)}\nTag: {ADMIN_TAG}",
                        reply_markup=keyboard)
                    cur.execute("UPDATE attendance SET warned=1 WHERE id=?", (aid,))
            conn.commit()
            conn.close()
        except Exception as e:
            print("⚠️ Error monitor_izin:", e)
        time.sleep(30)

# ================== REMINDER MASUK/PULANG ==================
def scheduler():
    while True:
        now = datetime.now()
        t_str = now.strftime("%H:%M")
        if t_str == WORK_START:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT user_id,fullname,chat_id FROM users WHERE user_id NOT IN (SELECT user_id FROM attendance WHERE date(start_time)=date('now') AND status='WORK')")
            rows = cur.fetchall()
            for uid, name, chat in rows:
                bot.send_message(chat,f"⏰ [{name}] Belum masuk kerja! Silakan /work sekarang.")
            conn.close()
        if t_str == WORK_END:
            conn = sqlite3.connect(DB_FILE)
            cur = conn.cursor()
            cur.execute("SELECT id,user_id,chat_id,start_time FROM attendance WHERE status='WORK' AND end_time IS NULL")
            rows = cur.fetchall()
            for aid, uid, chat, stime in rows:
                etime = now_str()
                dur = minutes_diff(datetime.strptime(stime,"%Y-%m-%d %H:%M:%S"), datetime.strptime(etime,"%Y-%m-%d %H:%M:%S"))
                cur.execute("UPDATE attendance SET end_time=? WHERE id=?",(etime,aid))
                bot.send_message(chat,f"💻 Auto pulang kerja!\n⏰ Jam {WORK_END}\n⏳ Durasi kerja: {dur} menit")
            conn.commit()
            conn.close()
        time.sleep(30)

# ================== COMMANDS ==================
@bot.message_handler(commands=["start","work"])
def work_cmd(m):
    register_user(m.from_user, m.chat.id)
    now = datetime.now()
    sched_start = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {WORK_START}","%Y-%m-%d %H:%M")
    late = max(0, minutes_diff(sched_start, now) - TOLERANSI) if now > sched_start else 0
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO attendance(user_id, username, fullname, status, start_time, chat_id, late) VALUES (?,?,?,?,?,?,?)",
                (m.from_user.id, getattr(m.from_user,'username','unknown'), m.from_user.full_name,"WORK", now_str(), m.chat.id, late))
    conn.commit(); conn.close()
    msg = f"💻 [{m.from_user.full_name}] Masuk kerja!"
    if late>0: msg += f"\n⏰ Terlambat {late} menit!"
    msg += f"\n{random.choice(WORK_MESSAGES)}"
    bot.reply_to(m, msg)

@bot.message_handler(commands=["offwork"])
def offwork_cmd(m):
    uid = m.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,start_time FROM attendance WHERE user_id=? AND status='WORK' AND end_time IS NULL ORDER BY id DESC LIMIT 1",(uid,))
    row = cur.fetchone()
    if row:
        aid, stime = row
        etime = now_str()
        dur = minutes_diff(datetime.strptime(stime,"%Y-%m-%d %H:%M:%S"), datetime.strptime(etime,"%Y-%m-%d %H:%M:%S"))
        cur.execute("UPDATE attendance SET end_time=? WHERE id=?",(etime, aid))
        bot.reply_to(m, f"✅ [{m.from_user.full_name}] Selesai kerja!\nDurasi: {dur} menit\n{random.choice(OFFWORK_MESSAGES)}")
    else:
        bot.reply_to(m, f"⚠️ Tidak ada sesi kerja aktif.")
    conn.commit(); conn.close()

@bot.message_handler(commands=["pipis","rokok","boker","makan"])
def izin_cmd(m):
    action = m.text.replace("/","").upper()
    uid = m.from_user.id
    chat_id = m.chat.id
    register_user(m.from_user, chat_id)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    count_today = 0
    if action in IZIN_LIMITS_COUNT:
        cur.execute("SELECT izin_count FROM attendance WHERE user_id=? AND status=? AND date(start_time)=date('now') ORDER BY id DESC LIMIT 1",(uid,action))
        row = cur.fetchone()
        count_today = row[0] if row else 0
        if count_today >= IZIN_LIMITS_COUNT[action]:
            bot.reply_to(m,f"🚫 Izin {action.lower()} sudah {IZIN_LIMITS_COUNT[action]}x hari ini!")
            conn.close(); return
    cur.execute("INSERT INTO attendance(user_id,username,fullname,status,start_time,chat_id,izin_count) VALUES (?,?,?,?,?,?,?)",
                (uid, getattr(m.from_user,'username','unknown'), m.from_user.full_name, action, now_str(), chat_id, count_today+1))
    conn.commit()
    bot.reply_to(m,f"🕐 Izin {action.lower()} dimulai.\n{random.choice(IZIN_MESSAGES[action])}")
    conn.close()

@bot.message_handler(commands=["back"])
def back_cmd(m):
    uid = m.from_user.id
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,status,start_time FROM attendance WHERE user_id=? AND end_time IS NULL AND status IN ('PIPIS','ROKOK','BOKER','MAKAN') ORDER BY id DESC LIMIT 1",(uid,))
    row = cur.fetchone()
    if row:
        aid, stype, stime = row
        etime = now_str()
        dur = minutes_diff(datetime.strptime(stime,"%Y-%m-%d %H:%M:%S"), datetime.strptime(etime,"%Y-%m-%d %H:%M:%S"))
        cur.execute("UPDATE attendance SET end_time=?, warned=0 WHERE id=?",(etime, aid))
        bot.reply_to(m,f"💾 Kembali dari {stype.lower()}! Durasi {dur} menit.")
    else:
        bot.reply_to(m,"⚠️ Tidak ada izin aktif.")
    conn.commit(); conn.close()

# ================== CALLBACK FINISH ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("finish_"))
def finish_izin(call):
    aid = int(call.data.split("_")[1])
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT fullname,status,start_time,chat_id FROM attendance WHERE id=?", (aid,))
    row = cur.fetchone()
    if not row:
        bot.answer_callback_query(call.id, "❌ Data izin tidak ditemukan!")
        conn.close(); return
    fullname, stype, stime, chat_id = row
    etime = now_str()
    dur = minutes_diff(datetime.strptime(stime,"%Y-%m-%d %H:%M:%S"), datetime.strptime(etime,"%Y-%m-%d %H:%M:%S"))
    cur.execute("UPDATE attendance SET end_time=?, warned=0 WHERE id=?", (etime, aid))
    conn.commit(); conn.close()
    bot.send_message(chat_id, f"✅ [{fullname}] Izin {stype.lower()} selesai!\nDurasi {dur} menit.")
    bot.answer_callback_query(call.id, "✅ Izin selesai!")

# ================== MAIN ==================
if __name__ == "__main__":
    keep_alive()  # 🔥 Jalankan web server mini agar Render tetap aktif
    migrate_db()
    acquire_lock()
    threading.Thread(target=refresh_lock, daemon=True).start()
    threading.Thread(target=monitor_izin, daemon=True).start()
    threading.Thread(target=reset_izin_count, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    print("✅ Bot full absensi siap! Semua fitur berjalan...")
    bot.infinity_polling(skip_pending=True)
