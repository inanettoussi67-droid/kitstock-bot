import json
import os
import smtplib
import glob
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ALERT_EMAIL    = os.environ.get("ALERT_EMAIL", "")
GMAIL_USER     = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

def main():
    print("Collecte des alertes de tous les batches...")

    # Cherche tous les fichiers alerts.json dans les sous-dossiers
    all_alerts = []
    first_scan = False
    timestamp  = datetime.now().strftime('%d/%m/%Y a %H:%M')

    alert_files = glob.glob("all_alerts/alerts-batch-*/alerts.json")
    print("Fichiers trouves : " + str(len(alert_files)))

    for fpath in sorted(alert_files):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            batch_alerts = data.get("alerts", [])
            if data.get("first_scan"):
                first_scan = True
            print("  " + fpath + " -> " + str(len(batch_alerts)) + " alerte(s)")
            all_alerts.extend(batch_alerts)
        except Exception as e:
            print("  Erreur lecture " + fpath + " : " + str(e))

    print("Total alertes : " + str(len(all_alerts)))

    if not GMAIL_USER or not GMAIL_PASSWORD or not ALERT_EMAIL:
        print("Secrets non configures, pas d'envoi.")
        return

    scan_label = "PREMIER SCAN" if first_scan else "Scan"
    has_new    = len(all_alerts) > 0

    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"]   = ALERT_EMAIL

    if has_new:
        msg["Subject"] = "KitStock - " + str(len(all_alerts)) + " code(s) de retrait detecte(s)"
        rows = ""
        for a in all_alerts:
            if a.get("code"):
                code_html = '<span style="font-weight:bold;color:#e63946;background:#fff0f1;padding:4px 12px;border-radius:6px;font-size:15px;">&#128273; ' + a["code"] + '</span>'
            else:
                code_html = '<span style="color:#aaa;font-style:italic;">Non trouve - verifier manuellement</span>'
            rows += (
                "<tr>"
                '<td style="padding:10px 8px;border-bottom:1px solid #eee;font-family:monospace;font-size:13px;">' + a.get("email","") + "</td>"
                '<td style="padding:10px 8px;border-bottom:1px solid #eee;">' + a.get("locker","") + "</td>"
                '<td style="padding:10px 8px;border-bottom:1px solid #eee;">' + a.get("article","") + "</td>"
                '<td style="padding:10px 8px;border-bottom:1px solid #eee;color:#555;">' + a.get("subject","") + "</td>"
                '<td style="padding:10px 8px;border-bottom:1px solid #eee;text-align:center;">' + code_html + "</td>"
                "</tr>"
            )
        body_html = (
            '<div style="background:#fff8e1;border-left:4px solid #f59e0b;border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:20px;">'
            '<strong style="color:#92400e;">&#9888; ' + str(len(all_alerts)) + ' code(s) de retrait detecte(s) (' + scan_label + ')</strong>'
            "</div>"
            '<table style="border-collapse:collapse;width:100%;margin-bottom:24px;">'
            "<thead><tr style=\"background:#1d3557;color:white;\">"
            '<th style="padding:10px 8px;text-align:left;">Email Yopmail</th>'
            '<th style="padding:10px 8px;text-align:left;">Locker</th>'
            '<th style="padding:10px 8px;text-align:left;">Article</th>'
            '<th style="padding:10px 8px;text-align:left;">Sujet email</th>'
            '<th style="padding:10px 8px;text-align:center;">Code retrait</th>'
            "</tr></thead><tbody>" + rows + "</tbody></table>"
        )
    else:
        msg["Subject"] = "KitStock - Scan OK, aucun nouveau code"
        body_html = (
            '<div style="background:#f0fdf4;border-left:4px solid #22c55e;border-radius:0 8px 8px 0;padding:14px 18px;">'
            '<strong style="color:#166534;">&#10003; Aucun nouveau code de retrait detecte.</strong>'
            "</div>"
        )

    html = (
        "<html><body style=\"font-family:'Segoe UI',Arial,sans-serif;color:#222;background:#f5f5f5;padding:20px;\">"
        '<div style="max-width:960px;margin:0 auto;background:white;border-radius:12px;padding:28px;">'
        '<h2 style="color:#1d3557;margin-top:0;">&#128236; KitStock - Rapport de scan</h2>'
        '<p style="color:#666;margin-bottom:20px;">' + scan_label + ' du <strong>' + timestamp + '</strong></p>'
        + body_html +
        '<p style="color:#aaa;font-size:12px;margin-top:20px;">Scan automatique toutes les 5h - GitHub Actions</p>'
        "</div></body></html>"
    )

    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())
        print("Rapport unique envoye a " + ALERT_EMAIL)
    except Exception as e:
        print("ERREUR envoi : " + str(e))

if __name__ == "__main__":
    main()
