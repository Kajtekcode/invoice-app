import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI
import os
import json
from google.cloud import vision
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import requests.exceptions
from dotenv import load_dotenv

# Configuration for Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
gspread_client = gspread.authorize(creds)
spreadsheet = gspread_client.open_by_key('1GrLufeQeZMwP9vd3OYA2zhzh50FOiNFePWtP0PbCCXk')

# Configuration for xAI API
xai_client = OpenAI(
    api_key=os.environ.get('XAI_API_KEY'),
    base_url="https://api.x.ai/v1"
)

def detect_text(image_path):
    os.environ["GRPC_POLL_STRATEGY"] = "poll"
    client_vision = vision.ImageAnnotatorClient()
    with open(image_path, 'rb') as image_file:
        content = image_file.read()
    image = vision.Image(content=content)
    response = client_vision.text_detection(image=image)
    return response.text_annotations[0].description if response.text_annotations else ""

def parse_invoice_text(text, paid_status):
    # Unchanged, included for completeness
    prompt = f"""
    Masz tekst z polskiej faktury. Wyodrębnij dane w formacie JSON, dokładnie przestrzegając struktury poniżej:
    {{
        "ingredients": [
            {{
                "name": "nazwa składnika",
                "unit": "kg|l|szt|zgrz|kart",
                "net_price_per_unit": liczba_zmiennoprzecinkowa,
                "vat_percent": liczba_zmiennoprzecinkowa,
                "gross_price_per_unit": liczba_zmiennoprzecinkowa,
                "category": "JEDZENIE|NAPOJE|NAPOJE ALKOHOLOWE|CHEMIA|INNE"
            }},
            ...
        ],
        "invoice_date": "DD.MM.YYYY",
        "due_date": "DD.MM.YYYY",
        "total": liczba_zmiennoprzecinkowa,
        "paid": "T|N",
        "seller": "nazwa sprzedawcy",
        "category": "JEDZENIE|NAPOJE|NAPOJE ALKOHOLOWE|CHEMIA|INNE",
        "invoice_number": "numer faktury"
    }}
    Tekst faktury: {text}
    Status płatności: {paid_status}
    - 'ingredients':
      - 'name': Nazwa składnika (np. 'Kukurydza kolby 2,5kg Oerlemans').
      - 'unit': Jednostka miary (np. 'kg', 'l', 'szt', 'zgrz', 'kart').
      - 'net_price_per_unit': Cena netto za jednostkę miary (kolumna 'Cena netto').
      - 'vat_percent': Stawka VAT w procentach (np. 5, 8, 23).
      - 'gross_price_per_unit': Cena brutto za jednostkę (net_price_per_unit + net_price_per_unit * vat_percent/100).
      - 'category': Kategoria składnika.
    - Ignoruj sumy pozycji, ceny brutto dla całej ilości i ilość (np. 2 szt.).
    - 'invoice_date': Znajdź datę wystawienia faktury. Może być oznaczona jako 'Data wystawienia', 'Data sprzedaży', 'Data dokumenty sprzedaży/wydania', lub występować samodzielnie (np. '10.04.2025'). Jeśli niejasna, wybierz najbardziej prawdopodobną datę w formacie DD.MM.YYYY lub DD/MM/YYYY.
    - 'due_date': Znajdź datę płatności. Może być oznaczona jako 'Termin płatności', 'Płatne do', lub podana w formie 'Płatność X dni' (np. 'Płatność 7 dni'). Jeśli podano 'Płatność X dni', oblicz jako 'invoice_date' plus X dni. Jeśli brak, przyjmij 'invoice_date' plus 7 dni. Użyj formatu DD.MM.YYYY.
    - 'invoice_number': Znajdź numer faktury. Może być oznaczony jako 'Numer faktury', 'Faktura', lub nieoznaczony. Często zaczyna się na 'FV' (np. 'FV/2025/04/095', '2025/04/095'). Znajdź ciąg znaków z cyframi, ukośnikami, myślnikami lub literami 'FV', który wygląda jak numer dokumentu (np. '2025/04/095', '051/04/2025'). Jeśli brak, ustaw na pusty string ('').
    - Przykłady dat:
      - 'FAKTURA VAT 051/04/2025, Termin płatności 01.05.2025' → "invoice_date": "10.04.2025", "due_date": "01.05.2025", "invoice_number": "051/04/2025"
      - 'Data wystawienia: 15.04.2025, Płatność 10 dni, Numer faktury: FV/2025/123' → "invoice_date": "15.04.2025", "due_date": "25.04.2025", "invoice_number": "FV/2025/123"
      - '20.04.2025, Faktura 2025-04-095' → "invoice_date": "20.04.2025", "due_date": "27.04.2025", "invoice_number": "2025-04-095"
    - Kategorie składników:
      - JEDZENIE: produkty spożywcze (np. kukurydza, tuńczyk, makaron, mąka, mięso, sery, chorizo, sałaty).
      - NAPOJE: napoje bezalkoholowe (np. woda, sok limonkowy, lemoniada).
      - NAPOJE ALKOHOLOWE: alkohol (np. wino, piwo, wódka).
      - CHEMIA: środki czystości, chemikalia.
      - INNE: pozostałe (np. opakowania, usługi).
    - Przykłady kategorii:
      - 'Woda źródlana gazowana 1,5Lx6szt Soleo' → NAPOJE
      - 'Sok 100% limonkowy z 44 limonek 1L Polenghi' → NAPOJE
      - 'Kukurydza kolby 2,5kg Oerlemans' → JEDZENIE
      - 'Pieprz czarny młotkowany 700g Horeca Aroma' → JEDZENIE
    - Kategoria faktury na podstawie dominującej kategorii składników.
    - Ignoruj pozycje, które nie są składnikami (np. rabaty, usługi).
    - Odpowiedz TYLKO poprawnym JSON-em, bez żadnego dodatkowego tekstu, komentarzy, znaków ```json ani innych elementów.
    - Jeśli dane są niejasne, pomiń niepewne pozycje, ale zachowaj poprawną strukturę JSON.
    """
    response = xai_client.chat.completions.create(
        model="grok-3-beta",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000
    )
    raw_response = response.choices[0].message.content
    print("Surowa odpowiedź Grok:", raw_response)
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        print("Błąd: Grok nie zwrócił poprawnego JSON")
        return None

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.exceptions.ConnectionError))
def get_worksheet(spreadsheet, title):
    return spreadsheet.worksheet(title)

def format_price(value):
    """Format a number to Polish decimal format (e.g., 717.88 -> '717,88')."""
    try:
        return f"{float(value):.2f}".replace('.', ',')
    except (ValueError, TypeError):
        print(f"Warning: Invalid price value {value}, returning '0,00'")
        return '0,00'

def parse_sheet_price(price):
    """Parse a price from the sheet, handling various formats."""
    if not price:
        return 0.0
    try:
        # Convert to string and remove any whitespace
        price_str = str(price).strip()
        # Replace comma with dot for float conversion
        price_str = price_str.replace(',', '.')
        # Remove any thousand separators (e.g., spaces or dots in some locales)
        price_str = price_str.replace(' ', '')
        return float(price_str)
    except (ValueError, TypeError) as e:
        print(f"Warning: Failed to parse price '{price}': {e}")
        return 0.0

def update_or_append_ingredient(sheet, ingredient, invoice_date, seller):
    records = sheet.get_all_records()
    for i, record in enumerate(records, start=2):
        if record['Składnik'] == ingredient['name']:
            # Convert sheet price to float for comparison
            try:
                sheet_net_price = parse_sheet_price(record['Cena netto (za JM)'])
            except ValueError:
                continue  # Skip invalid price entries
            if abs(sheet_net_price - ingredient['net_price_per_unit']) < 0.01:
                return  # Prices match, no update needed
            else:
                # Update existing row with formatted prices
                sheet.update(
                    range_name=f'A{i}:G{i}',
                    values=[[
                        invoice_date,
                        ingredient['name'],
                        ingredient['unit'],
                        format_price(ingredient['net_price_per_unit']),
                        ingredient['vat_percent'],
                        format_price(ingredient['gross_price_per_unit']),
                        seller
                    ]]
                )
                return
    # Append new row with formatted prices
    sheet.append_row([
        invoice_date,
        ingredient['name'],
        ingredient['unit'],
        format_price(ingredient['net_price_per_unit']),
        ingredient['vat_percent'],
        format_price(ingredient['gross_price_per_unit']),
        seller
    ])

def calculate_days_to_due(due_date):
    try:
        due = datetime.strptime(due_date, '%d.%m.%Y')
        today = datetime.now()
        days_left = (due - today).days
        return days_left, None
    except ValueError:
        return None, "Błąd daty"

def sync_invoice_status():
    unpaid_sheet = get_worksheet(spreadsheet, "Faktury Niezapłacone")
    paid_sheet = get_worksheet(spreadsheet, "Faktury Zapłacone")
    unpaid_data = unpaid_sheet.get_all_records()
    rows_to_move = []

    # Identify rows to move from "Unpaid" to "Paid"
    for i, row in enumerate(unpaid_data, start=2):
        if row['Opłacona (T/N)'] == 'T':
            try:
                kwota_float = parse_sheet_price(row['Kwota Całkowita (PLN)'])
            except ValueError:
                print(f"Warning: Skipping row {i} due to invalid price: {row['Kwota Całkowita (PLN)']}")
                continue
            rows_to_move.append((i, [
                row['Data Wystawienia'],
                row.get('Numer Faktury', ''),
                row['Sprzedawca'],
                format_price(kwota_float),
                row['Kategoria'],
                row['Termin Płatności'],
                row['Opłacona (T/N)'],
                ""
            ]))

    # Move rows to "Paid" sheet and delete from "Unpaid" sheet
    for row_idx, row_data in reversed(rows_to_move):
        paid_sheet.append_row(row_data)
        unpaid_sheet.delete_rows(row_idx)

    # Refresh and sort "Unpaid" sheet
    unpaid_data = unpaid_sheet.get_all_records()
    sorted_data = sorted(unpaid_data, key=lambda x: float(str(x['Dni do Zapłaty']).replace(',', '.')) if str(x['Dni do Zapłaty']).replace(',', '.').replace('.', '', 1).isdigit() else float('inf'))

    if sorted_data:
        unpaid_sheet.clear()
        unpaid_sheet.append_row([
            "Data Wystawienia", "Numer Faktury", "Sprzedawca", "Kwota Całkowita (PLN)",
            "Kategoria", "Termin Płatności", "Opłacona (T/N)", "Dni do Zapłaty"
        ])
        for row in sorted_data:
            try:
                kwota_float = parse_sheet_price(row['Kwota Całkowita (PLN)'])
            except ValueError:
                print(f"Warning: Skipping row with invalid price: {row['Kwota Całkowita (PLN)']}")
                continue
            unpaid_sheet.append_row([
                row['Data Wystawienia'],
                row.get('Numer Faktury', ''),
                row['Sprzedawca'],
                format_price(kwota_float),
                row['Kategoria'],
                row['Termin Płatności'],
                row['Opłacona (T/N)'],
                str(row['Dni do Zapłaty'])
            ])

if __name__ == "__main__":
    sync_invoice_status()
    invoice_folder = "invoices"
    invoice_files = [f for f in os.listdir(invoice_folder) if f.lower().endswith(('.jpg', '.png'))]
    if not invoice_files:
        print("Brak zdjęć w folderze invoices")
        exit()
    test_image = sorted(invoice_files)[-1]
    image_path = os.path.join(invoice_folder, test_image)
    paid_status = test_image.split('_')[-1].rsplit('.', 1)[0]
    text = detect_text(image_path)
    print("Wyodrębniony tekst:")
    print(text)
    json_data = parse_invoice_text(text, paid_status)
    if not json_data:
        print("Nie udało się sparsować danych faktury")
        exit()

    days_left, alert = calculate_days_to_due(json_data['due_date'])
    target_sheet = get_worksheet(spreadsheet, "Faktury Zapłacone" if json_data['paid'] == 'T' else "Faktury Niezapłacone")
    days_info = "" if json_data['paid'] == 'T' else (alert if alert else days_left if days_left is not None else "Błąd daty")
    target_sheet.append_row([
        json_data['invoice_date'],
        json_data.get('invoice_number', ''),
        json_data['seller'],
        format_price(json_data['total']),
        json_data['category'],
        json_data['due_date'],
        json_data['paid'],
        days_info
    ])

    category_sheets = {}
    for category in ["JEDZENIE", "NAPOJE", "NAPOJE ALKOHOLOWE", "CHEMIA", "INNE"]:
        try:
            category_sheets[category] = get_worksheet(spreadsheet, category)
        except gspread.exceptions.WorksheetNotFound:
            print(f"Zakładka {category} nie znaleziona")
            continue
    for ingredient in json_data['ingredients']:
        category = ingredient['category']
        if category in category_sheets:
            update_or_append_ingredient(
                category_sheets[category],
                ingredient,
                json_data['invoice_date'],
                json_data['seller']
            )

    sync_invoice_status()
    print("Dane zapisane do arkusza!")