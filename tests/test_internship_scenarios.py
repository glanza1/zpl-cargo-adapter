"""
End-to-End Test Suite for Pre-Printing Validation, ZPL II Generation & SMS Formatting
Explicitly implements and validates Test Cases TC-01 through TC-07.
"""

from datetime import datetime, timezone, timedelta
import re
import pytest

from src.cargo_adapters import ShipmentStatus, StandardShipmentStatus
from src.order_validators import (
    CustomerHistory,
    OrderData,
    OrderValidationPipeline,
    check_duplicate_order,
    evaluate_cod_fraud_risk,
    normalize_turkish_phone,
)
from src.sms_formatter import (
    MAX_SMS_LENGTH,
    format_cargo_status_sms,
    format_waiting_at_branch_sms,
)
from src.zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    sanitize_turkish_chars,
)


def test_tc01_phone_normalization():
    """
    TC-01: Verify '+90 (532) 111-22-33' normalizes to '5321112233'.
    Ensures country code, parentheses, spaces, and dashes are stripped to produce
    a standard 10-digit mobile number starting with '5'.
    """
    raw_phone = "+90 (532) 111-22-33"
    normalized = normalize_turkish_phone(raw_phone)
    assert normalized == "5321112233"

    # Additional standard variations for complete coverage
    assert normalize_turkish_phone("0532 111 22 33") == "5321112233"
    assert normalize_turkish_phone("905321112233") == "5321112233"
    assert normalize_turkish_phone("5321112233") == "5321112233"
    assert normalize_turkish_phone("+90.532.111.22.33") == "5321112233"


def test_tc02_phone_edge_cases():
    """
    TC-02: Verify landline '0212 444 0 444' and short number '53211' raise ValueError.
    Ensures non-mobile numbers and malformed/incomplete numbers are rejected prior to printing.
    """
    # Landline numbers (starting with 02xx, 03xx, 04xx) must raise ValueError
    with pytest.raises(ValueError, match="(?i)landline|area code|invalid"):
        normalize_turkish_phone("0212 444 0 444")

    with pytest.raises(ValueError, match="(?i)landline|area code|invalid"):
        normalize_turkish_phone("+90 (216) 555-55-55")

    # Incomplete / short phone numbers must raise ValueError
    with pytest.raises(ValueError, match="(?i)length|digits|invalid"):
        normalize_turkish_phone("53211")

    # Additional edge cases (letters, empty)
    with pytest.raises(ValueError):
        normalize_turkish_phone("")

    with pytest.raises(ValueError):
        normalize_turkish_phone("0532abc1234")


def test_tc03_duplicate_order_detection():
    """
    TC-03: Verify two identical orders (same phone, address, total_amount) submitted
    within 3 minutes flag the second one as duplicate, while one after 4 minutes passes.
    """
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    # Initial order placed at T0
    order_1 = {
        "order_id": "ORD-101",
        "phone": "+90 (532) 111-22-33",
        "shipping_address": "Caferağa Mah. Moda Cad. No: 42 D: 3 Kadıköy / İstanbul",
        "total_amount": 750.00,
        "created_at": t0,
    }
    recent_orders = [order_1]

    # Duplicate order submitted 2 minutes later (within 3-minute window)
    order_duplicate_2min = {
        "order_id": "ORD-102",
        "phone": "0532 111 22 33",  # Same phone, different formatting
        "shipping_address": "Caferaga Mah. Moda Cad. No: 42 D: 3 Kadikoy / Istanbul",  # Same address
        "total_amount": 750.00,
        "created_at": t0 + timedelta(minutes=2),
    }
    is_duplicate = check_duplicate_order(order_duplicate_2min, recent_orders, window_minutes=3)
    assert is_duplicate is True, "Second order within 2 minutes should be flagged as a duplicate"

    # Legitimate order submitted 4 minutes later (outside 3-minute window)
    order_after_4min = {
        "order_id": "ORD-103",
        "phone": "5321112233",
        "shipping_address": "Caferağa Mah. Moda Cad. No: 42 D: 3 Kadıköy / İstanbul",
        "total_amount": 750.00,
        "created_at": t0 + timedelta(minutes=4),
    }
    is_not_duplicate = check_duplicate_order(order_after_4min, recent_orders, window_minutes=3)
    assert is_not_duplicate is False, "Order submitted after 4 minutes should NOT be flagged as duplicate"

    # Different amount should also NOT be flagged as duplicate even within 1 minute
    order_diff_amount = {
        "order_id": "ORD-104",
        "phone": "+90 532 111 22 33",
        "shipping_address": "Caferağa Mah. Moda Cad. No: 42 D: 3 Kadıköy / İstanbul",
        "total_amount": 890.00,
        "created_at": t0 + timedelta(minutes=1),
    }
    assert check_duplicate_order(order_diff_amount, recent_orders, window_minutes=3) is False


def test_tc04_cod_fraud_alert():
    """
    TC-04: Verify a mock customer with past uncollected COD returns triggers
    is_suspicious = True ('HIGH_RETURN_RISK') and halts automatic ZPL printing.
    """
    cod_order = {
        "order_id": "ORD-COD-501",
        "phone": "+90 (532) 999 88 77",
        "shipping_address": "Göztepe Mah. Bağdat Cad. No: 120 Kadıköy / İstanbul",
        "total_amount": 420.00,
        "payment_type": "COD",
    }

    # Customer profile with past uncollected COD returns
    risky_customer_history = {
        "customer_id": "CUST-SUSPICIOUS-01",
        "total_orders": 3,
        "uncollected_cod_count": 2,
    }

    risk_evaluation = evaluate_cod_fraud_risk(cod_order, risky_customer_history)

    assert risk_evaluation["is_suspicious"] is True
    assert risk_evaluation["risk_label"] == "HIGH_RETURN_RISK"
    assert risk_evaluation["allow_auto_print"] is False
    assert cod_order["is_suspicious"] is True
    assert cod_order["risk_label"] == "HIGH_RETURN_RISK"
    assert cod_order["allow_auto_print"] is False

    # Verify that the pre-printing pipeline halts automatic ZPL generation
    pipeline = OrderValidationPipeline()
    can_print, message = pipeline.validate_for_printing(cod_order, customer_history=risky_customer_history)
    assert can_print is False
    assert "HIGH_RETURN_RISK" in message

    # Verify a safe customer with 0 uncollected returns is allowed to print
    safe_customer_history = {
        "customer_id": "CUST-RELIABLE-02",
        "total_orders": 10,
        "uncollected_cod_count": 0,
    }
    safe_evaluation = evaluate_cod_fraud_risk(cod_order, safe_customer_history)
    assert safe_evaluation["is_suspicious"] is False
    assert safe_evaluation["risk_label"] == "LOW_RISK"
    assert safe_evaluation["allow_auto_print"] is True


def test_tc05_zpl_turkish_sanitization():
    """
    TC-05: Verify 'Şükrü Öztürk' and 'Eskişehir / Odunpazarı' render as
    'SUKRU OZTURK' and 'ESKISEHIR / ODUNPAZARI' inside the generated ZPL string.
    Ensures thermal printer firmware does not corrupt special Turkish diacritics.
    """
    label_data = ShippingLabelData(
        recipient_name="Şükrü Öztürk",
        phone="0532 999 88 77",
        address="Kurtuluş Mahallesi Vatan Caddesi No: 12 Eskişehir / Odunpazarı",
        tracking_number="TRK123456789",
        carrier_name="Yurtiçi Kargo",
        payment_type="ALICI ÖDEMELİ",
    )

    generator = ZPLGenerator(width=800, height=600)
    zpl = generator.generate(label_data)

    # Assert expected uppercase ASCII transliterations exist in the output ZPL
    assert "SUKRU OZTURK" in zpl
    assert "ESKISEHIR / ODUNPAZARI" in zpl

    # Verify that no un-sanitized Turkish characters remain anywhere in the ZPL code
    forbidden_chars = ["ç", "ğ", "ı", "ö", "ş", "ü", "Ç", "Ğ", "İ", "Ö", "Ş", "Ü"]
    for char in forbidden_chars:
        assert char not in zpl, f"Found un-sanitized Turkish character '{char}' in generated ZPL"


def test_tc06_zpl_long_address_field_block():
    """
    TC-06: Pass a 140+ character address and verify the generated ZPL contains the
    ^FB (Field Block) command with 3-line wrapping and preserves barcode coordinates.
    """
    # 158-character detailed address with apartment and directions
    long_delivery_address = (
        "Vişnezade Mahallesi Şehit Cahit Gökgöz Sokak No: 14 Daire: 8 Kat: 3 "
        "Ihlamur Evleri Apartmanı Beşiktaş / İstanbul Türkiye (Arka sokaktaki parkın tam karşısı)"
    )
    assert len(long_delivery_address) > 140

    label_data = ShippingLabelData(
        recipient_name="Ahmet Şükrü Çelik",
        phone="0532 111 22 33",
        address=long_delivery_address,
        tracking_number="FC88776655TR",
        carrier_name="FastCargo Express",
        payment_type="PREPAID",
    )

    generator = ZPLGenerator(width=800, height=600)
    zpl = generator.generate(label_data)

    # 1. Verify ZPL Field Block command (^FB) is present with 3-line wrapping
    assert "^FB" in zpl
    # Check ^FB720,3,0,L,0 or equivalent ^FB<width>,3,<spacing>,<align>,<margin>
    fb_match = re.search(r"\^FB(\d+),3,", zpl)
    assert fb_match is not None, "Generated ZPL must specify 3-line address wrapping in ^FB"
    assert int(fb_match.group(1)) >= 700, "^FB width should match label printable bounds (>= 700 dots)"

    # 2. Verify Code 128 barcode commands and coordinates are strictly preserved below the address
    assert "^FO140,365" in zpl, "Barcode origin coordinate ^FO140,365 must remain unchanged"
    assert "^BCN,75,Y,N,N" in zpl, "Code 128 barcode command ^BCN must be preserved"
    assert "^BY" in zpl, "Barcode module width optimization ^BY must be present"
    assert "^FO30,345^GB740,140,2^FS" in zpl, "Barcode container box must remain intact"


def test_tc07_return_mitigation_sms_limit():
    """
    TC-07: Pass a 35-character branch name in WAITING_AT_BRANCH state and verify the
    formatted SMS includes tracking number and branch phone and has len(sms) <= 160.
    """
    branch_name_35_chars = "Kadikoy Anadolu Yakasi Dagitim Sube"  # Exactly 35 chars
    assert len(branch_name_35_chars) == 35

    customer_name = "Mehmet Şükrü Demir"
    tracking_no = "EXP998877TR"
    branch_phone = "0216 444 0 444"

    # Direct SMS formatting
    sms = format_waiting_at_branch_sms(
        customer_name=customer_name,
        tracking_no=tracking_no,
        branch_name=branch_name_35_chars,
        branch_phone=branch_phone,
    )

    # Verify essential components are present in SMS
    assert tracking_no in sms, "SMS must include the carrier tracking number"
    clean_phone = sanitize_turkish_chars(branch_phone)
    assert clean_phone in sms, "SMS must include the branch phone number"

    # Verify single SMS character boundary
    assert len(sms) <= MAX_SMS_LENGTH, f"SMS length {len(sms)} exceeds maximum single SMS limit of 160"

    # Integration test with cargo adapter status transition to WAITING_AT_BRANCH
    status_event = StandardShipmentStatus(
        tracking_number=tracking_no,
        carrier_code="EXPRESS_XML",
        normalized_status=ShipmentStatus.WAITING_AT_BRANCH,
        branch_name="Kadikoy Anadolu Bolge Ana Aktarma ve Dagitim Transfer Subesi",  # 65 chars
    )

    status_sms = format_cargo_status_sms(
        status=status_event,
        customer_name=customer_name,
        branch_phone=branch_phone,
    )

    assert status_sms is not None
    assert tracking_no in status_sms
    assert clean_phone in status_sms
    assert len(status_sms) <= MAX_SMS_LENGTH
    assert "..." in status_sms, "Long branch name must be cleanly truncated with an ellipsis"
