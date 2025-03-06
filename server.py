"""
    Filename: app.py
    Description: A Flask-based backend for Mail Scraped 3000, handling file uploads, email extraction, validation, 
                 and CSV processing. Supports CORS for frontend integration.
    System Name: Mail Scraped 3000
    Version: 0.3
    Author: Yip Zhen Yang
    Date: March 6, 2025
"""

from flask import Flask, request, jsonify, render_template, send_file
import re
import urllib.request
import csv
import dns.resolver
import os
import logging
from werkzeug.utils import secure_filename
from flask_cors import CORS
import time

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"csv"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_email(email_address):
    """Validates an email using MX records and blacklist."""
    BLACKLISTED_DOMAINS = {"sentry.io", "example.com", "test.com"}

    try:
        domain = email_address.split('@')[1]
        
        if domain in BLACKLISTED_DOMAINS:
            return False

        answers = dns.resolver.resolve(domain, 'MX', lifetime=3)  # Reduce timeout to 3s
        return bool(answers)
    
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False
    except Exception as e:
        app.logger.error(f"Unexpected error during email validation: {e}")
        return False

def extract_valid_emails(url_text):
    """Extracts unique, validated emails from webpage text."""
    emailRegex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}')
    extracted_emails = emailRegex.findall(url_text)
    valid_emails = {email for email in extracted_emails if validate_email(email)}
    return valid_emails

def fetch_and_extract_emails(url, name, index):
    """Fetches webpage content and extracts validated emails with names."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(url, None, headers)
        response = urllib.request.urlopen(request, timeout=15)  # Set timeout to 15 seconds
        url_text = response.read().decode(errors='ignore')
        emails = extract_valid_emails(url_text)
        
        print(f"✅ Done {index}: {len(emails)} emails found from {url}")
        return [(name, email) for email in emails]

    except Exception as e:
        app.logger.error(f"❌ Error fetching {url}: {e}")
    
    print(f"⚠️ Skipped {index}: Error fetching {url}")
    return []

def process_csv_in_batches(file_path, batch_size=10):
    """Processes a CSV file in batches of URLs, appending results to emails.csv."""
    try:
        with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            next(csv_reader, None)  # Skip header
            url_batches = []
            
            for index, row in enumerate(csv_reader, start=1):
                if len(row) >= 2:
                    url_batches.append((row[0].strip(), row[1].strip()))
                    
                    if len(url_batches) == batch_size:
                        process_batch(url_batches)
                        url_batches = []
                        time.sleep(2)  # Pause to avoid rate limits
            
            if url_batches:
                process_batch(url_batches)
        
        os.remove(file_path)
    except Exception as e:
        app.logger.error(f"❌ Error processing CSV file: {e}")

def process_batch(batch):
    """Processes a batch of URLs and appends results to emails.csv."""
    unique_emails = {}
    
    for index, (name, url) in enumerate(batch, start=1):
        extracted_emails = fetch_and_extract_emails(url, name, index)
        for extracted_name, email in extracted_emails:
            unique_emails[email] = extracted_name
    
    output_file = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    with open(output_file, 'a', newline='', encoding='utf-8') as csv_email_file:
        csv_writer = csv.writer(csv_email_file)
        for email, name in unique_emails.items():  
            csv_writer.writerow([name, email])

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
            process_csv_in_batches(file_path)
            return jsonify({"message": "File processed successfully"})
        except Exception as e:
            app.logger.error(f"❌ Internal server error: {e}")
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500

    return jsonify({"error": "Invalid file type. Please upload a CSV file."}), 400

@app.route("/download")
def download():
    """Allows users to download the extracted email file."""
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="emails.csv")
    
    return "File not found", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
