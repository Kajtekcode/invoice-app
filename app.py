from flask import Flask, request
import os
import requests
from track_prices2 import process_invoice  # ✅ updated import

app = Flask(__name__)

@app.route('/whatsapp', methods=['POST'])
def webhook():
    # Extract relevant info from WhatsApp message via Twilio
    sender = request.form.get('From')
    message_sid = request.form.get('MessageSid')
    image_url = request.form.get('MediaUrl0')
    
    print(f"Numer nadawcy: {sender}")
    print(f"Message SID: {message_sid}")
    print(f"URL zdjęcia: {image_url}")

    if not image_url:
        return "No image found", 400

    # Set up temporary storage path
    invoices_dir = "/tmp/invoices"
    os.makedirs(invoices_dir, exist_ok=True)

    filename = f"invoice_{message_sid}_N.jpg"
    image_path = os.path.join(invoices_dir, filename)

    # Download the image from Twilio
    try:
        response = requests.get(image_url, auth=(os.environ.get("TWILIO_SID"), os.environ.get("TWILIO_AUTH_TOKEN")))
        response.raise_for_status()
        with open(image_path, 'wb') as f:
            f.write(response.content)
    except Exception as e:
        print(f"Error downloading image: {e}")
        return "Failed to download image", 500

    # Process the invoice using your function
    try:
        process_invoice(image_path)
    except Exception as e:
        print(f"Error processing invoice: {e}")
        return "Invoice processing failed", 500

    return "Invoice received and processed", 200

@app.route('/')
def home():
    return "Invoice Webhook is running!"

if __name__ == '__main__':
    app.run(debug=True)
