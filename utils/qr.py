import base64
from io import BytesIO


def build_qr_png_base64(content: str):
    if not content:
        raise ValueError("Contenido QR requerido")

    try:
        import qrcode
    except Exception as exc:
        raise RuntimeError("Dependencia qrcode no instalada") from exc

    image = qrcode.make(content)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
