# Deploy en Railway

## Backend

Crear un servicio para `backend` y configurar el archivo de Railway como
`/backend/railway.toml` si el repositorio se despliega como monorepo.

Variables requeridas:

```env
APP_ENV=production
SECRET_KEY=<clave-aleatoria-minimo-32-caracteres>
JWT_SECRET=<clave-aleatoria-minimo-32-caracteres>
JWT_EXPIRE_MINUTES=720
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=Lax
CORS_ALLOWED_ORIGINS=https://<frontend>
```

`JWT_SECRET` es una credencial permanente del servicio backend. Debe crearse una
sola vez como variable de Railway y conservar exactamente el mismo valor entre
deploys. No debe definirse en `railway.toml`, generarse durante el build ni
reemplazarse con el valor de un `.env` local. Cambiarla invalida inmediatamente
los QR vigentes y los tokens móviles firmados con la clave anterior. La
aplicación valida esta variable al arrancar y rechaza el despliegue si falta, si
es una clave de plantilla o si tiene menos de 32 caracteres.

Para habilitar la API externa de reportes con usuario, contrasena y token:

```env
EXTERNAL_API_USERNAME=ApiFichaYa
EXTERNAL_API_PASSWORD_HASH=<hash-generado-con-werkzeug>
EXTERNAL_API_JWT_SECRET=<clave-aleatoria-minimo-32-caracteres>
EXTERNAL_API_TOKEN_TTL_MINUTES=60
```

`EXTERNAL_API_KEY` queda disponible como mecanismo anterior opcional. El contrato y los comandos para generar los secretos estan en `docs/external_api_contract.md`.

Para MySQL de Railway se pueden usar directamente las variables que expone el
servicio de base:

```env
MYSQLHOST=${{MySQL.MYSQLHOST}}
MYSQLPORT=${{MySQL.MYSQLPORT}}
MYSQLUSER=${{MySQL.MYSQLUSER}}
MYSQLPASSWORD=${{MySQL.MYSQLPASSWORD}}
MYSQLDATABASE=${{MySQL.MYSQLDATABASE}}
```

Tambien siguen funcionando las variables historicas `DB_HOST`, `DB_PORT`,
`DB_USER`, `DB_PASSWORD` y `DB_NAME`.

Antes del primer deploy, la base MySQL debe tener el esquema inicial del sistema.
El arranque de la app inicializa el ORM y asegura indices sobre tablas existentes
como `empleado_horarios` y `asistencias`; si la base esta vacia, el contenedor
puede fallar al iniciar. Para una base nueva de Railway, importar primero un dump
del esquema/datos actuales y luego aplicar las migraciones pendientes de
`migrations/` o los scripts idempotentes de `scripts/migrate_*.py` que
correspondan.

El contenedor arranca con Gunicorn y escucha en `0.0.0.0:$PORT`, que Railway
inyecta automaticamente. El healthcheck publico queda en `/healthz`.

Si se usan adjuntos o fotos en almacenamiento local, crear un volumen y montar
el directorio persistente en la ruta que use `FOTO_LOCAL_DIR` o
`LEGAJO_LOCAL_DIR`. Para evitar depender del filesystem efimero, el default de
fotos y legajos es guardar en base de datos.

## Frontend Flutter

Hay dos formas de usar el frontend:

### App mobile

Para mobile no se despliega la app en Railway: se compila apuntando al dominio
publico del backend.

```bash
flutter build apk --release \
  --dart-define=APP_FLAVOR=PROD \
  --dart-define=APP_PROD=true \
  --dart-define=API_BASE_URL=https://<backend>.up.railway.app
```

### Flutter Web en Railway

Crear otro servicio para `frontend_flutter` y configurar el archivo de Railway
como `/frontend_flutter/railway.toml` si el repositorio se despliega como
monorepo.

Variable requerida en el servicio frontend:

```env
API_BASE_URL=https://${{Backend.RAILWAY_PUBLIC_DOMAIN}}
```

Variables opcionales:

```env
APP_FLAVOR=PROD
APP_PROD=true
MOBILE_API_PREFIX=/api/v1/mobile
MOBILE_CONTRACT_VERSION=1.24.0
SESSION_IDLE_TIMEOUT_MINUTES=20
SESSION_MAX_AGE_HOURS=10
SESSION_PROACTIVE_REFRESH_MINUTES=8
```

En el backend, restringir CORS al dominio del frontend:

```env
CORS_ALLOWED_ORIGINS=https://${{Frontend.RAILWAY_PUBLIC_DOMAIN}}
```

El frontend usa Docker multi-stage: compila Flutter Web y sirve `build/web` con
Nginx escuchando en el `PORT` que Railway inyecta.
