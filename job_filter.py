"""
Fetches JobStreet email alerts from Gmail via IMAP, runs them through
Gemini to extract and filter relevant listings, then saves matches
to a Notion database.
"""

import os
import json
import imaplib
import email
import re
import time
from email.header import decode_header
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

import google.generativeai as genai
from notion_client import Client as NotionClient
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
CANDIDATE_PROFILE = os.environ.get("CANDIDATE_PROFILE", "")

FILTER_PROMPT = """
Kamu adalah AI job screener yang membantu fresh graduate menemukan lowongan yang relevan.

Profil kandidat:
{profile}

TUGAS:
1. Ekstrak SEMUA job listing dari konten email berikut
2. Nilai setiap job apakah COCOK atau TIDAK COCOK untuk kandidat di atas

KRITERIA TIDAK COCOK — tolak jika memenuhi salah satu:
• Memerlukan pengalaman kerja 2 tahun atau lebih
  [PENGECUALIAN: jika ada kata "fresh graduate", "baru lulus", "management trainee",
   "grad program", "fresh grad welcome", "0-2 tahun" → tetap COCOK]
• Level jabatan: Senior, Lead, Manager, Head, Director, VP, Principal, Chief
• Role tidak relevan: sales lapangan, driver, kurir, operator mesin, security, teknisi lapangan
• Industri tidak relevan: manufaktur berat, perkebunan, pertambangan, konstruksi
  [PENGECUALIAN: jika perusahaan tersebut memiliki divisi IT/Digital → bisa COCOK]

KRITERIA COCOK — nilai tinggi jika memenuhi:
• Menerima fresh graduate / 0-1 tahun / trainee / graduate hire
• Role relevan: Business Analyst, Data Analyst, AI/ML, ERP Consultant, Product Analyst,
  IT Consultant, System Analyst, RPA Analyst, BI Analyst, Data Scientist (junior)
• Industri relevan: teknologi, telekomunikasi, konsultan IT, perbankan/fintech, startup, BUMN IT

Konten email JobStreet (link asli ditandai dengan format [LINK: url]):
{email_text}

PENTING soal LINK:
• Setiap job listing biasanya diikuti oleh penanda [LINK: url] di dekat judulnya
• Ambil URL tersebut APA ADANYA, jangan diubah atau disingkat
• Jika untuk satu job ada beberapa [LINK: ...] (misal logo + judul), pakai salah satu
  yang paling relevan (biasanya yang menyertai judul pekerjaan)
• Jika benar-benar tidak ada link yang cocok untuk suatu job, isi dengan string kosong ""

PENTING: Jawab HANYA dengan JSON array yang valid.
Tidak boleh ada teks lain, penjelasan, atau markdown backtick (```).

Format response:
[
  {{
    "status": "COCOK" atau "TIDAK COCOK",
    "score": <angka 0-100, semakin tinggi semakin relevan>,
    "job_title": "<judul pekerjaan dari listing>",
    "company": "<nama perusahaan>",
    "location": "<kota atau Remote>",
    "experience_required": "<pengalaman yang dibutuhkan, contoh: Fresh Graduate, 0-1 tahun>",
    "reason": "<alasan singkat 1-2 kalimat kenapa cocok atau tidak>",
    "highlight": "<hal menarik dari job ini jika COCOK — string kosong jika TIDAK COCOK>",
    "link": "<URL lowongan dari penanda [LINK: ...] — string kosong jika tidak ditemukan>"
  }}
]
"""


def fetch_jobstreet_emails(days_back: int = 1) -> list[dict]:
    """Fetch recent JobStreet alert emails from Gmail via IMAP."""
    print("Connecting to Gmail...")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
    except imaplib.IMAP4.error as e:
        print(f"  Login gagal: {e}")
        print("  Pastikan IMAP aktif dan App Password sudah benar.")
        return []
    except Exception as e:
        print(f"  Koneksi gagal: {e}")
        return []

    since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    _, msg_ids = mail.search(None, f'FROM "jobstreet" SINCE {since_date}')

    msg_id_list = msg_ids[0].split()
    print(f"  Ditemukan {len(msg_id_list)} email")

    emails = []
    for msg_id in msg_id_list:
        try:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject_raw = msg.get("Subject", "No Subject")
            decoded, enc = decode_header(subject_raw)[0]
            subject = decoded.decode(enc or "utf-8") if isinstance(decoded, bytes) else str(decoded)

            body = _extract_email_body(msg)
            if body:
                emails.append({
                    "id": msg_id.decode(),
                    "subject": subject,
                    "body": body
                })
        except Exception as e:
            print(f"  Gagal baca email {msg_id}: {e}")
            continue

    mail.close()
    mail.logout()
    return emails


def _extract_email_body(msg) -> str:
    """Pull HTML or plain text body from an email message."""
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                decoded = payload.decode("utf-8", errors="ignore")
                if content_type == "text/html" and not html_body:
                    html_body = decoded
                elif content_type == "text/plain" and not text_body:
                    text_body = decoded
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                text_body = payload.decode("utf-8", errors="ignore")
        except Exception:
            pass

    return html_body if html_body else text_body


def html_to_clean_text(html: str, max_chars: int = 7000) -> str:
    """
    Convert HTML email to clean text for AI processing.
    Preserves job listing URLs inline as [LINK: url] markers so Gemini
    can match each listing to its original link.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "head", "img", "meta"]):
        tag.decompose()

    # Inject link URLs inline so the AI can associate them with job titles
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        skip = ["unsubscribe", "mailto:", "facebook.com", "twitter.com",
                "instagram.com", "linkedin.com/company", "preferences"]
        if href.startswith("http") and not any(k in href.lower() for k in skip):
            a_tag.append(f" [LINK: {href}]")

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip()

    return text[:max_chars]


def filter_jobs_with_gemini(email_text: str, max_retries: int = 2) -> list[dict]:
    """Send email content to Gemini to extract and score job listings."""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = FILTER_PROMPT.format(
        profile=CANDIDATE_PROFILE,
        email_text=email_text
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(prompt)
            raw = response.text.strip()

            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\n?```\s*$', '', raw, flags=re.MULTILINE)
            raw = raw.strip()

            jobs = json.loads(raw)
            return jobs if isinstance(jobs, list) else [jobs]

        except json.JSONDecodeError as e:
            print(f"  JSON parse gagal (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                print(f"  Gagal parse response setelah {max_retries}x")
                return []

        except Exception as e:
            print(f"  Gemini API error: {e}")
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                print("  Rate limited, waiting 60s...")
                time.sleep(60)
            return []

    return []


def _score_label(score: int) -> str:
    if score >= 80: return "Priority"
    if score >= 60: return "Good"
    if score >= 40: return "Maybe"
    return "Skip"


def _clean_url(url: str) -> str | None:
    """Validate URL before sending to Notion (it rejects malformed ones)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return None
    return url


def is_job_duplicate(notion: NotionClient, job_title: str, company: str) -> bool:
    try:
        results = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "and": [
                    {
                        "property": "Name",
                        "title": {"contains": job_title[:50]}
                    },
                    {
                        "property": "Company",
                        "rich_text": {"contains": company[:30]}
                    }
                ]
            }
        )
        return len(results["results"]) > 0
    except Exception:
        return False


def add_job_to_notion(notion: NotionClient, job: dict) -> bool:
    try:
        score = int(job.get("score", 0))
        label = _score_label(score)
        link = _clean_url(job.get("link", ""))

        properties = {
            "Name": {
                "title": [{"text": {"content": str(job.get("job_title", "Unknown Role"))[:100]}}]
            },
            "Company": {
                "rich_text": [{"text": {"content": str(job.get("company", "-"))[:100]}}]
            },
            "Location": {
                "rich_text": [{"text": {"content": str(job.get("location", "-"))[:100]}}]
            },
            "Score": {
                "number": score
            },
            "Label": {
                "select": {"name": label}
            },
            "Experience Required": {
                "rich_text": [{"text": {"content": str(job.get("experience_required", "-"))[:200]}}]
            },
            "Reason": {
                "rich_text": [{"text": {"content": str(job.get("reason", "-"))[:500]}}]
            },
            "Highlight": {
                "rich_text": [{"text": {"content": str(job.get("highlight", "-"))[:500]}}]
            },
            "Status": {
                "select": {"name": "New"}
            },
            "Date Found": {
                "date": {"start": datetime.now().strftime("%Y-%m-%d")}
            }
        }

        if link:
            properties["Link"] = {"url": link}

        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=properties
        )
        return True
    except Exception as e:
        print(f"  Notion error: {e}")
        return False


def validate_env() -> bool:
    required = {
        "GMAIL_USER": GMAIL_USER,
        "GMAIL_APP_PASSWORD": GMAIL_APP_PASSWORD,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "NOTION_TOKEN": NOTION_TOKEN,
        "NOTION_DATABASE_ID": NOTION_DATABASE_ID,
        "CANDIDATE_PROFILE": CANDIDATE_PROFILE,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        print("Lihat SETUP.md untuk panduan konfigurasi.")
        return False
    return True


def main():
    print(f"\n--- JobStreet Filter | {datetime.now().strftime('%Y-%m-%d %H:%M')} ---\n")

    if not validate_env():
        return

    notion = NotionClient(auth=NOTION_TOKEN)

    emails = fetch_jobstreet_emails(days_back=1)
    if not emails:
        print("Tidak ada email baru.")
        return

    total_extracted = 0
    total_added = 0
    total_filtered = 0

    for i, em in enumerate(emails, 1):
        print(f"\n[{i}/{len(emails)}] {em['subject'][:65]}")

        email_text = html_to_clean_text(em["body"])
        if not email_text.strip():
            print("  Email kosong, skip.")
            continue

        print("  Analyzing with Gemini...")
        jobs = filter_jobs_with_gemini(email_text)

        if not jobs:
            print("  Tidak ada job diekstrak.")
            continue

        print(f"  {len(jobs)} job ditemukan\n")
        total_extracted += len(jobs)

        for job in jobs:
            title = str(job.get("job_title", "Unknown"))
            company = str(job.get("company", "Unknown"))
            status = job.get("status", "TIDAK COCOK")
            score = int(job.get("score", 0))

            if status == "COCOK":
                if is_job_duplicate(notion, title, company):
                    print(f"  [dup]  {score:3}/100  {title[:40]} @ {company[:25]}")
                    total_filtered += 1
                    continue

                if add_job_to_notion(notion, job):
                    total_added += 1
                    has_link = "+" if _clean_url(job.get("link", "")) else "-"
                    print(f"  [add]  {score:3}/100  {title[:35]} @ {company[:20]} [{has_link}link]")
                    highlight = job.get("highlight", "")
                    if highlight:
                        print(f"         ^ {highlight[:75]}")
                else:
                    print(f"  [err]  {score:3}/100  {title[:40]} @ {company[:25]} (notion failed)")
            else:
                total_filtered += 1
                print(f"  [skip] {score:3}/100  {title[:40]} @ {company[:25]}")

        if i < len(emails):
            time.sleep(2)

    print(f"\n--- Done: {len(emails)} emails, {total_extracted} extracted, "
          f"{total_added} added, {total_filtered} filtered ---\n")


if __name__ == "__main__":
    main()