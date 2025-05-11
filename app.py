from flask import Flask, request
import os
import requests
from invoice_tracker import process_invoice  # Assuming this function exists
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "Invoice processing webhook is live."

@app.route("/whatsapp", methods=["POST"])
def webhook():
    sender_number = request.form.get("From")
    message_sid = request.form.get("MessageSid")
    media_url = request.form.get("MediaUrl0")
    message_body = request.form.get("Body")

    print(f"Numer nadawcy: {sender_number}")
    print(f"Treść wiadomości: {message_body}")
    print(f"URL zdjęcia: {media_url}")
    print(f"Message SID: {message_sid}")

    if media_url:
        try:
            response = requests.get(media_url, auth=(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH_TOKEN")))

            # Use safe temp directory
            image_dir = "/tmp/invoices"
            os.makedirs(image_dir, exist_ok=True)

            image_path = os.path.join(image_dir, f"invoice_{message_sid}_N.jpg")
            with open(image_path, 'wb') as f:
                f.write(response.content)

            print(f"Saved invoice to {image_path}")

            # Call your processing logic
            process_invoice(image_path)

        except Exception as e:
            print(f"Error processing invoice: {e}")

    return "OK", 200
