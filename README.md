# 📦 zpl-cargo-adapter

A clean, modular Python 3.11+ library that standardizes disparate third-party logistics (cargo) payloads using the **Adapter Pattern**, runs pre-printing order validations & fraud screening, formats single-segment return-mitigation SMS alerts, and generates **ZPL II thermal shipping labels** for 4x6" printers (800x600 dots / 8 dpmm / 203 DPI).

---

## 🌟 Key Features

1. **Cargo Response Standardizer (`src/cargo_adapters.py`)**:
   - Standardizes disparate logistics carrier responses into a single, strongly-typed **Pydantic v2** model (`StandardShipmentStatus`).
   - Normalizes shipment statuses to unified enums: `CREATED`, `IN_TRANSIT`, `WAITING_AT_BRANCH`, `DELIVERED`, `RETURNED`.
   - **`FastCargoJSONAdapter`**: Parses nested JSON payloads with custom status codes (`"10"` ➔ `IN_TRANSIT`, `"40"` ➔ `WAITING_AT_BRANCH`), handling missing or null fields gracefully.
   - **`ExpressXMLCargoAdapter`**: Parses legacy XML responses from older cargo APIs into the exact same unified schema.
   - Comprehensive error hierarchy (`CarrierParsingError`, `CarrierValidationError`, `CarrierStatusError`).

2. **Pre-Print Order Validation & Fraud Gatekeeper (`src/order_validators.py`)**:
   - **Phone Normalization**: `normalize_turkish_phone` strips international country codes (`+90`/`90`), leading zeros, spaces, and formatting characters to return a 10-digit mobile number starting with `5`. Rejects landlines and incomplete numbers.
   - **Duplicate Order Detection**: `check_duplicate_order` flags duplicate orders if another order with the identical normalized phone, shipping address, and total amount was submitted within a 3-minute window.
   - **COD Return Risk Screening**: `evaluate_cod_fraud_risk` flags Cash on Delivery (COD) orders from customers with past uncollected returns (`uncollected_cod_count > 0`) as `HIGH_RETURN_RISK`, halting automated ZPL barcode generation.

3. **Return-Mitigation SMS Formatter (`src/sms_formatter.py`)**:
   - **`format_waiting_at_branch_sms`**: Formats proactive customer notifications when a package transitions to `WAITING_AT_BRANCH`.
   - Cleanly truncates long branch names (35+ characters) with an ellipsis (`...`) while preserving tracking numbers and contact numbers.
   - Strictly enforces the single SMS segment boundary (`len(sms) <= 160` characters).

4. **ZPL II Thermal Label Generator (`src/zpl_generator.py`)**:
   - Formats label data using `ShippingLabelData` model.
   - **Turkish Character Transliteration**: Converts Turkish diacritics (`ç, ğ, ı, ö, ş, ü, Ç, Ğ, İ, Ö, Ş, Ü`) to clean uppercase ASCII (`C, G, I, O, S, U`) so thermal printers do not corrupt text.
   - **Address Wrapping with `^FB`**: Wraps long delivery addresses (140+ characters) across a maximum of 3 lines without overflowing into the barcode area.
   - **Standard 203 DPI Layout (800x600 dots)**: Valid ZPL II string (`^XA ... ^XZ`) containing `^PW800`, `^LL600`, `^FO`, `^A0N`, `^GB`, barcode module width optimization (`^BY2`), and Code 128 barcode (`^BCN`).
   - **Labelary API Integration**: Helper function `render_zpl_to_png` to preview labels via Labelary's online engine.

5. **Comprehensive Test Suite (`tests/`)**:
   - 100% passing test coverage across adapters, ZPL generator, and the dedicated scenario suite covering **TC-01 through TC-07**.

---

## 📁 Project Structure

```
zpl-cargo-adapter/
├── src/
│   ├── __init__.py                  # Package exports
│   ├── cargo_adapters.py            # Adapter Pattern & Pydantic models
│   ├── order_validators.py          # Phone normalization, duplicate detection & COD risk
│   ├── sms_formatter.py             # Single-segment (<=160 chars) SMS formatter
│   └── zpl_generator.py             # ZPL II builder & Labelary renderer
├── tests/
│   ├── __init__.py
│   ├── test_adapters.py             # Tests for JSON & XML adapters
│   ├── test_zpl_generator.py        # Tests for ZPL generation & sanitization
│   └── test_internship_scenarios.py # Dedicated test suite covering TC-01 to TC-07
├── examples/
│   └── demo.py                      # Full end-to-end runnable demonstration
├── requirements.txt                 # Python dependencies
├── .gitignore                       # Git ignore patterns
└── README.md                        # Project documentation
```

---

## 🚀 Quickstart

### 1. Installation

```bash
git clone https://github.com/your-username/zpl-cargo-adapter.git
cd zpl-cargo-adapter

# Create & activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the End-to-End Demo

```bash
python -m examples.demo
```

### 3. Run the Test Suite

```bash
pytest -v
```

---

## 📐 ZPL II `^FB` Address Wrapping & Layout Logic

In thermal label printing (203 DPI / 8 dpmm), unconstrained address strings cause vertical overflow that can overwrite or overlap the carrier barcode. In `zpl-cargo-adapter`, the recipient address field uses the ZPL **Field Block (`^FB`)** command:

```zpl
^FO50,215^A0N,22,22^FB720,3,0,L,0^FD{clean_address}^FS
```

### Command Parameter Breakdown:
- **`^FO50,215`**: Field Origin at `X=50`, `Y=215` dots.
- **`^A0N,22,22`**: Zebra Font 0 (standard alphanumeric), normal orientation, 22 dots high x 22 dots wide.
- **`^FB720,3,0,L,0`**:
  - `720`: Width of the block in dots (fits within the 740-dot bounding box with margins).
  - `3`: **Maximum number of lines = 3**. Text exceeding 3 lines is clipped by the printer firmware.
  - `0`: Line spacing addition in dots.
  - `L`: Left text alignment.
  - `0`: Hanging indent in dots.
- **Barcode Isolation**:
  - The recipient bounding box extends from `Y=115` to `Y=330`.
  - 3 lines of 22pt font occupy `215 + (3 * 22) = 281 dots`, leaving safe padding inside the container.
  - The carrier Code 128 barcode section begins cleanly below at `Y=345` with barcode origin at `^FO140,365`, completely isolated from address expansion.
- **`^BY2` Module Optimization**: Sets barcode narrow module width to 2 dots, ensuring crisp optical scanning on 203 DPI print heads.

---

## 🧪 Pre-Print Validation & Test Scenarios (TC-01 – TC-07)

The project includes a dedicated test suite in [`tests/test_internship_scenarios.py`](tests/test_internship_scenarios.py) validating the end-to-end pre-print pipeline:

| Test Case | Function Name | Description & Assertion Criteria |
|:---|:---|:---|
| **TC-01** | `test_tc01_phone_normalization` | Verifies `"+90 (532) 111-22-33"` normalizes to standard 10-digit mobile `"5321112233"`, stripping `+90`, trunk `0`, spaces, and punctuation. |
| **TC-02** | `test_tc02_phone_edge_cases` | Verifies landline numbers (e.g. `"0212 444 0 444"`), incomplete numbers (e.g. `"53211"`), and non-numeric inputs raise `ValueError`. |
| **TC-03** | `test_tc03_duplicate_order_detection` | Verifies two identical orders (same normalized phone, address, and amount) submitted within 3 minutes flag the second order as a duplicate (`True`), while an order placed after 4 minutes passes (`False`). |
| **TC-04** | `test_tc04_cod_fraud_alert` | Verifies customer profiles with past uncollected COD returns (`uncollected_cod_count > 0`) trigger `is_suspicious = True` (`"HIGH_RETURN_RISK"`) and block automated ZPL barcode printing. |
| **TC-05** | `test_tc05_zpl_turkish_sanitization` | Verifies Turkish diacritics `"Şükrü Öztürk"` and `"Eskişehir / Odunpazarı"` render as uppercase ASCII `"SUKRU OZTURK"` and `"ESKISEHIR / ODUNPAZARI"` inside the generated ZPL code. |
| **TC-06** | `test_tc06_zpl_long_address_field_block` | Passes a 140+ character address and verifies the generated ZPL contains the `^FB` command with 3-line wrapping while preserving barcode coordinates (`^FO140,365`, `^BCN`, `^BY2`). |
| **TC-07** | `test_tc07_return_mitigation_sms_limit` | Passes a 35-character branch name in `WAITING_AT_BRANCH` state and verifies the formatted SMS includes tracking number, branch phone, truncated branch name, and has `len(sms) <= 160`. |

To run the dedicated scenarios:

```bash
pytest tests/test_internship_scenarios.py -v
```

---

## 🏷️ Generated ZPL II Template Sample

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
^FO480,158^A0N,24,24^FDTEL: 5329998877^FS
^FO50,200^GB700,1,1^FS
^FO50,215^A0N,22,22^FB720,3,0,L,0^FDATATURK MAH. SEHIT ERDEM CAD. PAPATYA CICEGI SOK. NO: 15 DAIRE: 4 KADIKOY / ISTANBUL^FS
^FO30,345^GB740,140,2^FS
^BY2
^FO140,365^BCN,75,Y,N,N^FDFC99887766TR^FS
^FO30,500^GB740,70,2^FS
^FO50,522^A0N,26,26^FDPAYMENT: ALICI ODEMELI^FS
^FO460,522^A0N,24,24^FDTRACK: FC99887766TR^FS
^XZ
```

---

## 👁️ Previewing on Labelary

1. Copy the generated ZPL code block above.
2. Visit [Labelary Online ZPL Viewer](http://labelary.com/viewer.html).
3. Set **Print Density** to `8 dpmm (203 dpi)` and **Label Size** to `4" x 6"`.
4. Paste the ZPL string into the editor and click **Redraw**.
