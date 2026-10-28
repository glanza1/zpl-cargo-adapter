"""
Unit tests for ZPL II thermal shipping label generator.
Tests ZPL command structure, Turkish character sanitization, address overflow prevention,
and Labelary rendering API caller.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.zpl_generator import (
    ShippingLabelData,
    ZPLGenerator,
    render_zpl_to_png,
    sanitize_turkish_chars,
    truncate_address,
)


class TestTurkishSanitization:
    """Test suite for Turkish character transliteration."""

    def test_lowercase_turkish_chars(self):
        raw = "şükrü öztürk çankaya dağlıoğlu ılık su"
        expected = "sukru ozturk cankaya daglioglu ilik su"
        assert sanitize_turkish_chars(raw) == expected

    def test_uppercase_turkish_chars(self):
        raw = "ŞÜKRÜ ÖZTÜRK ÇANKAYA DAĞLIOĞLU İSTANBUL"
        expected = "SUKRU OZTURK CANKAYA DAGLIOGLU ISTANBUL"
        assert sanitize_turkish_chars(raw) == expected

    def test_mixed_text_with_punctuation(self):
        raw = "Kadıköy Mah. Şairler Sk. No: 12/A, D: 4 - Beşiktaş/İstanbul"
        expected = "Kadikoy Mah. Sairler Sk. No: 12/A, D: 4 - Besiktas/Istanbul"
        assert sanitize_turkish_chars(raw) == expected

    def test_empty_string(self):
        assert sanitize_turkish_chars("") == ""
        assert sanitize_turkish_chars(None) == ""  # type: ignore


class TestAddressTruncation:
    """Test suite for address truncation and formatting."""

    def test_short_address_preserved(self):
        addr = "Kadikoy Mah. Moda Cad. No: 10 Istanbul"
        assert truncate_address(addr, max_chars=140) == addr

    def test_long_address_truncated_cleanly(self):
        long_addr = (
            "Atatürk Mahallesi Kazım Karabekir Caddesi Şehit Erdem Yürük Sokak "
            "Papatya Çiçekçilik Apartmanı Kat: 4 Daire: 12 Başakşehir İstanbul Türkiye"
        )
        truncated = truncate_address(long_addr, max_chars=80)
        assert len(truncated) <= 80
        assert truncated.endswith("...")
        # Check no Turkish characters remain in truncated output
        assert "ş" not in truncated.lower()
        assert "ç" not in truncated.lower()

    def test_multi_line_and_whitespace_collapse(self):
        raw_addr = "Kadıköy\n\n  Moda Cad.   \t No:5\n  Daire: 2  "
        expected = "Kadikoy Moda Cad. No:5 Daire: 2"
        assert truncate_address(raw_addr) == expected


class TestZPLGenerator:
    """Test suite for ZPL II string generation."""

    @pytest.fixture
    def sample_data(self):
        return ShippingLabelData(
            recipient_name="Ahmet Şükrü Çelik",
            phone="0532 111 22 33",
            address="Göztepe Mah. Bağdat Cad. No: 200 D: 5 Kadıköy / İstanbul",
            tracking_number="TRK987654321",
            carrier_name="Yurt İçi Kargo",
            payment_type="ALICI ÖDEMELİ",
        )

    def test_zpl_markers_present(self, sample_data):
        generator = ZPLGenerator(width=800, height=600)
        zpl = generator.generate(sample_data)

        # Essential ZPL markers
        assert zpl.startswith("^XA")
        assert zpl.endswith("^XZ")
        assert "^BCN" in zpl  # Code 128 barcode
        assert "^BY" in zpl   # Barcode module width optimization
        assert "^PW800" in zpl
        assert "^LL600" in zpl
        assert "^FD" in zpl
        assert "^FS" in zpl
        assert "^FB" in zpl  # Multi-line address block

    def test_turkish_characters_sanitized_in_output(self, sample_data):
        generator = ZPLGenerator()
        zpl = generator.generate(sample_data)

        # None of the Turkish characters should exist
        for tr_char in ["ş", "Ş", "ü", "Ü", "ç", "Ç", "ö", "Ö", "ı", "İ", "ğ", "Ğ"]:
            assert tr_char not in zpl, f"Found un-sanitized Turkish character '{tr_char}' in ZPL"

        # Check transliterated equivalents
        assert "AHMET SUKRU CELIK" in zpl
        assert "YURT ICI KARGO" in zpl
        assert "ALICI ODEMELI" in zpl
        assert "KADIKOY / ISTANBUL" in zpl

    def test_barcode_contains_tracking_number(self, sample_data):
        generator = ZPLGenerator()
        zpl = generator.generate(sample_data)
        assert f"^BCN,75,Y,N,N^FD{sample_data.tracking_number}^FS" in zpl

    def test_empty_fields_raise_validation_error(self):
        with pytest.raises(ValueError, match="recipient_name cannot be empty"):
            ShippingLabelData(
                recipient_name="   ",
                phone="123",
                address="Addr",
                tracking_number="TRK1",
                carrier_name="Carrier",
                payment_type="Prepaid",
            )

        with pytest.raises(ValueError, match="tracking_number cannot be empty"):
            ShippingLabelData(
                recipient_name="John Doe",
                phone="123",
                address="Addr",
                tracking_number="",
                carrier_name="Carrier",
                payment_type="Prepaid",
            )


class TestRenderZPLToPNG:
    """Test suite for Labelary API renderer with mocked requests."""

    @patch("src.zpl_generator.requests")
    def test_render_success(self, mock_requests, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"\x89PNG\r\n\x1a\nFakePngContent"
        mock_requests.post.return_value = mock_response

        out_file = tmp_path / "label.png"
        success = render_zpl_to_png("^XA^XZ", out_file)

        assert success is True
        assert out_file.exists()
        assert out_file.read_bytes() == b"\x89PNG\r\n\x1a\nFakePngContent"

    @patch("src.zpl_generator.requests")
    def test_render_api_error(self, mock_requests, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request: Malformed ZPL"
        mock_requests.post.return_value = mock_response

        out_file = tmp_path / "label_error.png"
        success = render_zpl_to_png("^XA^XZ", out_file)

        assert success is False
        assert not out_file.exists()

    @patch("src.zpl_generator.requests")
    def test_render_network_exception(self, mock_requests, tmp_path):
        mock_requests.post.side_effect = TimeoutError("Connection timed out")

        out_file = tmp_path / "label_timeout.png"
        success = render_zpl_to_png("^XA^XZ", out_file)

        assert success is False
        assert not out_file.exists()

    def test_empty_zpl_returns_false(self, tmp_path):
        out_file = tmp_path / "empty.png"
        assert render_zpl_to_png("", out_file) is False
        assert render_zpl_to_png("   ", out_file) is False
