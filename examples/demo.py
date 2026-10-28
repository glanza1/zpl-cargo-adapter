"""
End-to-End Demo for zpl-cargo-adapter.
Demonstrates:
1. Parsing nested JSON from FastCargo.
2. Parsing legacy XML from ExpressXML.
3. Pre-printing order validation, phone normalization, duplicate detection, and COD fraud gatekeeping.
4. Return-mitigation SMS generation for WAITING_AT_BRANCH.
5. Generating clean 4x6 ZPL II thermal shipping labels with ^FB address wrapping and ^BY barcode optimization.
6. Previewing label via Labelary API.
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

# Ensure project root is in sys.path when executed directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cargo_adapters import (
    ExpressXMLCargoAdapter,
    FastCargoJSONAdapter,
)
from src.order_validators import (
    OrderValidationPipeline,
    check_duplicate_order,
    evaluate_cod_fraud_risk,
    normalize_turkish_phone,
)
from src.sms_formatter import (
    format_cargo_status_sms,
    format_waiting_at_branch_sms,
)
from src.zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    render_zpl_to_png,
)


def run_demo():
    print("=" * 75)
    print("📦 ZPL CARGO ADAPTER - FULL END-TO-END PIPELINE DEMONSTRATION")
    print("=" * 75)

    # 1. FastCargo Nested JSON Payload
    fast_cargo_payload = {
        "status": "success",
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

    json_adapter = FastCargoJSONAdapter()
    fast_status = json_adapter.parse(fast_cargo_payload)

    print("\n[1] FastCargo JSON Adapter Result:")
    print(json.dumps(fast_status.model_dump(), indent=2, default=str))

    # 2. ExpressXML Legacy XML Payload
    express_xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
    <ShipmentResponse>
        <Barcode>EXP44556677TR</Barcode>
        <StateCode>WB</StateCode>
        <Branch>Cankaya Aktarma Subesi</Branch>
        <EventDateTime>2026-10-23 12:45:00</EventDateTime>
    </ShipmentResponse>
    """

    xml_adapter = ExpressXMLCargoAdapter()
    xml_status = xml_adapter.parse(express_xml_payload)

    print("\n[2] ExpressXML Cargo Adapter Result:")
    print(json.dumps(xml_status.model_dump(), indent=2, default=str))

    # 3. Pre-Printing Order Validation Pipeline
    print("\n[3] Pre-Printing Validation & Gatekeeper Pipeline:")
    pipeline = OrderValidationPipeline(duplicate_window_minutes=3)

    raw_phone = "+90 (532) 999-88-77"
    norm_phone = normalize_turkish_phone(raw_phone)
    print(f"  • Phone Normalization: '{raw_phone}' -> '{norm_phone}'")

    incoming_order = {
        "order_id": "ORD-DEMO-01",
        "phone": norm_phone,
        "shipping_address": "Atatürk Mah. Şehit Erdem Cad. Papatya Çiçeği Sok. No: 15 Daire: 4 Kadıköy / İstanbul",
        "total_amount": 550.00,
        "payment_type": "COD",
        "recipient_name": "Şükrü Öztürk",
        "tracking_number": fast_status.tracking_number,
        "carrier_name": "FastCargo Express",
        "created_at": datetime.now(timezone.utc),
    }

    # Test Customer with uncollected COD returns
    risky_customer = {"customer_id": "CUST-999", "uncollected_cod_count": 2}
    can_print, reason = pipeline.validate_for_printing(incoming_order, customer_history=risky_customer)
    print(f"  • Risky COD Check: Can Print={can_print} | Reason: {reason}")

    # Safe Customer with clean history
    clean_customer = {"customer_id": "CUST-100", "uncollected_cod_count": 0}
    can_print, reason = pipeline.validate_for_printing(incoming_order, customer_history=clean_customer)
    print(f"  • Safe Customer Check: Can Print={can_print} | Reason: {reason}")

    # 4. Return Mitigation SMS Generation (Triggered on WAITING_AT_BRANCH)
    print("\n[4] Return Mitigation SMS Formatter (WAITING_AT_BRANCH Trigger):")
    sms_text = format_cargo_status_sms(
        status=xml_status,
        customer_name="Şükrü Öztürk",
        branch_phone="0216 444 0 444",
    )
    print(f"  • Formatted SMS ({len(sms_text)} chars, single segment limit <= 160):")
    print(f"    \"{sms_text}\"")

    # 5. Generate ZPL II Shipping Label
    print("\n[5] Generating 4x6 (800x600 dots) ZPL II Thermal Label...")
    label_info = ShippingLabelData(
        recipient_name=incoming_order["recipient_name"],
        phone=norm_phone,
        address=incoming_order["shipping_address"],
        tracking_number=fast_status.tracking_number,
        carrier_name=incoming_order["carrier_name"],
        payment_type="ALICI ÖDEMELİ",
    )

    generator = ZPLGenerator(width=800, height=600)
    zpl_output = generator.generate(label_info)

    print("\n--- Generated ZPL II Code ---")
    print(zpl_output)
    print("----------------------------")

    # 6. Render to PNG using Labelary API (Optional / Output)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    png_path = output_dir / "sample_label.png"

    print(f"\n[6] Rendering label to PNG via Labelary API: {png_path}...")
    success = render_zpl_to_png(zpl_output, png_path, timeout=5.0)
    if success:
        print(f"✅ Label image rendered successfully: {png_path.resolve()}")
    else:
        print("ℹ️ Labelary API call skipped or network unavailable. You can paste the ZPL into http://labelary.com/viewer.html")


if __name__ == "__main__":
    run_demo()
