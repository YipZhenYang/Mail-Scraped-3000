"""
    Filename: app.py
    Description: A Flask-based backend for Mail Scraped 3000, handling file uploads, email extraction, validation, 
                 and CSV processing. Supports CORS for frontend integration.
    System Name: Mail Scraped 3000
    Version: 0.4
    Author: Yip Zhen Yang
    Date: March 7, 2025
"""

from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import os
import csv
import re
import urllib.request
import dns.resolver
import logging
from concurrent.futures import ThreadPoolExecutor
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"csv"}
MAX_WORKERS = 5  # Controls concurrency

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Setup logging
logging.basicConfig(level=logging.INFO)

# Email regex pattern
emailRegex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def allowed_file(filename):
    """Checks if uploaded file is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_email(email_address):
    """Validates an email using MX records and blacklist."""
    BLACKLISTED_DOMAINS = {"sentry.io", "example.com", "test.com"}

    try:
        domain = email_address.split('@')[1]

        if domain in BLACKLISTED_DOMAINS:
            return False  # Immediately reject blacklisted domains

        answers = dns.resolver.resolve(domain, 'MX', lifetime=10)  # Increased timeout
        return bool(answers)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False
    except Exception:
        return False


def extract_valid_emails(url_text):
    """Extracts unique, validated emails from webpage text."""
    extracted_emails = emailRegex.findall(url_text)
    valid_emails = {email for email in extracted_emails if validate_email(email)}
    return valid_emails


def fetch_and_extract_emails(url, name):
    """Fetches webpage content and extracts validated emails with names."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(url, None, headers)
        response = urllib.request.urlopen(request, timeout=5)  # Reduced timeout
        url_text = response.read().decode(errors='ignore')
        return [(name, email) for email in extract_valid_emails(url_text)]
    except urllib.error.URLError as e:
        logging.error(f"Network error for {url}: {e.reason}")
        return []
    except urllib.error.HTTPError as e:
        logging.error(f"HTTP error {e.code} for {url}: {e.reason}")
        return []
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return []


def process_csv(file_path):
    """Processes CSV file containing URLs and extracts emails."""
    output_file = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")

    with open(output_file, 'w', newline='', encoding='utf-8') as csv_email_file:
        csv_writer = csv.writer(csv_email_file)
        csv_writer.writerow(["Name", "Email"])

        with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            next(csv_reader, None)  # Skip header

            for row in csv_reader:
                if len(row) >= 2:
                    name, url = row[0].strip(), row[1].strip()
                    extracted_emails = fetch_and_extract_emails(url, name)
                    for extracted_name, email in extracted_emails:
                        csv_writer.writerow([extracted_name, email])  # Write directly

    os.remove(file_path)  # Delete uploaded file
    return output_file


@app.route('/')
def home():
    return render_template('index.html')


@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles CSV file upload and processes it."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        try:
            output_file, extracted_emails = process_csv(file_path)
            return jsonify({"file": output_file, "emails": extracted_emails})
        except Exception as e:
            logging.error(f"Processing error: {e}")
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500

    return jsonify({"error": "Invalid file type. Please upload a CSV file."}), 400


@app.route("/result")
def result():
    """Displays result page with a download link."""
    file_name = request.args.get("file", "")
    return render_template("result.html", file_name=file_name)


@app.route("/download")
def download():
    """Allows users to download the extracted email file."""
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="emails.csv")
    return "File not found", 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)  # Production-ready (debug=False)
