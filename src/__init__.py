"""
zpl-cargo-adapter
A modular Python package for standardizing logistics carrier payloads
and generating ZPL II thermal shipping labels.
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
from .zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    render_zpl_to_png,
    sanitize_turkish_chars,
    truncate_address,
)

__all__ = [
    "BaseCargoAdapter",
    "CargoAdapterError",
    "CarrierParsingError",
    "CarrierStatusError",
    "CarrierValidationError",
    "ExpressXMLCargoAdapter",
    "FastCargoJSONAdapter",
    "ShipmentStatus",
    "StandardShipmentStatus",
    "ShippingLabelData",
    "ZPLGenerator",
    "render_zpl_to_png",
    "sanitize_turkish_chars",
    "truncate_address",
]
