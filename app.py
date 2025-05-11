from flask import Flask, request
import requests
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Pobierz Account SID i Auth Token z zmiennych środowiskowych
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    raise ValueError("Ustaw zmienne środowiskowe TWILIO_ACCOUNT_SID i TWILIO_AUTH_TOKEN")

@app.route('/whatsapp', methods=['POST'])
def webhook():
    # Pobierz dane z żądania Twilio
    from_number = request.values.get('From')  # Numer nadawcy
    body = request.values.get('Body', '').lower()  # Treść wiadomości
    media_url = request.values.get('MediaUrl0')  # URL zdjęcia
    message_sid = request.values.get('MessageSid')  # Unikalny ID wiadomości

    # Debug: Wypisz dane żądania
    print(f"Numer nadawcy: {from_number}")
    print(f"Treść wiadomości: {body}")
    print(f"URL zdjęcia: {media_url}")
    print(f"Message SID: {message_sid}")

    # Sprawdź, czy jest zdjęcie
    if media_url:
        # Określ status płatności na podstawie treści wiadomości
        paid_status = 'T' if 'faktura zapłacona' in body else 'N'
        
        # Pobierz zdjęcie z autentykacją
        response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        if response.status_code == 200:
            image_path = os.path.join('invoices', f'invoice_{message_sid}_{paid_status}.jpg')
            with open(image_path, 'wb') as f:
                f.write(response.content)
            print(f"Zdjęcie zapisane: {image_path}, Status: {paid_status}")
        else:
            print(f"Błąd pobierania zdjęcia: Status {response.status_code}, Treść: {response.text}")
    
    return '', 200

if __name__ == '__main__':
    app.run(debug=True)