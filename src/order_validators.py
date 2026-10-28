"""
Order Validation, Duplicate Detection & Fraud Gatekeeper Module
Validates incoming orders prior to automatic ZPL barcode printing,
normalizes Turkish phone numbers, flags rapid duplicate submissions,
and evaluates Cash on Delivery (COD) fraud/return risk.
"""

from datetime import datetime, timezone, timedelta
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class OrderData(BaseModel):
    """Normalized order structure for pre-printing validation and ZPL generation."""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    order_id: Optional[str] = Field(default=None, description="Unique internal order ID")
    phone: str = Field(..., description="Customer contact phone number")
    shipping_address: str = Field(..., description="Full delivery address")
    total_amount: float = Field(..., description="Total order monetary amount")
    payment_type: str = Field(default="PREPAID", description="Payment method: COD, CREDIT_CARD, etc.")
    recipient_name: Optional[str] = Field(default=None, description="Recipient full name")
    tracking_number: Optional[str] = Field(default=None, description="Assigned carrier tracking number")
    carrier_name: Optional[str] = Field(default=None, description="Carrier name (e.g. FastCargo)")
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_suspicious: bool = Field(default=False, description="Flagged for seller review")
    risk_label: Optional[str] = Field(default="LOW_RISK", description="Risk assessment level")
    allow_auto_print: bool = Field(default=True, description="Whether ZPL generation is permitted")


class CustomerHistory(BaseModel):
    """Customer profile summary containing historical delivery and return telemetry."""
    model_config = ConfigDict(extra="allow")

    customer_id: Optional[str] = Field(default=None, description="Unique customer ID")
    total_orders: int = Field(default=0, description="Total historical order count")
    uncollected_cod_count: int = Field(default=0, description="Past uncollected Cash on Delivery returns")


def normalize_turkish_phone(phone_str: str) -> str:
    """
    Normalizes a Turkish phone number string into a clean 10-digit mobile number starting with '5'.
    Strips international country code (+90/90), leading zero, spaces, parentheses, and symbols.

    Args:
        phone_str: Input phone number string (e.g. "+90 (532) 111-22-33", "0532 111 22 33").

    Returns:
        str: Standard 10-digit mobile phone number starting with '5' (e.g. "5321112233").

    Raises:
        ValueError: If phone_str is empty, contains letters, is an invalid length,
                    or is a landline/unsupported area code.
    """
    if phone_str is None or not isinstance(phone_str, str):
        raise ValueError("Phone number must be a non-empty string")

    clean = phone_str.strip()
    if not clean:
        raise ValueError("Phone number cannot be empty")

    # Reject strings with alphabetic characters
    if re.search(r"[a-zA-Z]", clean):
        raise ValueError(f"Phone number cannot contain alphabetic characters: '{phone_str}'")

    # Extract digits only
    digits = re.sub(r"\D", "", clean)

    # Strip international country code +90 / 0090 / 90
    if digits.startswith("0090") and len(digits) > 10:
        digits = digits[4:]
    elif digits.startswith("90") and len(digits) > 10:
        digits = digits[2:]

    # Strip trunk prefix (leading 0)
    if digits.startswith("0"):
        digits = digits[1:]

    # Must be exactly 10 digits
    if len(digits) != 10:
        raise ValueError(
            f"Invalid Turkish phone number length ({len(digits)} digits, expected 10): '{phone_str}'"
        )

    # Turkish mobile phone numbers strictly start with '5' (e.g. 50x, 53x, 54x, 55x)
    # Landlines start with 2, 3, or 4 (e.g. 212, 216, 312)
    if not digits.startswith("5"):
        raise ValueError(
            f"Invalid Turkish mobile phone number. Landlines or invalid area codes not allowed: '{phone_str}'"
        )

    return digits


def _extract_field(obj: Any, *keys: str, default: Any = None) -> Any:
    """Helper to extract a field from a dict or an object instance."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
    else:
        for k in keys:
            if hasattr(obj, k):
                val = getattr(obj, k)
                if val is not None:
                    return val
    return default


def _extract_datetime(val: Any) -> datetime:
    """Helper to convert varied timestamp representations to timezone-aware UTC datetime."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        clean = val.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


from .zpl_generator import sanitize_turkish_chars


def _normalize_address(addr: Any) -> str:
    """Sanitizes Turkish characters and normalizes whitespaces for robust address comparison."""
    cleaned = sanitize_turkish_chars(str(addr or ""))
    return " ".join(cleaned.strip().lower().split())


def check_duplicate_order(
    new_order: Union[Dict[str, Any], Any],
    recent_orders: Iterable[Union[Dict[str, Any], Any]],
    window_minutes: int = 3,
) -> bool:
    """
    Flags an order as a duplicate if another order with the exact same
    normalized customer phone, shipping address, and total amount was submitted
    within the configured time window.

    Args:
        new_order: Incoming order (dict or model instance).
        recent_orders: Collection of recently processed orders.
        window_minutes: Duplicate detection time window in minutes (default: 3).

    Returns:
        bool: True if duplicate order detected within window, False otherwise.
    """
    raw_new_phone = _extract_field(new_order, "phone", "customer_phone", "recipient_phone", "tel")
    if raw_new_phone is None:
        return False

    try:
        norm_new_phone = normalize_turkish_phone(str(raw_new_phone))
    except ValueError:
        norm_new_phone = re.sub(r"\D", "", str(raw_new_phone))

    new_addr = _extract_field(new_order, "shipping_address", "address", "delivery_address", default="")
    clean_new_addr = _normalize_address(new_addr)

    new_amount_raw = _extract_field(new_order, "total_amount", "amount", "price", "total", default=0.0)
    try:
        new_amount = round(float(new_amount_raw), 2)
    except (ValueError, TypeError):
        new_amount = 0.0

    new_time_val = _extract_field(new_order, "created_at", "submitted_at", "timestamp", "order_date", default=None)
    new_time = _extract_datetime(new_time_val)

    for order in recent_orders:
        # Avoid self-comparison if order_id is present and identical
        curr_id = _extract_field(order, "order_id", "id")
        new_id = _extract_field(new_order, "order_id", "id")
        if curr_id and new_id and curr_id == new_id:
            continue

        raw_phone = _extract_field(order, "phone", "customer_phone", "recipient_phone", "tel")
        if raw_phone is None:
            continue

        try:
            norm_phone = normalize_turkish_phone(str(raw_phone))
        except ValueError:
            norm_phone = re.sub(r"\D", "", str(raw_phone))

        if norm_new_phone != norm_phone:
            continue

        addr = _extract_field(order, "shipping_address", "address", "delivery_address", default="")
        clean_addr = _normalize_address(addr)
        if clean_new_addr != clean_addr:
            continue

        amount_raw = _extract_field(order, "total_amount", "amount", "price", "total", default=0.0)
        try:
            amount = round(float(amount_raw), 2)
        except (ValueError, TypeError):
            amount = 0.0

        if new_amount != amount:
            continue

        # Check timestamp window
        time_val = _extract_field(order, "created_at", "submitted_at", "timestamp", "order_date", default=None)
        curr_time = _extract_datetime(time_val)

        delta_seconds = abs((new_time - curr_time).total_seconds())
        if delta_seconds <= (window_minutes * 60):
            logger.warning(
                "Duplicate order detected! Phone: %s, Address: %s, Amount: %.2f (Delta: %.1fs <= %ds)",
                norm_new_phone, clean_new_addr, new_amount, delta_seconds, window_minutes * 60
            )
            return True

    return False


def evaluate_cod_fraud_risk(
    order: Union[Dict[str, Any], Any],
    customer_history: Union[Dict[str, Any], Any],
) -> Dict[str, Any]:
    """
    Evaluates Cash on Delivery (COD) fraud and return risk.
    If the order payment type is COD and the customer profile has past uncollected
    COD returns (uncollected_cod_count > 0), flags the order as HIGH_RETURN_RISK
    and halts automatic ZPL generation until manual seller approval.

    Args:
        order: Incoming order (dict or model instance).
        customer_history: Customer history/profile (dict or model instance).

    Returns:
        dict: Assessment result containing:
            - is_suspicious: bool
            - risk_label: str ("HIGH_RETURN_RISK" or "LOW_RISK")
            - allow_auto_print: bool
            - reason: str
            - uncollected_cod_count: int
    """
    payment_raw = _extract_field(order, "payment_type", "payment_method", "payment", default="")
    clean_payment = str(payment_raw).strip().upper()

    cod_keywords = ["COD", "CASH_ON_DELIVERY", "KAPIDA", "ALICI_ODEMELI", "ALICI ODEMELI"]
    is_cod = any(kw in clean_payment for kw in cod_keywords)

    uncollected_count_raw = _extract_field(
        customer_history,
        "uncollected_cod_count",
        "past_uncollected_cod_returns",
        "uncollected_returns",
        default=0,
    )
    try:
        uncollected_count = int(uncollected_count_raw)
    except (ValueError, TypeError):
        uncollected_count = 0

    if is_cod and uncollected_count > 0:
        is_suspicious = True
        risk_label = "HIGH_RETURN_RISK"
        allow_auto_print = False
        reason = (
            f"Cash on Delivery order with {uncollected_count} past uncollected return(s). "
            "Automatic ZPL printing blocked pending seller review."
        )
    else:
        is_suspicious = False
        risk_label = "LOW_RISK"
        allow_auto_print = True
        reason = "Order passed pre-print COD risk verification."

    # Update order object if mutable
    if isinstance(order, dict):
        order["is_suspicious"] = is_suspicious
        order["risk_label"] = risk_label
        order["allow_auto_print"] = allow_auto_print
    else:
        try:
            setattr(order, "is_suspicious", is_suspicious)
            setattr(order, "risk_label", risk_label)
            setattr(order, "allow_auto_print", allow_auto_print)
        except Exception:
            pass

    return {
        "is_suspicious": is_suspicious,
        "risk_label": risk_label,
        "allow_auto_print": allow_auto_print,
        "reason": reason,
        "uncollected_cod_count": uncollected_count,
    }


class OrderValidationPipeline:
    """
    Unified gatekeeper pipeline executing all pre-printing validations
    prior to queueing an order for ZPL generation.
    """

    def __init__(self, duplicate_window_minutes: int = 3):
        self.duplicate_window_minutes = duplicate_window_minutes

    def validate_for_printing(
        self,
        order: Union[Dict[str, Any], Any],
        recent_orders: Optional[Iterable[Union[Dict[str, Any], Any]]] = None,
        customer_history: Optional[Union[Dict[str, Any], Any]] = None,
    ) -> Tuple[bool, str]:
        """
        Executes pre-printing checks in sequence:
        1. Normalizes Turkish contact phone.
        2. Detects rapid duplicate submissions.
        3. Evaluates COD return fraud risks.

        Returns:
            Tuple[bool, str]: (can_proceed_to_print, status_message)
        """
        # 1. Phone validation
        phone_val = _extract_field(order, "phone", "customer_phone", "tel")
        if not phone_val:
            return False, "Missing phone number"
        try:
            norm_phone = normalize_turkish_phone(str(phone_val))
            if isinstance(order, dict):
                order["phone"] = norm_phone
            elif hasattr(order, "phone"):
                try:
                    setattr(order, "phone", norm_phone)
                except Exception:
                    pass
        except ValueError as e:
            return False, f"Phone validation failed: {e}"

        # 2. Duplicate detection
        if recent_orders:
            if check_duplicate_order(order, recent_orders, window_minutes=self.duplicate_window_minutes):
                return False, f"Duplicate order detected within {self.duplicate_window_minutes}-minute window"

        # 3. COD Fraud check
        if customer_history is not None:
            risk_result = evaluate_cod_fraud_risk(order, customer_history)
            if risk_result["is_suspicious"] or not risk_result["allow_auto_print"]:
                return False, f"COD Risk Alert: {risk_result['risk_label']} - {risk_result['reason']}"

        return True, "Order approved for ZPL printing"
