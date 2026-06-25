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
FIXED_ACCESS_CODE = "Telegram#Telegram"

bot = telebot.TeleBot(BOT_TOKEN)

# Multiple Gmail accounts load
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

# Authorized users (যারা code দিয়ে access নিয়েছে)
authorized_users = set()

# ===================== HELPER FUNCTIONS =====================
def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='ignore')
    return str(value)

def get_email_body(msg):
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
                    # HTML tag remove
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
    """সব link বের করো"""
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
    """Verification/action link বের করো"""
    keywords = ['verify', 'confirm', 'activate', 'login', 'sign', 'auth', 
                'reset', 'approve', 'click', 'action', 'token', 'validate']
    for link in all_links:
        if any(kw in link.lower() for kw in keywords):
            return link
    return None

def extract_otp_codes(body):
    """
    বিভিন্ন format-এর OTP বের করো:
    - Plain text: Your OTP is 123456
    - Box style: [123456] বা |123456|
    - Bold/spaced: 1 2 3 4 5 6
    - Mixed: code is: 123-456
    """
    otps = []
    
    # সাধারণ ৪-৮ digit number
    patterns = [
        r'\b(\d{4,8})\b',                          # plain 4-8 digit
        r'[\[\|{](\d{4,8})[\]\|}]',                # [123456] বা |123456|
        r'(\d{3}[-\s]\d{3})',                       # 123-456 বা 123 456
        r'(\d{2}[-\s]\d{2}[-\s]\d{2})',            # 12-34-56
        r'code[:\s]+(\d{4,8})',                     # code: 123456
        r'otp[:\s]+(\d{4,8})',                      # otp: 123456
        r'(\d\s\d\s\d\s\d[\s\d]*)',                # spaced: 1 2 3 4 5 6
        r'pin[:\s]+(\d{4,8})',                      # pin: 1234
        r'passcode[:\s]+(\d{4,8})',                 # passcode: 123456
        r'verification[:\s#]+(\d{4,8})',            # verification: 123456
        r'token[:\s]+([A-Z0-9]{4,10})',            # token: ABC123
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, body, re.IGNORECASE)
        for match in matches:
            cleaned = re.sub(r'[\s\-]', '', match)
            if cleaned and cleaned not in otps and len(cleaned) >= 4:
                otps.append(cleaned)
    
    return list(dict.fromkeys(otps))  # duplicate remove

def send_to_all(message, markup=None, parse_mode="HTML"):
    """সব authorized user-কে message পাঠাও"""
    for chat_id in authorized_users:
        try:
            bot.send_message(chat_id, message, parse_mode=parse_mode, reply_markup=markup)
        except Exception as e:
            print(f"Send error to {chat_id}: {e}")

# ===================== BOT COMMANDS =====================
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = str(message.chat.id)
    if chat_id in authorized_users:
        accounts_text = "\n".join([f"  ✅ {acc['label']}: {acc['user']}" for acc in ACCOUNTS])
        bot.send_message(message.chat.id,
            f"✅ <b>Bot Online!</b>\n\n"
            f"📧 <b>Connected Accounts ({len(ACCOUNTS)}):</b>\n{accounts_text}\n\n"
            f"🔔 নতুন mail আসলে এখানে দেখাবে\n\n"
            f"<b>Commands:</b>\n"
            f"/start - Status check\n"
            f"/accounts - Account list\n"
            f"/help - সাহায্য",
            parse_mode="HTML"
        )
    else:
        bot.send_message(message.chat.id,
            "🔐 <b>Access Code দাও:</b>\n\n"
            "Bot ব্যবহার করতে access code লাগবে।\n"
            "Code টা এখানে পাঠাও।",
            parse_mode="HTML"
        )

@bot.message_handler(commands=['accounts'])
def handle_accounts(message):
    if str(message.chat.id) not in authorized_users:
        bot.send_message(message.chat.id, "❌ Access নেই! /start দিয়ে code দাও।")
        return
    text = "📧 <b>Connected Gmail Accounts:</b>\n\n"
    for i, acc in enumerate(ACCOUNTS, 1):
        text += f"{i}. {acc['label']}\n   📮 {acc['user']}\n\n"
    bot.send_message(message.chat.id, text, parse_mode="HTML")

@bot.message_handler(commands=['help'])
def handle_help(message):
    if str(message.chat.id) not in authorized_users:
        bot.send_message(message.chat.id, "❌ Access নেই!")
        return
    bot.send_message(message.chat.id,
        "📖 <b>Help Guide</b>\n\n"
        "🔹 নতুন mail আসলে auto notification\n"
        "🔹 OTP/Code automatically detect হবে\n"
        "🔹 Verification link-এ direct click করা যাবে\n"
        "🔹 Mail সরাসরি delete করা যাবে\n"
        "🔹 যেকোনো device থেকে access code দিয়ে login\n\n"
        "<b>Commands:</b>\n"
        "/start - Status ও account info\n"
        "/accounts - Gmail account list\n"
        "/help - এই help message",
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    chat_id = str(message.chat.id)
    text = message.text.strip()

    if chat_id in authorized_users:
        return  # Already authorized, ignore

    # Access code check
    if text == FIXED_ACCESS_CODE:
        authorized_users.add(chat_id)
        accounts_text = "\n".join([f"  ✅ {acc['label']}: {acc['user']}" for acc in ACCOUNTS])
        bot.send_message(message.chat.id,
            f"✅ <b>Access দেওয়া হয়েছে!</b>\n\n"
            f"📧 <b>Connected Accounts ({len(ACCOUNTS)}):</b>\n{accounts_text}\n\n"
            f"🔔 এখন থেকে নতুন mail এখানে আসবে।",
            parse_mode="HTML"
        )
    else:
        bot.send_message(message.chat.id,
            "❌ <b>ভুল Code!</b>\n\nআবার চেষ্টা করো।",
            parse_mode="HTML"
        )

# ===================== DELETE CALLBACK =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def handle_delete(call):
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

        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )
        bot.send_message(
            call.message.chat.id,
            f"🗑️ <b>Mail Delete হয়েছে!</b>\n📧 {target['user']}",
            parse_mode="HTML",
            reply_to_message_id=call.message.message_id
        )
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Delete failed: {e}", show_alert=True)

# ===================== EMAIL MONITOR =====================
def monitor_loop():
    print(f"[+] Monitoring {len(ACCOUNTS)} Gmail accounts...")
    while True:
        if not ACCOUNTS:
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

                        # Subject
                        subject_raw = decode_header(msg["Subject"])[0]
                        subject = clean_text(subject_raw[0])

                        # Sender
                        from_raw = decode_header(msg["From"])[0]
                        sender = clean_text(from_raw[0])

                        # Body
                        body = get_email_body(msg)

                        # Links
                        all_links = extract_all_links(msg)
                        verify_link = extract_verification_link(all_links)

                        # OTP detection
                        otps = extract_otp_codes(body)

                        # OTP section build
                        otp_section = ""
                        if otps:
                            otp_lines = "\n".join([f"   <code>{otp}</code>  ← tap to copy" for otp in otps[:3]])
                            otp_section = f"\n\n🔑 <b>OTP / Code detected:</b>\n{otp_lines}"

                        # Body preview
                        clean_body = re.sub(r'\s+', ' ', body).strip()
                        preview = clean_body[:250] + "..." if len(clean_body) > 250 else clean_body

                        # Message build
                        tg_message = (
                            f"📩 <b>New Email!</b>\n"
                            f"📧 <b>To:</b> {acc['user']}\n"
                            f"👤 <b>From:</b> {sender}\n"
                            f"📌 <b>Subject:</b> {subject}\n\n"
                            f"💬 <b>Preview:</b>\n{preview}"
                            f"{otp_section}"
                        )

                        # Buttons
                        markup = types.InlineKeyboardMarkup(row_width=2)
                        if verify_link:
                            markup.add(types.InlineKeyboardButton(
                                "🔗 Open Verify Link", url=verify_link
                            ))
                        if all_links and not verify_link:
                            markup.add(types.InlineKeyboardButton(
                                "🌐 Open Link", url=all_links[0]
                            ))
                        markup.add(types.InlineKeyboardButton(
                            "🗑️ Delete Mail",
                            callback_data=f"del_{acc['index']}_{uid.decode()}"
                        ))

                        # Send
                        send_to_all(tg_message, markup=markup)

                        # Mark as read
                        mail.uid('store', uid, '+FLAGS', '\\Seen')

                mail.logout()

            except Exception as e:
                print(f"[-] Error {acc['user']}: {e}")

        time.sleep(10)

# ===================== WEB SERVER =====================
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Gmail Bot Running!")
    def log_message(self, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(('0.0.0.0', port), WebHandler).serve_forever()

# ===================== MAIN =====================
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    print("[+] Bot started!")
    bot.infinity_polling()
