"""
End-to-End Demo for zpl-cargo-adapter.
Demonstrates:
1. Parsing nested JSON from FastCargo.
2. Parsing legacy XML from ExpressXML.
3. Generating standardized shipment status objects.
4. Generating clean 4x6 ZPL II thermal shipping labels.
5. Previewing label via Labelary API.
"""

from pathlib import Path
import json

from src.cargo_adapters import (
    ExpressXMLCargoAdapter,
    FastCargoJSONAdapter,
)
from src.zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    render_zpl_to_png,
)


def run_demo():
    print("=" * 70)
    print("📦 ZPL CARGO ADAPTER - PIPELINE DEMONSTRATION")
    print("=" * 70)

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

    # 3. Generate ZPL II Shipping Label
    print("\n[3] Generating 4x6 (800x600 dots) ZPL II Thermal Label...")
    label_info = ShippingLabelData(
        recipient_name="Şükrü Öztürk",
        phone="0532 999 88 77",
        address="Atatürk Mah. Şehit Erdem Cad. Papatya Çiçeği Sok. No: 15 Daire: 4 Kadıköy / İstanbul",
        tracking_number=fast_status.tracking_number,
        carrier_name="FastCargo Express",
        payment_type="ALICI ÖDEMELİ",
    )

    generator = ZPLGenerator(width=800, height=600)
    zpl_output = generator.generate(label_info)

    print("\n--- Generated ZPL II Code ---")
    print(zpl_output)
    print("----------------------------")

    # 4. Render to PNG using Labelary API (Optional / Output)
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    png_path = output_dir / "sample_label.png"

    print(f"\n[4] Rendering label to PNG via Labelary API: {png_path}...")
    success = render_zpl_to_png(zpl_output, png_path, timeout=5.0)
    if success:
        print(f"✅ Label image rendered successfully: {png_path.resolve()}")
    else:
        print("ℹ️ Labelary API call skipped or network unavailable. You can paste the ZPL into http://labelary.com/viewer.html")


if __name__ == "__main__":
    run_demo()
