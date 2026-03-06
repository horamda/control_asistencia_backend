# Demo Aislado FTP + Media

Este demo es independiente del proyecto principal. Sirve para probar:

1. Subir archivos a FTP y obtener URL publica.
2. Guardar adjuntos "privados" en FTP y servirlos a traves de backend.

No modifica `app.py` ni rutas del sistema principal.

## Requisitos

- Python 3.10+
- Paquetes:
  - Flask
  - python-dotenv

Instalacion minima:

```powershell
pip install flask python-dotenv
```

## Configuracion

Copiar `.env.example` a `.env` dentro de esta carpeta y completar credenciales.

Variables clave:

- `DEMO_FTP_HOST`
- `DEMO_FTP_USER`
- `DEMO_FTP_PASSWORD`
- `DEMO_PUBLIC_BASE_URL` (ej: `https://www.delpalacio.com.ar`)
- `DEMO_FTP_PUBLIC_DIR` (ej: `/htdocs/uploads/demo/public`)
- `DEMO_FTP_PRIVATE_DIR` (ej: `/htdocs/uploads/demo/private`)
- `DEMO_PRIVATE_KEY` (clave simple para descarga privada)

## Ejecutar

```powershell
python app_demo.py
```

Abrir:

- `http://127.0.0.1:5055`

## Que valida este demo

- Flujo "foto/documento publico": archivo subido a FTP y mostrado por URL publica.
- Flujo "documento privado": archivo subido a FTP pero solo accesible via backend:
  - Endpoint: `/media/private/<id>?key=TU_CLAVE`
