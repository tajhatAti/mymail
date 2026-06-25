import os
import time
import imaplib
import email
from email.header import decode_header
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types

# ===================== CONFIGURATION =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "YOUR_TELEGRAM_CHAT_ID") # সরাসরি ভেরিয়েবল থেকে সিকিউরড অ্যাক্সেস

bot = telebot.TeleBot(BOT_TOKEN)

# ৭টি জিমেইল অ্যাকাউন্ট ডাইনামিক লোড
ACCOUNTS = []
for i in range(1, 8):
    user = os.environ.get(f"GMAIL_USER_{i}")
    pas = os.environ.get(f"GMAIL_PASS_{i}")
    if user and pas:
        ACCOUNTS.append({
            "user": user,
            "pass": pas.replace(" ", ""),
            "index": i - 1,
            "label": os.environ.get(f"GMAIL_LABEL_{i}", f"Account {i}")
        })

# ===================== HELPER FUNCTIONS =====================
def safe_decode(header_value):
    """ক্র্যাশ প্রোটেক্টেড হেডার ডিকোডার"""
    if not header_value:
        return "No Subject/Sender"
    try:
        decoded = decode_header(header_value)
        text, encoding = decoded[0]
        if isinstance(text, bytes):
            return text.decode(encoding or 'utf-8', errors='ignore')
        return str(text)
    except Exception:
        return "Decoding Error"

def get_email_body(msg):
    """মেইলের বডি স্ক্র্যাপ করার নিরাপদ লজিক"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
                except:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    # সিএসএস/স্টাইল ব্লক রিমুভ করে বডি ক্লিন করা
                    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
                    body = re.sub(r'<[^>]+>', ' ', html)
                    body = re.sub(r'\s+', ' ', body).strip()
                except:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            pass
    return body

def extract_all_links(msg):
    all_links = []
    content = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ["text/plain", "text/html"]:
                try:
                    content += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass
    else:
        try:
            content = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except:
            pass
    
    found = re.findall(r'https?://[^\s"\'<>\]\)]+', content)
    for link in found:
        clean = link.rstrip('.,;)]\'"')
        if clean not in all_links:
            all_links.append(clean)
    return all_links

def extract_verification_link(all_links):
    keywords = ['verify', 'confirm', 'activate', 'login', 'sign', 'auth', 
                'reset', 'approve', 'click', 'action', 'token', 'validate']
    for link in all_links:
        if any(kw in link.lower() for kw in keywords):
            return link
    return None

def extract_otp_codes(body):
    otps = []
    patterns = [
        r'\b(\d{4,8})\b',
        r'[\[\|{](\d{4,8})[\]\|}]',
        r'(\d{3}[-\s]\d{3})',
        r'code[:\s]+(\d{4,8})',
        r'otp[:\s]+(\d{4,8})',
        r'pin[:\s]+(\d{4,8})'
    ]
    for pattern in patterns:
        matches = re.findall(pattern, body, re.IGNORECASE)
        for match in matches:
            cleaned = re.sub(r'[\s\-]', '', match)
            if cleaned and cleaned not in otps and len(cleaned) >= 4:
                # সিএসএস বা পিক্সেল সাইজের বড় সংখ্যা ফিল্টার করা
                if len(cleaned) == 4 and cleaned in ['1000', '2000', '3000']: 
                    continue
                otps.append(cleaned)
    return list(dict.fromkeys(otps))

# ===================== BOT COMMANDS =====================
@bot.message_handler(commands=['start'])
def handle_start(message):
    if str(message.chat.id) != CHAT_ID:
        return # সম্পূর্ণ আনঅথরাইজড ইউজার ব্লক
        
    accounts_text = "\n".join([f"  ✅ {acc['label']}: {acc['user']}" for acc in ACCOUNTS])
    bot.send_message(CHAT_ID,
        f"✅ <b>Gmail Monitor Online!</b>\n\n"
        f"📧 <b>Connected Accounts ({len(ACCOUNTS)}):</b>\n{accounts_text}\n\n"
        f"🤖 সার্ভার ২৪/৭ সচল আছে এবং ইনবক্স মনিটর করছে।",
        parse_mode="HTML"
    )

# ===================== DELETE CALLBACK =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def handle_delete(call):
    if str(call.message.chat.id) != CHAT_ID:
        return

    parts = call.data.split('_')
    acc_idx = int(parts[1])
    uid = parts[2]

    target = next((a for a in ACCOUNTS if a["index"] == acc_idx), None)
    if not target:
        bot.answer_callback_query(call.id, "❌ Account পাওয়া যায়নি!", show_alert=True)
        return

    try:
        bot.answer_callback_query(call.id, "⏳ Delete হচ্ছে...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(target["user"], target["pass"])
        mail.select("INBOX")
        mail.uid('store', uid.encode(), '+FLAGS', '\\Deleted')
        mail.expunge()
        mail.logout()

        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        bot.send_message(CHAT_ID, f"🗑️ <b>Mail Delete হয়েছে!</b>\n📧 {target['user']}", parse_mode="HTML", reply_to_message_id=call.message.message_id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Delete failed: {e}", show_alert=True)

# ===================== EMAIL MONITOR =====================
def monitor_loop():
    print(f"[+] Monitoring {len(ACCOUNTS)} Gmail accounts sequentially...")
    while True:
        if not ACCOUNTS or not CHAT_ID:
            time.sleep(30)
            continue

        for acc in ACCOUNTS:
            try:
                mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                mail.login(acc["user"], acc["pass"])
                mail.select("INBOX")

                status, messages = mail.uid('search', None, "UNSEEN")
                if status != "OK" or not messages[0]:
                    mail.logout()
                    continue

                uids = messages[0].split()
                for uid in uids:
                    res, msg_data = mail.uid('fetch', uid, '(BODY.PEEK[])')
                    if res != "OK":
                        continue

                    for part in msg_data:
                        if not isinstance(part, tuple):
                            continue

                        msg = email.message_from_bytes(part[1])

                        # Safe Header Decoding
                        subject = safe_decode(msg.get("Subject"))
                        sender = safe_decode(msg.get("From"))

                        body = get_email_body(msg)
                        all_links = extract_all_links(msg)
                        verify_link = extract_verification_link(all_links)
                        otps = extract_otp_codes(body)

                        otp_section = ""
                        if otps:
                            otp_lines = "\n".join([f"   <code>{otp}</code>  ← tap to copy" for otp in otps[:3]])
                            otp_section = f"\n\n🔑 <b>OTP / Code detected:</b>\n{otp_lines}"

                        clean_body = re.sub(r'\s+', ' ', body).strip()
                        preview = clean_body[:250] + "..." if len(clean_body) > 250 else clean_body

                        tg_message = (
                            f"📩 <b>New Email Alert!</b>\n"
                            f"📧 <b>Account:</b> {acc['label']} ({acc['user']})\n"
                            f"👤 <b>From:</b> {sender}\n"
                            f"📌 <b>Subject:</b> {subject}\n\n"
                            f"💬 <b>Preview:</b>\n{preview}"
                            f"{otp_section}"
                        )

                        markup = types.InlineKeyboardMarkup(row_width=2)
                        if verify_link:
                            markup.add(types.InlineKeyboardButton("🔗 Open Verify Link", url=verify_link))
                        elif all_links:
                            markup.add(types.InlineKeyboardButton("🌐 Open Main Link", url=all_links[0]))
                        
                        markup.add(types.InlineKeyboardButton("🗑️ Delete Mail", callback_data=f"del_{acc['index']}_{uid.decode()}"))

                        # সরাসরি তোর CHAT_ID তে মেসেজ পাঠানো হচ্ছে
                        try:
                            bot.send_message(CHAT_ID, tg_message, parse_mode="HTML", reply_markup=markup)
                            # সফল ডেলিভারির পর মেইলটিকে Seen করা হচ্ছে
                            mail.uid('store', uid, '+FLAGS', '\\Seen')
                        except Exception as e:
                            print(f"[-] Telegram Send Failed: {e}")

                mail.logout()

            except Exception as e:
                print(f"[-] Error on {acc['user']}: {e}")

        # ৭টি অ্যাকাউন্ট এক চক্কর দেওয়ার পর ১০ সেকেন্ড বিরতি (CPU Throttling বাঁচাবে)
        time.sleep(10)

# ===================== WEB SERVER =====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gmail Monitor Keep-Alive Status: OK")
    def log_message(self, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), WebHandler).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    print("[+] Absolute Secure Monitor Engine Started!")
    bot.infinity_polling()
                   
