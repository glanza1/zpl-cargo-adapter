"""
Unit tests for cargo response standardizer adapters.
Tests valid parsing, missing fields, malformed payloads, and status codes.
"""

from datetime import datetime, timezone
import pytest

from src.cargo_adapters import (
    CarrierParsingError,
    CarrierStatusError,
    CarrierValidationError,
    ExpressXMLCargoAdapter,
    FastCargoJSONAdapter,
    ShipmentStatus,
    StandardShipmentStatus,
)


class TestFastCargoJSONAdapter:
    """Test suite for FastCargo JSON Adapter."""

    @pytest.fixture
    def adapter(self):
        return FastCargoJSONAdapter()

    def test_valid_json_in_transit(self, adapter):
        payload = {
            "meta": {"code": 200, "status": "OK"},
            "data": {
                "shipment": {
                    "waybill": "FC123456789TR",
                    "statusCode": "10",
                    "statusDescription": "Package in transit",
                    "location": {
                        "currentBranch": "Kadikoy Transfer Hub",
                        "city": "Istanbul"
                    },
                    "lastUpdate": "2026-10-23T14:30:00Z"
                }
            }
        }
        result = adapter.parse(payload)

        assert isinstance(result, StandardShipmentStatus)
        assert result.tracking_number == "FC123456789TR"
        assert result.carrier_code == "FAST_CARGO"
        assert result.normalized_status == ShipmentStatus.IN_TRANSIT
        assert result.branch_name == "Kadikoy Transfer Hub"
        assert result.updated_at == datetime(2026, 10, 23, 14, 30, tzinfo=timezone.utc)

    def test_valid_json_waiting_at_branch(self, adapter):
        payload = """
        {
            "data": {
                "shipment": {
                    "waybill": "FC987654321TR",
                    "statusCode": "40",
                    "location": {
                        "currentBranch": "Besiktas Branch"
                    }
                }
            }
        }
        """
        result = adapter.parse(payload)
        assert result.normalized_status == ShipmentStatus.WAITING_AT_BRANCH
        assert result.branch_name == "Besiktas Branch"
        assert result.updated_at is None

    @pytest.mark.parametrize("status_code,expected_enum", [
        ("00", ShipmentStatus.CREATED),
        ("01", ShipmentStatus.CREATED),
        ("10", ShipmentStatus.IN_TRANSIT),
        ("40", ShipmentStatus.WAITING_AT_BRANCH),
        ("50", ShipmentStatus.DELIVERED),
        ("90", ShipmentStatus.RETURNED),
    ])
    def test_all_status_codes(self, adapter, status_code, expected_enum):
        payload = {
            "shipment": {
                "tracking_number": "TRK12345",
                "status_code": status_code,
            }
        }
        result = adapter.parse(payload)
        assert result.normalized_status == expected_enum

    def test_missing_optional_fields_handled_gracefully(self, adapter):
        payload = {
            "shipment": {
                "waybill": "FC_MINIMAL_01",
                "statusCode": "10"
            }
        }
        result = adapter.parse(payload)
        assert result.tracking_number == "FC_MINIMAL_01"
        assert result.normalized_status == ShipmentStatus.IN_TRANSIT
        assert result.branch_name is None
        assert result.updated_at is None

    def test_malformed_json_string(self, adapter):
        malformed = '{"data": {"shipment": { unclosed ...'
        with pytest.raises(CarrierParsingError) as exc_info:
            adapter.parse(malformed)
        assert "Malformed JSON payload" in str(exc_info.value)

    def test_non_dict_payload(self, adapter):
        with pytest.raises(CarrierParsingError):
            adapter.parse(12345)  # type: ignore

    def test_missing_tracking_number(self, adapter):
        payload = {
            "shipment": {
                "statusCode": "10",
                "currentBranch": "Izmir Hub"
            }
        }
        with pytest.raises(CarrierValidationError) as exc_info:
            adapter.parse(payload)
        assert "tracking number" in str(exc_info.value).lower()

    def test_empty_tracking_number(self, adapter):
        payload = {
            "shipment": {
                "waybill": "   ",
                "statusCode": "10"
            }
        }
        with pytest.raises(CarrierValidationError):
            adapter.parse(payload)

    def test_unexpected_status_code(self, adapter):
        payload = {
            "shipment": {
                "waybill": "FC999",
                "statusCode": "999_UNKNOWN"
            }
        }
        with pytest.raises(CarrierStatusError) as exc_info:
            adapter.parse(payload)
        assert "999_UNKNOWN" in str(exc_info.value)


class TestExpressXMLCargoAdapter:
    """Test suite for ExpressXML legacy Cargo Adapter."""

    @pytest.fixture
    def adapter(self):
        return ExpressXMLCargoAdapter()

    def test_valid_xml_in_transit(self, adapter):
        xml_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <ShipmentInfo>
            <Barcode>EXP778899TR</Barcode>
            <StateCode>TRN</StateCode>
            <CurrentBranch>Ankara Transfer Center</CurrentBranch>
            <EventDateTime>2026-10-23 11:15:00</EventDateTime>
        </ShipmentInfo>
        """
        result = adapter.parse(xml_payload)
        assert isinstance(result, StandardShipmentStatus)
        assert result.tracking_number == "EXP778899TR"
        assert result.carrier_code == "EXPRESS_XML"
        assert result.normalized_status == ShipmentStatus.IN_TRANSIT
        assert result.branch_name == "Ankara Transfer Center"
        assert result.updated_at == datetime(2026, 10, 23, 11, 15, tzinfo=timezone.utc)

    def test_valid_xml_waiting_at_branch(self, adapter):
        xml_payload = """<ShipmentResponse>
            <TrackingNo>EXP112233TR</TrackingNo>
            <StateCode>WB</StateCode>
            <Branch>Cankaya Sube</Branch>
        </ShipmentResponse>
        """
        result = adapter.parse(xml_payload)
        assert result.normalized_status == ShipmentStatus.WAITING_AT_BRANCH
        assert result.branch_name == "Cankaya Sube"
        assert result.updated_at is None

    @pytest.mark.parametrize("code,expected_enum", [
        ("NEW", ShipmentStatus.CREATED),
        ("TRN", ShipmentStatus.IN_TRANSIT),
        ("WB", ShipmentStatus.WAITING_AT_BRANCH),
        ("DLV", ShipmentStatus.DELIVERED),
        ("RET", ShipmentStatus.RETURNED),
    ])
    def test_all_xml_status_codes(self, adapter, code, expected_enum):
        xml_payload = f"""<Shipment>
            <Barcode>EXP_CODE_{code}</Barcode>
            <StateCode>{code}</StateCode>
        </Shipment>"""
        result = adapter.parse(xml_payload)
        assert result.normalized_status == expected_enum

    def test_missing_optional_fields_handled_gracefully(self, adapter):
        xml_payload = """<Shipment>
            <Barcode>EXP_MINIMAL</Barcode>
            <StateCode>DLV</StateCode>
        </Shipment>"""
        result = adapter.parse(xml_payload)
        assert result.tracking_number == "EXP_MINIMAL"
        assert result.normalized_status == ShipmentStatus.DELIVERED
        assert result.branch_name is None
        assert result.updated_at is None

    def test_malformed_xml_syntax(self, adapter):
        xml_payload = "<ShipmentInfo><Barcode>123</StateCode>"
        with pytest.raises(CarrierParsingError) as exc_info:
            adapter.parse(xml_payload)
        assert "Malformed XML payload" in str(exc_info.value)

    def test_empty_xml_payload(self, adapter):
        with pytest.raises(CarrierParsingError):
            adapter.parse("   ")

    def test_invalid_type_payload(self, adapter):
        with pytest.raises(CarrierParsingError):
            adapter.parse({"not": "xml"})  # type: ignore

    def test_missing_tracking_number_xml(self, adapter):
        xml_payload = """<ShipmentInfo>
            <StateCode>TRN</StateCode>
            <CurrentBranch>Hub</CurrentBranch>
        </ShipmentInfo>"""
        with pytest.raises(CarrierValidationError) as exc_info:
            adapter.parse(xml_payload)
        assert "tracking number" in str(exc_info.value).lower()

    def test_empty_tracking_number_tag_xml(self, adapter):
        xml_payload = """<ShipmentInfo>
            <Barcode>   </Barcode>
            <StateCode>TRN</StateCode>
        </ShipmentInfo>"""
        with pytest.raises(CarrierValidationError):
            adapter.parse(xml_payload)

    def test_unexpected_status_code_xml(self, adapter):
        xml_payload = """<ShipmentInfo>
            <Barcode>EXP12345</Barcode>
            <StateCode>NON_EXISTENT_STATUS</StateCode>
        </ShipmentInfo>"""
        with pytest.raises(CarrierStatusError) as exc_info:
            adapter.parse(xml_payload)
        assert "NON_EXISTENT_STATUS" in str(exc_info.value)


class TestStandardShipmentStatusModel:
    """Test validations on the standard Pydantic model itself."""

    def test_valid_model_creation(self):
        status = StandardShipmentStatus(
            tracking_number="TRK100",
            carrier_code="TEST_CARRIER",
            normalized_status=ShipmentStatus.CREATED,
            branch_name="Main Hub",
            updated_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        assert status.tracking_number == "TRK100"
        assert status.normalized_status == "CREATED"

    def test_whitespace_only_tracking_number_fails(self):
        with pytest.raises(ValueError):
            StandardShipmentStatus(
                tracking_number="   ",
                carrier_code="TEST_CARRIER",
                normalized_status=ShipmentStatus.CREATED,
            )
