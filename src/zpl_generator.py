"""
ZPL II Thermal Label Generator Module
Formats standardized shipping data into ZPL II format (4x6 / 800x600 dots)
with Turkish character sanitization and Labelary API preview capability.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Optional, Union

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


logger = logging.getLogger(__name__)

# Complete Turkish character transliteration map
TURKISH_CHAR_MAP = str.maketrans({
    "ğ": "g", "Ğ": "G",
    "ü": "u", "Ü": "U",
    "ş": "s", "Ş": "S",
    "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O",
    "ç": "c", "Ç": "C",
    "â": "a", "Â": "A",
    "î": "i", "Î": "I",
    "û": "u", "Û": "U",
})


def sanitize_turkish_chars(text: str) -> str:
    """
    Sanitizes Turkish and special diacritic characters to plain ASCII equivalents
    suitable for thermal label printers.

    Args:
        text: Input string with possible Turkish characters.

    Returns:
        Sanitized ASCII-compatible string.
    """
    if not text:
        return ""
    transliterated = text.translate(TURKISH_CHAR_MAP)
    # Remove any other non-printable or unsupported control characters while preserving standard punctuation
    sanitized = re.sub(r"[^\x20-\x7E\n\r]", "", transliterated)
    return sanitized.strip()


def truncate_address(address: str, max_chars: int = 140) -> str:
    """
    Cleans and safely truncates long address texts to prevent overflowing thermal label bounds.

    Args:
        address: Full address text.
        max_chars: Maximum characters allowed across label address block.

    Returns:
        Truncated and sanitized address string.
    """
    cleaned = sanitize_turkish_chars(address)
    # Collapse multiple whitespaces and newlines
    normalized = " ".join(cleaned.split())
    if len(normalized) > max_chars:
        return normalized[: max_chars - 3].rstrip() + "..."
    return normalized


@dataclass
class ShippingLabelData:
    """Data model containing all required fields for a thermal shipping label."""
    recipient_name: str
    phone: str
    address: str
    tracking_number: str
    carrier_name: str
    payment_type: str

    def __post_init__(self):
        # Auto-validate and sanitize attributes
        if not self.recipient_name or not self.recipient_name.strip():
            raise ValueError("recipient_name cannot be empty")
        if not self.tracking_number or not self.tracking_number.strip():
            raise ValueError("tracking_number cannot be empty")
        if not self.carrier_name or not self.carrier_name.strip():
            raise ValueError("carrier_name cannot be empty")


class ZPLGenerator:
    """Generates standard ZPL II thermal label code for 4x6 labels (800x600 dots)."""

    def __init__(self, width: int = 800, height: int = 600):
        self.width = width
        self.height = height

    def generate(self, data: ShippingLabelData) -> str:
        """
        Generates a valid 4x6 (800x600 dots) ZPL II string.

        Args:
            data: ShippingLabelData containing recipient, carrier, barcode, and payment details.

        Returns:
            str: Full ZPL II code string starting with ^XA and ending with ^XZ.
        """
        clean_carrier = sanitize_turkish_chars(data.carrier_name).upper()
        clean_recipient = sanitize_turkish_chars(data.recipient_name).upper()
        clean_phone = sanitize_turkish_chars(data.phone)
        clean_address = truncate_address(data.address, max_chars=140).upper()
        clean_tracking = sanitize_turkish_chars(data.tracking_number).upper()
        clean_payment = sanitize_turkish_chars(data.payment_type).upper()

        # Build clean, modular ZPL II commands
        zpl_lines = [
            "^XA",
            f"^PW{self.width}",
            f"^LL{self.height}",
            "^LH0,0",
            # --- HEADER SECTION (Carrier Box) ---
            "^FO30,25^GB740,75,3^FS",
            f"^FO50,42^A0N,42,42^FD{clean_carrier}^FS",
            "^FO480,50^A0N,24,24^FDEXPRESS CARGO LABEL^FS",
            # --- RECIPIENT SECTION ---
            "^FO30,115^GB740,215,2^FS",
            "^FO50,130^A0N,20,20^FDRECIPIENT / ALICI:^FS",
            f"^FO50,158^A0N,32,32^FD{clean_recipient}^FS",
            f"^FO480,158^A0N,24,24^FDTEL: {clean_phone}^FS",
            "^FO50,200^GB700,1,1^FS",
            # Multi-line address block (width: 700, max lines: 3, line spacing: 4)
            f"^FO50,215^A0N,22,22^FB700,3,4,L,0^FD{clean_address}^FS",
            # --- BARCODE SECTION (Code 128) ---
            "^FO30,345^GB740,140,2^FS",
            f"^FO140,365^BCN,75,Y,N,N^FD{clean_tracking}^FS",
            # --- PAYMENT & SUMMARY SECTION ---
            "^FO30,500^GB740,70,2^FS",
            f"^FO50,522^A0N,26,26^FDPAYMENT: {clean_payment}^FS",
            f"^FO460,522^A0N,24,24^FDTRACK: {clean_tracking}^FS",
            "^XZ",
        ]

        return "\n".join(zpl_lines)


def render_zpl_to_png(
    zpl_str: str,
    output_path: Union[str, Path],
    timeout: float = 10.0,
    api_url: str = "http://api.labelary.com/v1/printers/8dpmm/labels/4x6/0/",
) -> bool:
    """
    Renders a ZPL II string to a PNG image using the public Labelary API.

    Args:
        zpl_str: ZPL II code string.
        output_path: Local filesystem path where the PNG will be saved.
        timeout: Request timeout in seconds (default: 10.0).
        api_url: Labelary endpoint URL.

    Returns:
        bool: True if image was successfully generated and saved, False otherwise.
    """
    if not zpl_str or not zpl_str.strip():
        logger.error("Empty ZPL string provided for rendering.")
        return False

    headers = {
        "Accept": "image/png",
    }
    payload = zpl_str.encode("utf-8")
    out_path = Path(output_path)

    # Prefer requests if available, fallback to httpx
    if requests is not None:
        try:
            response = requests.post(
                api_url,
                headers=headers,
                data=payload,
                timeout=timeout,
            )
            if response.status_code == 200:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(response.content)
                logger.info("Successfully rendered ZPL label to %s", out_path)
                return True
            else:
                logger.error(
                    "Labelary API error (%d): %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as e:
            logger.error("Failed to render ZPL via Labelary using requests: %s", e)
            return False

    elif httpx is not None:
        try:
            response = httpx.post(
                api_url,
                headers=headers,
                content=payload,
                timeout=timeout,
            )
            if response.status_code == 200:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(response.content)
                logger.info("Successfully rendered ZPL label to %s", out_path)
                return True
            else:
                logger.error(
                    "Labelary API error (%d): %s",
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as e:
            logger.error("Failed to render ZPL via Labelary using httpx: %s", e)
            return False

    else:
        logger.error("Neither 'requests' nor 'httpx' is installed to call Labelary API.")
        return False
