const express = require("express");
const multer = require("multer");
const cors = require("cors");
const fs = require("fs");
const path = require("path");
const dns = require("dns");
const csv = require("fast-csv");

const app = express();
app.use(cors());
app.use(express.static("public")); // Serve static files (like frontend HTML)
app.use(express.json());

// Upload folder setup
const UPLOAD_FOLDER = "uploads";
if (!fs.existsSync(UPLOAD_FOLDER)) {
    fs.mkdirSync(UPLOAD_FOLDER);
}

// Multer setup for file uploads
const storage = multer.diskStorage({
    destination: UPLOAD_FOLDER,
    filename: (req, file, cb) => {
        cb(null, Date.now() + "-" + file.originalname);
    },
});
const upload = multer({ storage });

// Email regex
const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;

// Blacklisted domains
const BLACKLISTED_DOMAINS = new Set(["sentry.io", "example.com", "test.com"]);

// Validate email by checking MX records
function validateEmail(email) {
    return new Promise((resolve) => {
        const domain = email.split("@")[1];
        if (BLACKLISTED_DOMAINS.has(domain)) return resolve(false);

        dns.resolveMx(domain, (err, addresses) => {
            resolve(!err && addresses && addresses.length > 0);
        });
    });
}

// Process CSV & Extract Emails
async function processCSV(filePath) {
    return new Promise((resolve, reject) => {
        const emails = new Set();
        const results = [];

        fs.createReadStream(filePath)
            .pipe(csv.parse({ headers: false }))
            .on("data", async (row) => {
                if (row.length >= 2) {
                    const name = row[0].trim();
                    const url = row[1].trim();
                    const extractedEmails = url.match(emailRegex) || [];
                    
                    for (const email of extractedEmails) {
                        if (!(email in emails) && await validateEmail(email)) {
                            emails.add(email);
                            results.push([name, email]);
                        }
                    }
                }
            })
            .on("end", () => {
                const outputFilePath = path.join(UPLOAD_FOLDER, "emails.csv");
                const ws = fs.createWriteStream(outputFilePath);
                csv.write([["Name", "Email"], ...results], { headers: true }).pipe(ws);
                resolve({ outputFilePath, results });
            })
            .on("error", reject);
    });
}

// Upload route
app.post("/upload", upload.single("file"), async (req, res) => {
    if (!req.file) return res.status(400).json({ error: "No file uploaded" });

    try {
        const { outputFilePath, results } = await processCSV(req.file.path);
        res.json({ file: outputFilePath, emails: results });
    } catch (err) {
        res.status(500).json({ error: "Error processing file" });
    }
});

// Download route
app.get("/download", (req, res) => {
    const file = req.query.file;
    if (fs.existsSync(file)) {
        return res.download(file);
    }
    res.status(404).send("File not found");
});

// Serve HTML frontend (upload page)
app.get("/", (req, res) => {
    res.sendFile(path.join(__dirname, "public", "index.html"));
});

// Start server
const PORT = 3000;
app.listen(PORT, () => console.log(`🚀 Server running on http://localhost:${PORT}`));
