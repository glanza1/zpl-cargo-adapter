"""
Return Mitigation SMS Formatter Module
Generates compact, single-segment (<= 160 characters) SMS notifications
to prompt customer pickup when shipments arrive and wait at cargo branches.
"""

import logging
from typing import Optional

from .cargo_adapters import ShipmentStatus, StandardShipmentStatus
from .zpl_generator import sanitize_turkish_chars

logger = logging.getLogger(__name__)

# Single SMS limit according to GSM 03.38 standard
MAX_SMS_LENGTH = 160


def format_waiting_at_branch_sms(
    customer_name: str,
    tracking_no: str,
    branch_name: str,
    branch_phone: str,
    max_branch_chars: int = 30,
) -> str:
    """
    Formats a return-mitigation SMS notification when a shipment status is WAITING_AT_BRANCH.
    Cleanly truncates long branch names (e.g. 35+ characters) and enforces a strict
    maximum message length of 160 characters (single SMS segment).

    Args:
        customer_name: Recipient full name.
        tracking_no: Carrier tracking / waybill number.
        branch_name: Branch or destination hub location name.
        branch_phone: Contact phone number for the branch.
        max_branch_chars: Maximum characters allowed for branch name (default: 30).

    Returns:
        str: Sanitized SMS text string guaranteed to be <= 160 characters.
    """
    clean_cust = sanitize_turkish_chars(customer_name or "").strip()
    clean_track = sanitize_turkish_chars(tracking_no or "").strip()
    clean_phone = sanitize_turkish_chars(branch_phone or "").strip()
    clean_branch = sanitize_turkish_chars(branch_name or "").strip()

    # Cleanly truncate long branch names if exceeding max_branch_chars
    if len(clean_branch) > max_branch_chars:
        clean_branch = clean_branch[: max_branch_chars - 3].rstrip() + "..."

    # Initial template construction
    # E.g.: "Sayin Ahmet Yilmaz, TRK123456 takip nolu kargonuz Kadikoy Subesi subemizde teslimat beklemektedir. Tel: 02164440444"
    template_prefix = f"Sayin {clean_cust}, " if clean_cust else "Sayin Musterimiz, "
    template_suffix = f" subemizde teslimat beklemektedir. Tel: {clean_phone}"

    # Calculate current length
    sms = f"{template_prefix}{clean_track} takip nolu kargonuz {clean_branch}{template_suffix}"

    # Strict fallback truncation to guarantee <= 160 chars under all conditions
    if len(sms) > MAX_SMS_LENGTH:
        # Calculate available budget for branch
        fixed_overhead = len(template_prefix) + len(clean_track) + len(" takip nolu kargonuz ") + len(template_suffix)
        available_branch = MAX_SMS_LENGTH - fixed_overhead

        if available_branch > 6:
            clean_branch = clean_branch[: available_branch - 3].rstrip() + "..."
            sms = f"{template_prefix}{clean_track} takip nolu kargonuz {clean_branch}{template_suffix}"
        else:
            # If still exceeding (e.g. very long customer name), compact customer name as well
            if len(clean_cust) > 15:
                compact_cust = clean_cust[:12].rstrip() + "..."
                template_prefix = f"Sayin {compact_cust}, "
            clean_branch = clean_branch[:15].rstrip() + "..." if len(clean_branch) > 15 else clean_branch
            sms = f"{template_prefix}{clean_track} takip nolu kargonuz {clean_branch}{template_suffix}"

            # Final safety slice if extreme values
            if len(sms) > MAX_SMS_LENGTH:
                sms = sms[:MAX_SMS_LENGTH]

    return sms


def format_cargo_status_sms(
    status: StandardShipmentStatus,
    customer_name: str,
    branch_phone: str = "",
) -> Optional[str]:
    """
    Event-driven hook that formats notifications based on cargo status transitions.
    Specifically triggers format_waiting_at_branch_sms when the status is WAITING_AT_BRANCH.

    Args:
        status: StandardShipmentStatus parsed by cargo adapters.
        customer_name: Recipient full name.
        branch_phone: Branch contact phone number.

    Returns:
        Optional[str]: Formatted SMS string if action is triggered, None otherwise.
    """
    if status.normalized_status == ShipmentStatus.WAITING_AT_BRANCH:
        branch = status.branch_name or "Ilgili"
        return format_waiting_at_branch_sms(
            customer_name=customer_name,
            tracking_no=status.tracking_number,
            branch_name=branch,
            branch_phone=branch_phone,
        )
    return None
