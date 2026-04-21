import json
import os
import re
import hashlib
import time
import random
from datetime import datetime
from bs4 import BeautifulSoup

ALERT_EMAIL    = os.environ.get("ALERT_EMAIL", "")
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
STATE_FILE     = "seen_emails.json"
MAILBOXES_FILE = "mailboxes.json"
BATCH_INDEX    = int(os.environ.get("BATCH_INDEX", "0"))
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "10"))
SEP            = "=" * 60

def load_mailboxes():
    if not os.path.exists(MAILBOXES_FILE):
        return []
    with open(MAILBOXES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    yopmail = [m for m in data if "@yopmail.com" in m.get("email", "").lower()]
    # Slice selon le batch
    start = BATCH_INDEX * BATCH_SIZE
    end   = start + BATCH_SIZE
    batch = yopmail[start:end]
    print("Batch " + str(BATCH_INDEX) + " : boites " + str(start+1) + " a " + str(min(end, len(yopmail))) + " sur " + str(len(yopmail)))
    return batch

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def is_first_scan(state):
    return len(state) == 0

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def msg_fingerprint(mid, subject):
    return hashlib.md5((mid + subject).encode()).hexdigest()

def extract_mondial_relay_code(text):
    patterns = [
        r'[Cc]ode\s*(?:de\s*)?(?:retrait|depot|collecte)\s*[:\-]?\s*([A-Z0-9]{4,8})',
        r'[Cc]ode\s*[:\-]?\s*([A-Z0-9]{5,8})',
        r'[Rr]etrait\s*[:\-]?\s*([A-Z0-9]{4,8})',
        r'\b([0-9]{5,6})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None

def is_mondial_relay_email(subject, sender, body):
    # Exclure explicitement les emails Saramart / Hacoo
    excluded_senders = ["saramart", "hacoo", "smtp-messaging", "email-messaging"]
    sender_lower = sender.lower()
    if any(exc in sender_lower for exc in excluded_senders):
        return False

    # Exclure aussi si le sujet contient des marqueurs Hacoo/Saramart
    excluded_subjects = ["hacoo", "saramart", "confirmation de commande", "paquet expedie", "paquet expédié"]
    subject_lower = subject.lower()
    if any(exc in subject_lower for exc in excluded_subjects):
        return False

    # Doit venir de Mondial Relay
    mondial_keywords = ["mondial relay", "mondialrelay", "point relais", "locker",
                        "colis disponible", "code de retrait", "retirer votre colis",
                        "consigne", "votre colis est disponible"]
    text = (subject + " " + sender + " " + body[:1000]).lower()
    return any(kw in text for kw in mondial_keywords)

def scan_mailbox(username, browser):
    from playwright.sync_api import TimeoutError as PWTimeout
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        locale="fr-FR",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    emails = []
    body_map = {}

    try:
        page.goto("https://yopmail.com/fr/?login=" + username, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Clique sur le bouton OK/Consulter si present
        for selector in ["button#refreshbut", "button.md", "input[value='OK']"]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(2)
                    break
            except Exception:
                pass

        # Attend l'iframe inbox
        try:
            page.wait_for_selector("iframe#ifinbox", timeout=12000)
        except PWTimeout:
            print("  -> pas d'iframe inbox")
            context.close()
            return [], {}

        inbox_frame = page.frame(name="ifinbox")
        if not inbox_frame:
            for frame in page.frames:
                if "inbox" in (frame.name or "") or "inbox" in frame.url:
                    inbox_frame = frame
                    break

        if not inbox_frame:
            print("  -> iframe introuvable")
            context.close()
            return [], {}

        try:
            inbox_frame.wait_for_load_state("load", timeout=8000)
        except PWTimeout:
            pass

        html = inbox_frame.content()
        soup = BeautifulSoup(html, "html.parser")

        for msg_el in soup.select(".m"):
            mid        = msg_el.get("id", "")
            subject_el = msg_el.select_one(".lms")
            sender_el  = msg_el.select_one(".lmf")
            date_el    = msg_el.select_one(".lmd")
            if not mid:
                continue
            emails.append({
                "id":      mid,
                "subject": subject_el.text.strip() if subject_el else "",
                "from":    sender_el.text.strip()  if sender_el  else "",
                "date":    date_el.text.strip()    if date_el    else "",
            })

        print("  -> " + str(len(emails)) + " email(s)")

        # Lit le corps de chaque email via JS (evite le probleme de = dans les IDs CSS)
        for email in emails:
            try:
                msg_id = email["id"]
                inbox_frame.evaluate("var el = document.getElementById('" + msg_id + "'); if(el) el.click();")
                time.sleep(2)

                mail_frame = page.frame(name="ifmail")
                if not mail_frame:
                    for frame in page.frames:
                        if frame.url and "mail" in frame.url and "inbox" not in frame.url:
                            mail_frame = frame
                            break

                if mail_frame:
                    try:
                        mail_frame.wait_for_load_state("load", timeout=8000)
                    except PWTimeout:
                        pass
                    mail_soup = BeautifulSoup(mail_frame.content(), "html.parser")
                    for tag in mail_soup(["script", "style"]):
                        tag.decompose()
                    body_map[msg_id] = mail_soup.get_text(separator="\n")
                    print("    Corps: " + str(len(body_map[msg_id])) + " chars")
                else:
                    body_map[msg_id] = ""
            except Exception as e:
                print("    erreur corps: " + str(e))
                body_map[email["id"]] = ""

    except Exception as e:
        print("  ERREUR: " + str(e))

    context.close()
    return emails, body_map


def save_alerts(alerts, batch_index, first_scan):
    """Sauvegarde les alertes dans alerts.json pour le job rapport."""
    data = {
        "batch": batch_index,
        "first_scan": first_scan,
        "timestamp": datetime.now().strftime('%d/%m/%Y a %H:%M'),
        "alerts": alerts,
    }
    with open("alerts.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Alertes sauvegardees : " + str(len(alerts)) + " code(s)")


def main():
    from playwright.sync_api import sync_playwright

    print(SEP)
    print("Scan KitStock batch " + str(BATCH_INDEX) + " - " + datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
    print(SEP)

    MAILBOXES  = load_mailboxes()
    if not MAILBOXES:
        print("Aucune boite pour ce batch, fin.")
        return

    state      = load_state()
    first_scan = is_first_scan(state)
    alerts     = []

    if first_scan:
        print("PREMIER SCAN - codes Mondial Relay existants seront remontes")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

        for i, box in enumerate(MAILBOXES):
            username = box["email"].split("@")[0]
            print("\n[" + str(i+1) + "/" + str(len(MAILBOXES)) + "] >> " + box["email"])

            if i > 0:
                delay = random.uniform(3, 6)
                print("  pause " + str(round(delay, 1)) + "s")
                time.sleep(delay)

            inbox, body_map = scan_mailbox(username, browser)

            if not inbox:
                state[box["email"]] = state.get(box["email"], {})
                continue

            box_state = state.get(box["email"], {})

            if first_scan:
                for msg in inbox:
                    fp   = msg_fingerprint(msg["id"], msg["subject"])
                    body = body_map.get(msg["id"], "")
                    box_state[fp] = True

                    mondial = is_mondial_relay_email(msg["subject"], msg["from"], body)
                    code    = extract_mondial_relay_code(body) if mondial else None

                    print("    Email: " + repr(msg["subject"]))
                    if mondial:
                        print("    -> Mondial Relay! Code: " + str(code))
                        alerts.append({
                            "email":   box["email"],
                            "locker":  box.get("locker", "-"),
                            "article": box.get("article", "-"),
                            "subject": msg["subject"],
                            "sender":  msg["from"],
                            "code":    code,
                        })
            else:
                new_msgs = [(m, msg_fingerprint(m["id"], m["subject"])) for m in inbox if msg_fingerprint(m["id"], m["subject"]) not in box_state]
                if not new_msgs:
                    print("  -> " + str(len(inbox)) + " email(s), aucun nouveau")
                    state[box["email"]] = box_state
                    continue

                print("  -> " + str(len(new_msgs)) + " nouveau(x) !")
                for msg, fp in new_msgs:
                    box_state[fp] = True
                    body    = body_map.get(msg["id"], "")
                    mondial = is_mondial_relay_email(msg["subject"], msg["from"], body)
                    code    = extract_mondial_relay_code(body) if mondial else None

                    print("    Email: " + repr(msg["subject"]))
                    if mondial:
                        print("    -> Mondial Relay! Code: " + str(code))
                        alerts.append({
                            "email":   box["email"],
                            "locker":  box.get("locker", "-"),
                            "article": box.get("article", "-"),
                            "subject": msg["subject"],
                            "sender":  msg["from"],
                            "code":    code,
                        })

            state[box["email"]] = box_state

        browser.close()

    save_state(state)

    print("\n" + SEP)
    print("Batch " + str(BATCH_INDEX) + " termine - " + str(len(alerts)) + " code(s) detecte(s)")
    save_alerts(alerts, BATCH_INDEX, first_scan)
    print(SEP)


if __name__ == "__main__":
    main()
