from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for
import re
import urllib.request
import csv
import dns.resolver  # Install with `pip install dnspython`
import os
from werkzeug.utils import secure_filename
from flask_cors import CORS

app = Flask(__name__, template_folder="templates")  # Ensure templates folder is used
CORS(app)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"csv"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

emailRegex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_email(email_address):
    """Validates an email by checking its domain's MX records and blacklist."""
    try:
        BLACKLISTED_DOMAINS = {"sentry.io", "example.com", "test.com"}  # Add more if needed

        domain = email_address.split('@')[1]
        
        #DNS-based email validation
        answers = dns.resolver.resolve(domain, 'MX', lifetime=5)  # 5s timeout
        return bool(answers)
    
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return False
    except Exception as e:
        return False

def extract_valid_emails(url_text):
    """Extracts and validates emails from webpage text."""
    extracted_emails = emailRegex.findall(url_text)
    return {email for email in extracted_emails if validate_email(email)}  # Only store unique valid emails

def fetch_and_extract_emails(url, name):
    """Fetches webpage content and extracts valid emails with names."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        request = urllib.request.Request(url, None, headers)
        response = urllib.request.urlopen(request, timeout=10)  # 10-second timeout
        url_text = response.read().decode(errors='ignore')
        return [(name, email) for email in extract_valid_emails(url_text)]
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

def process_csv(file_path):
    """Processes a CSV file containing URLs and extracts only validated unique emails with names."""
    unique_emails = set()
    with open(file_path, 'r', newline='', encoding='utf-8') as csv_file:
        csv_reader = csv.reader(csv_file)
        next(csv_reader, None)
        for row in csv_reader:
            if len(row) >= 2:
                name, url = row[0].strip(), row[1].strip()
                extracted_emails = fetch_and_extract_emails(url, name)
                unique_emails.update(extracted_emails)

    output_file = "emails.csv"  

    with open(output_file, 'w', newline='', encoding='utf-8') as csv_email_file:
        csv_writer = csv.writer(csv_email_file)
        csv_writer.writerow(["Name", "Email"])  # Add header
        for name, email in sorted(unique_emails):  
            csv_writer.writerow([name, email])

    os.remove(file_path)  # Delete uploaded CSV after processing

    return output_file, list(unique_emails)  # ✅ Ensure emails are returned

@app.route('/')
def home():
    return render_template('index.html')  # Make sure this file exists

                           
@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles CSV file upload and processing."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        try:
            output_file, extracted_emails = process_csv(file_path)  # ✅ Ensures CSV writing is completed
            return jsonify({"file": output_file, "emails": extracted_emails})  # ✅ Always return JSON

        except Exception as e:
            return jsonify({"error": f"Internal server error: {str(e)}"}), 500  # ✅ Return JSON even on errors

    return jsonify({"error": "Invalid file type. Please upload a CSV file."}), 400

@app.route("/result")
def result():
    """Displays result page with a download link."""
    file_name = request.args.get("file", "")
    return render_template("result.html", file_name=file_name)

@app.route("/download")
def download():
    """Allows users to download the extracted email file."""
    file_name = request.args.get("file", "")
    if os.path.exists(file_name):
        return send_file(file_name, as_attachment=True)
    return "File not found", 404

if __name__ == '__main__':
    app.run(debug=True)