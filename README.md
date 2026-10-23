# 📦 zpl-cargo-adapter

A clean, modular Python 3.11+ library that standardizes disparate third-party logistics (cargo) payloads using the **Adapter Pattern** and generates **ZPL II thermal shipping labels** for 4x6" printers (800x600 dots / 8 dpmm).

---

## 🌟 Key Features

1. **Cargo Response Standardizer (`src/cargo_adapters.py`)**:
   - Standardizes disparate logistics carrier responses into a single, strongly-typed **Pydantic v2** model (`StandardShipmentStatus`).
   - Normalizes shipment statuses to unified enums: `CREATED`, `IN_TRANSIT`, `WAITING_AT_BRANCH`, `DELIVERED`, `RETURNED`.
   - **`FastCargoJSONAdapter`**: Parses nested JSON payloads with custom status codes (`"10"` ➔ `IN_TRANSIT`, `"40"` ➔ `WAITING_AT_BRANCH`), handling missing or null fields gracefully.
   - **`ExpressXMLCargoAdapter`**: Parses legacy XML responses from older cargo APIs into the exact same unified schema.
   - Comprehensive error hierarchy (`CarrierParsingError`, `CarrierValidationError`, `CarrierStatusError`).

2. **ZPL II Thermal Label Generator (`src/zpl_generator.py`)**:
   - Formats label data using `ShippingLabelData` model.
   - **Turkish Character Sanitization**: Replaces Turkish diacritics (`ğ, ü, ş, ı, ö, ç, Ğ, Ü, Ş, İ, Ö, Ç`) with ASCII equivalents (`g, u, s, i, o, c, G, U, S, I, O, C`) to prevent corrupt rendering on thermal printers.
   - **Address Overflow Prevention**: Truncates and uses ZPL Field Block (`^FB`) to prevent text overflowing into the barcode area.
   - **Standard 4x6" Layout (800x600 dots)**: Valid ZPL II string (`^XA ... ^XZ`) containing carrier header box, recipient details, Code 128 barcode (`^BCN`), and payment info.
   - **Labelary API Integration**: Helper function `render_zpl_to_png` to preview labels via Labelary's online engine.

3. **Production-Grade Test Suite (`tests/`)**:
   - 100% coverage across valid responses, malformed payloads, unmapped status codes, missing tracking numbers, and network mocking.

---

## 📁 Project Structure

```
zpl-cargo-adapter/
├── src/
│   ├── __init__.py           # Package exports
│   ├── cargo_adapters.py     # Adapter Pattern & Pydantic models
│   └── zpl_generator.py      # ZPL II builder & Labelary renderer
├── tests/
│   ├── __init__.py
│   ├── test_adapters.py      # Tests for JSON & XML adapters
│   └── test_zpl_generator.py # Tests for ZPL generation & sanitization
├── examples/
│   └── demo.py               # End-to-end runnable demo
├── requirements.txt          # Python dependencies
├── .gitignore                # Git ignore patterns
└── README.md                 # Documentation
```

---

## 🚀 Quickstart

### 1. Installation

Clone the repository and install requirements:

```bash
git clone https://github.com/your-username/zpl-cargo-adapter.git
cd zpl-cargo-adapter

# Create & activate a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the Demo

```bash
python -m examples.demo
```

### 3. Run the Test Suite

```bash
pytest -v
```

---

## 🔌 Adapter Pattern in Action

### 1. FastCargo Nested JSON Input
```json
{
  "meta": { "code": 200, "status": "success" },
  "data": {
    "shipment": {
      "waybill": "FC99887766TR",
      "statusCode": "10",
      "statusDescription": "Kurye dagitimda",
      "location": {
        "currentBranch": "Kadikoy Dagitim Merkezi",
        "city": "Istanbul"
      },
      "lastUpdate": "2026-10-23T14:35:00Z"
    }
  }
}
```

### 2. ExpressXML Legacy XML Input
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ShipmentResponse>
    <Barcode>EXP44556677TR</Barcode>
    <StateCode>WB</StateCode>
    <Branch>Cankaya Aktarma Subesi</Branch>
    <EventDateTime>2026-10-23 12:45:00</EventDateTime>
</ShipmentResponse>
```

### 3. Standardized Output (`StandardShipmentStatus`)
Both formats standardize to the identical Pydantic model:

```json
{
  "tracking_number": "FC99887766TR",
  "carrier_code": "FAST_CARGO",
  "normalized_status": "IN_TRANSIT",
  "branch_name": "Kadikoy Dagitim Merkezi",
  "updated_at": "2026-10-23 14:35:00+00:00"
}
```

---

## 🏷️ Sample ZPL II Code

```zpl
^XA
^PW800
^LL600
^LH0,0
^FO30,25^GB740,75,3^FS
^FO50,42^A0N,42,42^FDFASTCARGO EXPRESS^FS
^FO480,50^A0N,24,24^FDEXPRESS CARGO LABEL^FS
^FO30,115^GB740,215,2^FS
^FO50,130^A0N,20,20^FDRECIPIENT / ALICI:^FS
^FO50,158^A0N,32,32^FDSUKRU OZTURK^FS
^FO480,158^A0N,24,24^FDTEL: 0532 999 88 77^FS
^FO50,200^GB700,1,1^FS
^FO50,215^A0N,22,22^FB700,3,4,L,0^FDATATURK MAH. SEHIT ERDEM CAD. PAPATYA CICEGI SOK. NO: 15 DAIRE: 4 KADIKOY / ISTANBUL^FS
^FO30,345^GB740,140,2^FS
^FO140,365^BCN,75,Y,N,N^FDFC99887766TR^FS
^FO30,500^GB740,70,2^FS
^FO50,522^A0N,26,26^FDPAYMENT: ALICI ODEMELI^FS
^FO460,522^A0N,24,24^FDTRACK: FC99887766TR^FS
^XZ
```

---

## 👁️ Previewing on Labelary

You can preview the generated ZPL label in two ways:

### Method A: Automated via Python
```python
from src.zpl_generator import render_zpl_to_png

# Sends ZPL directly to Labelary 8dpmm 4x6 endpoint and saves PNG
render_zpl_to_png(zpl_output, "output/label.png")
```

### Method B: Online Visual Viewer
1. Copy the generated ZPL II code block above.
2. Visit [Labelary Online ZPL Viewer](http://labelary.com/viewer.html).
3. Set **Print Density** to `8 dpmm (203 dpi)` and **Label Size** to `4" x 6"`.
4. Paste the ZPL string into the text box and click **Redraw**.

---

## 🧪 Testing

Run pytest across all unit tests:

```bash
pytest tests/ -v
```

All status code variations, edge cases, malformed payloads, Turkish transliterations, and HTTP mocks are validated.
