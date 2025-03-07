from celery import Celery
from flask import Flask, request, jsonify, render_template, send_file
import re
import urllib.request
import csv
import dns.resolver
import os
from werkzeug.utils import secure_filename
from flask_cors import CORS

# Flask App Setup
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"csv"}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Celery Configuration
app.config["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
app.config["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/0"

celery = Celery(app.name, broker=app.config["CELERY_BROKER_URL"])
celery.conf.update(app.config)

# Regex for email extraction
emailRegex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_email(email_address):
    """Validates an email using MX records and blacklist."""
    BLACKLISTED_DOMAINS = {"sentry.io", "example.com", "test.com"}

    try:
        domain = email_address.split('@')[1]
        
        if domain in BLACKLISTED_DOMAINS:
            return False  

        answers = dns.resolver.resolve(domain, 'MX', lifetime=5)  
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
        response = urllib.request.urlopen(request, timeout=10)  
        url_text = response.read().decode(errors='ignore')
        return [(name, email) for email in extract_valid_emails(url_text)]
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

@celery.task
def process_csv_task(file_path):
    """Processes a CSV file asynchronously using Celery."""
    unique_emails = {}

    with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
        csv_reader = csv.reader(csv_file)
        next(csv_reader, None)  

        for row in csv_reader:
            if len(row) >= 2:
                name, url = row[0].strip(), row[1].strip()
                extracted_emails = fetch_and_extract_emails(url, name)
                for extracted_name, email in extracted_emails:
                    unique_emails[email] = extracted_name  

    output_file = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")

    with open(output_file, 'w', newline='', encoding='utf-8') as csv_email_file:
        csv_writer = csv.writer(csv_email_file)
        csv_writer.writerow(["Name", "Email"])
        for email, name in unique_emails.items():  
            csv_writer.writerow([name, email])

    os.remove(file_path)  
    return output_file, list(unique_emails.items())

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles CSV file upload and processes it asynchronously."""
    if "file" not in request.files:
        return jsonify({"error": "No file part"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        task = process_csv_task.apply_async(args=[file_path])
        return jsonify({"task_id": task.id, "status": "Processing started"})

    return jsonify({"error": "Invalid file type. Please upload a CSV file."}), 400

@app.route("/task_status/<task_id>")
def task_status(task_id):
    """Checks the status of a Celery task."""
    task = process_csv_task.AsyncResult(task_id)
    if task.state == "PENDING":
        response = {"status": "Pending"}
    elif task.state == "SUCCESS":
        response = {"status": "Completed", "result": task.result}
    elif task.state == "FAILURE":
        response = {"status": "Failed", "error": str(task.info)}
    else:
        response = {"status": "Processing"}
    
    return jsonify(response)

@app.route("/result")
def result():
    file_name = request.args.get("file", "")
    return render_template("result.html", file_name=file_name)

@app.route("/download")
def download():
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], "emails.csv")
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name="emails.csv")
    return "File not found", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
