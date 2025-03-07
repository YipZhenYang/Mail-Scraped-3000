"""
    Filename: app.py
    Description: A Flask-based backend for Mail Scraped 3000, handling file uploads, email extraction, validation, 
                 and CSV processing. Supports CORS for frontend integration.
    System Name: Mail Scraped 3000
    Version: 1.2
    Author: Yip Zhen Yang
    Date: March 7, 2025
"""

import os
import csv
import re
import urllib.request
import dns.resolver
import logging
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"csv"}
MAX_WORKERS = os.cpu_count() // 2 or 1  # Dynamic threading
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # Fixed to 50MB
REQUEST_TIMEOUT = 900

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE

# Setup logging
logging.basicConfig(level=logging.INFO)

# Email regex pattern
emailRegex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# Blacklisted domains
BLACKLISTED_DOMAINS = {"sentry.io", "example.com", "test.com"}

def allowed_file(filename):
    """Checks if uploaded file is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_email(email_address):
    """Validates an email using MX records and blacklist."""
    try:
        domain = email_address.split('@')[1]
        if domain in BLACKLISTED_DOMAINS:
            return False
        answers = dns.resolver.resolve(domain, 'MX', lifetime=5)
        return bool(answers)
    except:
        return False

def extract_valid_emails(url_text):
    """Extracts unique, validated emails from webpage text."""
    return {email for email in emailRegex.findall(url_text) if validate_email(email)}

def fetch_and_extract_emails(url, name):
    """Fetches webpage content and extracts validated emails with names."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(url, None, headers)
        response = urllib.request.urlopen(request, timeout=10)
        url_text = response.read().decode(errors='ignore')
        return [(name, email) for email in extract_valid_emails(url_text)]
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return []

def process_csv(file_path):
    """Processes a CSV file containing URLs and extracts unique emails in parallel."""
    unique_emails = {}
    with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
        csv_reader = csv.reader(csv_file)
        next(csv_reader, None)  # Skip header
        tasks = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for row in csv_reader:
                if len(row) < 2:
                    continue
                tasks.append(executor.submit(fetch_and_extract_emails, row[1].strip(), row[0].strip()))
            for future in as_completed(tasks):
                try:
                    for extracted_name, email in future.result():
                        unique_emails[email] = extracted_name
                except Exception as e:
                    logging.error(f"Task processing error: {e}")
    output_file = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    with open(output_file, 'w', newline='', encoding='utf-8') as csv_email_file:
        csv_writer = csv.writer(csv_email_file)
        csv_writer.writerow(["Name", "Email"])
        for email, name in unique_emails.items():
            csv_writer.writerow([name, email])
    os.remove(file_path)  # Delete uploaded file
    return output_file, list(unique_emails.items())

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
        try:
            file.save(file_path)
            output_file, extracted_emails = process_csv(file_path)
            return jsonify({"file": output_file, "emails": extracted_emails})
        except Exception as e:
            logging.error(f"Processing error: {e}")
            return jsonify({"error": "Internal server error"}), 500
    return jsonify({"error": "Invalid file type. Please upload a CSV file."}), 400

@app.route("/download")
def download():
    """Allows users to download the extracted email file."""
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    return send_file(file_path, as_attachment=True, download_name="emails.csv") if os.path.exists(file_path) else ("File not found", 404)

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(error):
    """Handles file size limit errors."""
    return jsonify({"error": "File too large. Maximum allowed size is 50MB."}), 413

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)