"""
Cargo Adapter Module
Standardizes diverse 3rd-party logistics (carrier) payloads into a unified schema
using the Adapter Pattern.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, Optional, Union
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShipmentStatus(str, Enum):
    """Normalized shipment status across all supported carriers."""
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    WAITING_AT_BRANCH = "WAITING_AT_BRANCH"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class StandardShipmentStatus(BaseModel):
    """Unified shipment status model produced by all cargo adapters."""
    model_config = ConfigDict(use_enum_values=True)

    tracking_number: str = Field(..., description="Unique carrier tracking identifier")
    carrier_code: str = Field(..., description="Short code representing the carrier")
    normalized_status: ShipmentStatus = Field(..., description="Standardized shipment status")
    branch_name: Optional[str] = Field(default=None, description="Current branch or hub location name")
    updated_at: Optional[datetime] = Field(default=None, description="Timestamp of the latest update in UTC")

    @field_validator("tracking_number")
    @classmethod
    def validate_tracking_number(cls, v: str) -> str:
        clean = v.strip() if v else ""
        if not clean:
            raise ValueError("Tracking number cannot be empty or blank")
        return clean


class CargoAdapterError(Exception):
    """Base exception for all cargo adapter operations."""
    pass


class CarrierParsingError(CargoAdapterError):
    """Raised when the payload cannot be parsed (e.g. malformed JSON or XML)."""
    pass


class CarrierValidationError(CargoAdapterError):
    """Raised when critical fields (e.g. tracking number) are missing."""
    pass


class CarrierStatusError(CargoAdapterError):
    """Raised when a carrier returns an unexpected or unmapped status code."""
    pass


class BaseCargoAdapter(ABC):
    """Abstract base class for all carrier payload adapters."""

    carrier_code: str = "UNKNOWN"

    @abstractmethod
    def parse(self, raw_payload: Union[str, bytes, Dict[str, Any]]) -> StandardShipmentStatus:
        """
        Parse raw carrier payload into StandardShipmentStatus.

        Args:
            raw_payload: Raw carrier response (JSON string, dict, or XML string/bytes).

        Returns:
            StandardShipmentStatus: Unified shipment status object.

        Raises:
            CarrierParsingError: If payload is malformed or invalid syntax.
            CarrierValidationError: If mandatory fields like tracking number are absent.
            CarrierStatusError: If carrier status code cannot be mapped.
        """
        pass


class FastCargoJSONAdapter(BaseCargoAdapter):
    """
    Adapter for 'FastCargo' modern JSON API.
    Parses nested JSON responses with numeric custom status codes.
    Status Mapping:
      - "00" / "01" -> CREATED
      - "10"        -> IN_TRANSIT
      - "40"        -> WAITING_AT_BRANCH
      - "50"        -> DELIVERED
      - "90"        -> RETURNED
    """

    carrier_code: str = "FAST_CARGO"

    STATUS_MAP: Dict[str, ShipmentStatus] = {
        "00": ShipmentStatus.CREATED,
        "01": ShipmentStatus.CREATED,
        "10": ShipmentStatus.IN_TRANSIT,
        "40": ShipmentStatus.WAITING_AT_BRANCH,
        "50": ShipmentStatus.DELIVERED,
        "90": ShipmentStatus.RETURNED,
    }

    def parse(self, raw_payload: Union[str, bytes, Dict[str, Any]]) -> StandardShipmentStatus:
        data: Dict[str, Any]

        if isinstance(raw_payload, (str, bytes)):
            try:
                data = json.loads(raw_payload)
            except Exception as e:
                raise CarrierParsingError(f"Malformed JSON payload: {e}") from e
        elif isinstance(raw_payload, dict):
            data = raw_payload
        else:
            raise CarrierParsingError(f"Unsupported payload type: {type(raw_payload).__name__}")

        if not isinstance(data, dict):
            raise CarrierParsingError("JSON root must be an object")

        # Support both nested structure (data.shipment) and flat payloads
        shipment = data.get("data", {}).get("shipment") if "data" in data else data.get("shipment", data)
        if not isinstance(shipment, dict):
            raise CarrierParsingError("Invalid shipment structure inside payload")

        # Extract tracking number (support common key names: waybill, tracking_number, barcode)
        tracking_number = (
            shipment.get("waybill")
            or shipment.get("tracking_number")
            or shipment.get("barcode")
        )

        if not tracking_number or not str(tracking_number).strip():
            raise CarrierValidationError("Missing or empty tracking number in FastCargo payload")

        tracking_number = str(tracking_number).strip()

        # Extract status code
        raw_code = shipment.get("statusCode") or shipment.get("status_code")
        if raw_code is None:
            raise CarrierStatusError("Missing status code in FastCargo payload")

        code_str = str(raw_code).strip()
        if code_str not in self.STATUS_MAP:
            raise CarrierStatusError(f"Unexpected status code '{code_str}' in FastCargo payload")

        normalized_status = self.STATUS_MAP[code_str]

        # Extract branch name gracefully (nested location or direct key)
        branch_name: Optional[str] = None
        location = shipment.get("location")
        if isinstance(location, dict):
            branch_name = location.get("currentBranch") or location.get("branch_name")
        if not branch_name:
            branch_name = shipment.get("currentBranch") or shipment.get("branch_name")

        if branch_name is not None:
            branch_name = str(branch_name).strip() or None

        # Extract timestamp
        updated_at: Optional[datetime] = None
        raw_time = (
            shipment.get("lastUpdate")
            or shipment.get("updated_at")
            or shipment.get("timestamp")
        )

        if raw_time:
            try:
                # ISO-8601 parsing
                if isinstance(raw_time, str):
                    clean_time = raw_time.replace("Z", "+00:00")
                    updated_at = datetime.fromisoformat(clean_time)
                elif isinstance(raw_time, datetime):
                    updated_at = raw_time
            except Exception:
                updated_at = None

        return StandardShipmentStatus(
            tracking_number=tracking_number,
            carrier_code=self.carrier_code,
            normalized_status=normalized_status,
            branch_name=branch_name,
            updated_at=updated_at,
        )


class ExpressXMLCargoAdapter(BaseCargoAdapter):
    """
    Adapter for 'ExpressXML' legacy cargo carrier.
    Parses legacy XML string responses into the exact same StandardShipmentStatus model.
    Status Mapping:
      - 'NEW', 'INIT', 'CR', '00'        -> CREATED
      - 'TRN', 'IT', 'IN_TRANSIT', '10'  -> IN_TRANSIT
      - 'BRN', 'WB', 'WAITING', '40'     -> WAITING_AT_BRANCH
      - 'DLV', 'OK', 'DELIVERED', '50'   -> DELIVERED
      - 'RET', 'FAIL', 'RETURNED', '90'  -> RETURNED
    """

    carrier_code: str = "EXPRESS_XML"

    STATUS_MAP: Dict[str, ShipmentStatus] = {
        "NEW": ShipmentStatus.CREATED,
        "INIT": ShipmentStatus.CREATED,
        "CR": ShipmentStatus.CREATED,
        "00": ShipmentStatus.CREATED,
        "TRN": ShipmentStatus.IN_TRANSIT,
        "IT": ShipmentStatus.IN_TRANSIT,
        "IN_TRANSIT": ShipmentStatus.IN_TRANSIT,
        "10": ShipmentStatus.IN_TRANSIT,
        "BRN": ShipmentStatus.WAITING_AT_BRANCH,
        "WB": ShipmentStatus.WAITING_AT_BRANCH,
        "WAITING": ShipmentStatus.WAITING_AT_BRANCH,
        "40": ShipmentStatus.WAITING_AT_BRANCH,
        "DLV": ShipmentStatus.DELIVERED,
        "OK": ShipmentStatus.DELIVERED,
        "DELIVERED": ShipmentStatus.DELIVERED,
        "50": ShipmentStatus.DELIVERED,
        "RET": ShipmentStatus.RETURNED,
        "FAIL": ShipmentStatus.RETURNED,
        "RETURNED": ShipmentStatus.RETURNED,
        "90": ShipmentStatus.RETURNED,
    }

    def parse(self, raw_payload: Union[str, bytes]) -> StandardShipmentStatus:
        if not isinstance(raw_payload, (str, bytes)):
            raise CarrierParsingError(f"Expected XML string or bytes, got {type(raw_payload).__name__}")

        if isinstance(raw_payload, str) and not raw_payload.strip():
            raise CarrierParsingError("Empty XML payload")

        try:
            root = ET.fromstring(raw_payload)
        except ET.ParseError as e:
            raise CarrierParsingError(f"Malformed XML payload: {e}") from e

        def find_element(*tags: str) -> Optional[ET.Element]:
            for tag in tags:
                elem = root.find(tag)
                if elem is not None:
                    return elem
                elem = root.find(f".//{tag}")
                if elem is not None:
                    return elem
            return None

        # Extract tracking number from common XML tags
        tracking_elem = find_element("Barcode", "TrackingNo", "TrackingNumber", "Waybill")

        tracking_number = (tracking_elem.text if tracking_elem is not None and tracking_elem.text else "").strip()
        if not tracking_number:
            raise CarrierValidationError("Missing or empty tracking number in ExpressXML payload")

        # Extract status code
        status_elem = find_element("StateCode", "StatusCode", "Status")

        raw_status = (status_elem.text if status_elem is not None and status_elem.text else "").strip().upper()
        if not raw_status:
            raise CarrierStatusError("Missing status code in ExpressXML payload")

        if raw_status not in self.STATUS_MAP:
            raise CarrierStatusError(f"Unexpected status code '{raw_status}' in ExpressXML payload")

        normalized_status = self.STATUS_MAP[raw_status]

        # Extract branch name gracefully
        branch_elem = find_element("CurrentBranch", "Branch", "BranchName")
        branch_name: Optional[str] = None
        if branch_elem is not None and branch_elem.text and branch_elem.text.strip():
            branch_name = branch_elem.text.strip()

        # Extract timestamp
        time_elem = find_element("EventDateTime", "Timestamp", "Date")
        updated_at: Optional[datetime] = None
        if time_elem is not None and time_elem.text and time_elem.text.strip():
            raw_time_str = time_elem.text.strip()
            # Try multiple legacy datetime formats
            date_formats = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%d.%m.%Y %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
            ]
            for fmt in date_formats:
                try:
                    updated_at = datetime.strptime(raw_time_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        return StandardShipmentStatus(
            tracking_number=tracking_number,
            carrier_code=self.carrier_code,
            normalized_status=normalized_status,
            branch_name=branch_name,
            updated_at=updated_at,
        )
