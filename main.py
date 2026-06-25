import os
import time
import imaplib
import email
from email.header import decode_header
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot

# ===================== CONFIGURATION =====================
# Render-এর Environment Variables থেকে ডাটা নেবে
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
GMAIL_USER = os.environ.get("GMAIL_USER", "YOUR_GMAIL@gmail.com")
GMAIL_PASS = os.environ.get("GMAIL_PASS", "YOUR_16_DIGIT_APP_PASSWORD")  # স্পেস ছাড়া ১৬ অক্ষর
CHAT_ID = os.environ.get("CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")  # ওটিপি যে আইডি-তে যাবে

bot = telebot.TeleBot(BOT_TOKEN)

# ===================== HELPER FUNCTIONS =====================
def clean_text(string):
    """টেক্সট ডিকোড করার ফাংশন"""
    if string is None:
        return ""
    if isinstance(string, bytes):
        return string.decode('utf-8', errors='ignore')
    return string

def get_email_body(msg):
    """মেইলের বডি থেকে প্লেইন টেক্সট এক্সট্রাক্ট করার লজিক"""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                return part.get_payload(decode=True).decode('utf-8', errors='ignore')
    else:
        return msg.get_payload(decode=True).decode('utf-8', errors='ignore')
    return ""

# ===================== GMAIL MONITOR LOGIC =====================
def check_gmail():
    try:
        # SSL এর মাধ্যমে জিমেইল কানেক্ট করা
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("INBOX")

        # শুধুমাত্র আনরিড (UNSEEN) মেইল সার্চ করবে
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return

        msg_ids = messages[0].split()
        if not msg_ids:
            mail.logout()
            return

        for msg_id in msg_ids:
            # CRUCIAL FIX: BODY.PEEK[] ব্যবহারের ফলে ডাটা ফেচ হলেও মেইল অটো-রিড হবে না
            res, msg_data = mail.fetch(msg_id, '(BODY.PEEK[])')
            if res != "OK":
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    # সাবজেক্ট ডিকোড করা
                    subject, encoding = decode_header(msg["Subject"])[0]
                    subject = clean_text(subject)
                    
                    # প্রেরকের নাম ডিকোড করা
                    from_sender, encoding = decode_header(msg["From"])[0]
                    from_sender = clean_text(from_sender)
                    
                    # বডি টেক্সট এক্সট্রাক্ট করা
                    body = get_email_body(msg)
                    
                    # ওটিপি বা ভেরিফিকেশন কোড হাইলাইট করার চেষ্টা (Regex)
                    otp_match = re.search(r'\b\d{4,8}\b', body)
                    otp_hint = f"\n🔑 **Possible OTP/Code:** `{otp_match.group(0)}`" if otp_match else ""

                    # টেলিগ্রাম মেসেজ ফরম্যাট
                    tg_message = (
                        f"📩 **New Email Received!**\n\n"
                        f"👤 **From:** {from_sender}\n"
                        f"📌 **Subject:** {subject}\n"
                        f"📄 **Content Summary:**\n{body[:300]}...\n"
                        f"{otp_hint}"
                    )

                    # টেলিগ্রামে ওটিপি পাঠানো
                    try:
                        bot.send_message(CHAT_ID, tg_message, parse_mode="Markdown")
                        
                        # টেলিগ্রামে সফলভাবে যাওয়ার পর মেইলটিকে 'Seen' (Read) মার্ক করা হবে
                        mail.store(msg_id, '+FLAGS', '\\Seen')
                        print(f"[+] Successfully forwarded email ID {msg_id.decode()} to Telegram.")
                    except Exception as tg_err:
                        print(f"[-] Telegram Send Error: {tg_err}")

        mail.logout()

    except Exception as e:
        print(f"[-] Gmail Sync Error: {e}")

def gmail_background_loop():
    """রেন্ডার সার্ভারে প্রতি ১০ সেকেন্ড পর পর জিমেইল ইনবক্স চেক করবে"""
    print("[+] Gmail Monitor Thread Active...")
    while True:
        check_gmail()
        time.sleep(10)

# ===================== TELEGRAM COMMANDS =====================
@bot.message_handler(commands=['start'])
def start_command(message):
    # ইউজার যেন সহজে তার Chat ID জানতে পারে (Render-এর এনভায়রনমেন্টে বসানোর জন্য)
    bot.reply_to(message, f"👋 জিমেইল ফরওয়ার্ডার বট সচল আছে।\n\n"
                          f"🆔 তোর টেলিগ্রাম Chat ID: `{message.chat.id}`\n"
                          f"এই আইডিটি রেন্ডারের 'CHAT_ID' এনভায়রনমেন্ট ভেরিয়েবলে বসিয়ে দে।")

# ===================== KEEP ALIVE HTTP SERVER =====================
class WebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gmail to Telegram Forwarder is fully operational 24/7.")

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), WebServer).serve_forever()

# ===================== MAIN RUNNER =====================
if __name__ == "__main__":
    # ১. আপটাইম রোবটের পিং রিসিভ করার জন্য ওয়েব সার্ভার থ্রেড চালু
    threading.Thread(target=run_http_server, daemon=True).start()
    
    # ২. ব্যাকগ্রাউন্ডে জিমেইল মনিটর করার থ্রেড চালু
    threading.Thread(target=gmail_background_loop, daemon=True).start()
    
    # ৩. বটের কমান্ড হ্যান্ডলিং সচল রাখা
    print("[+] Bot initialized and polling...")
    bot.infinity_polling()
