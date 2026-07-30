"""Создание безопасной ссылки и QR-кода цифрового паспорта выпуска."""
from __future__ import annotations

import base64
import io
import secrets

import qrcode
from qrcode.image.svg import SvgPathImage

from app.pz.project import DigitalPassportInfo


def new_passport_id() -> str:
    """192-битный URL-safe идентификатор без последовательной нумерации."""
    return secrets.token_urlsafe(24)


def qr_data_uri(url: str) -> str:
    """Сформировать векторный QR без растрового масштабирования в PDF."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def build_passport_info(passport_id: str, public_base_url: str) -> DigitalPassportInfo:
    base = public_base_url.rstrip("/")
    url = f"{base}/p/{passport_id}"
    return DigitalPassportInfo(
        passport_id=passport_id,
        url=url,
        qr_data_uri=qr_data_uri(url),
    )
