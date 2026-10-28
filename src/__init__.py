"""
zpl-cargo-adapter
A modular Python package for standardizing logistics carrier payloads,
performing pre-printing order validations and fraud screening,
and generating ZPL II thermal shipping labels with return-mitigation SMS alerting.
"""

from .cargo_adapters import (
    BaseCargoAdapter,
    CargoAdapterError,
    CarrierParsingError,
    CarrierStatusError,
    CarrierValidationError,
    ExpressXMLCargoAdapter,
    FastCargoJSONAdapter,
    ShipmentStatus,
    StandardShipmentStatus,
)
from .order_validators import (
    CustomerHistory,
    OrderData,
    OrderValidationPipeline,
    check_duplicate_order,
    evaluate_cod_fraud_risk,
    normalize_turkish_phone,
)
from .sms_formatter import (
    MAX_SMS_LENGTH,
    format_cargo_status_sms,
    format_waiting_at_branch_sms,
)
from .zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    render_zpl_to_png,
    sanitize_turkish_chars,
    truncate_address,
)

__all__ = [
    # Cargo Adapters
    "BaseCargoAdapter",
    "CargoAdapterError",
    "CarrierParsingError",
    "CarrierStatusError",
    "CarrierValidationError",
    "ExpressXMLCargoAdapter",
    "FastCargoJSONAdapter",
    "ShipmentStatus",
    "StandardShipmentStatus",
    # Order Validation & Fraud
    "CustomerHistory",
    "OrderData",
    "OrderValidationPipeline",
    "check_duplicate_order",
    "evaluate_cod_fraud_risk",
    "normalize_turkish_phone",
    # SMS Formatter
    "MAX_SMS_LENGTH",
    "format_cargo_status_sms",
    "format_waiting_at_branch_sms",
    # ZPL Generator
    "ShippingLabelData",
    "ZPLGenerator",
    "render_zpl_to_png",
    "sanitize_turkish_chars",
    "truncate_address",
]
