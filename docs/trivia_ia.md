# Trivias generadas con IA y Configuración de IA

## Qué hace
- **Trivias → «Generar con IA»** (`/admin/trivias/ia/`, admin y rrhh): pegar texto o cargar PDF/DOCX/TXT,
  elegir cantidad, dificultad e indicaciones. La IA propone preguntas; el panel las muestra para editar,
  eliminar, regenerar una o todas, y recién al aprobar se guardan.
- **Sistema → «Configuración de IA»** (`/configuracion-ia/`, solo admin): proveedor (Anthropic, OpenAI,
  Gemini), modelo de cada uno, activar/desactivar, límites, precios para estimar costo, «Probar conexión»,
  «Ver modelos disponibles» y registro de uso.

## Compatibilidad
- Se guarda en `trivias`, `trivia_sectores` y `trivia_preguntas`, con los mismos campos y validaciones del
  alta manual (`normalizar_pregunta` es la misma función para ambos). Cuatro opciones A-D, una correcta,
  10 puntos por defecto. Android no cambia.
- Trivia y preguntas se insertan en una sola transacción (`create_trivia_con_preguntas`): el scheduler nunca
  ve una trivia a medio cargar. El borrador no toca la base hasta aprobarlo.
- Si la IA falla o está apagada, el alta manual funciona igual.

## Variables de entorno (Railway)
| Variable | Uso |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (modelo por defecto `claude-opus-5-5`) |
| `OPENAI_API_KEY` | OpenAI (cargar el modelo en el panel) |
| `GEMINI_API_KEY` | Gemini (cargar el modelo en el panel) |
| `IA_TIMEOUT_SEGUNDOS` | Opcional, 10-110 (por defecto 100; Gunicorn corta a 120) |

Las claves no se guardan en la base ni se muestran. Proveedor, modelos, límites y precios van en
`system_config` (claves `ia_*`). La IA arranca **desactivada**: hay que activarla en el panel.

## Seguridad
- El documento se envía como dato delimitado; el prompt indica no obedecer instrucciones que contenga.
  La salida se valida con esquema JSON y luego con las reglas de FichaYa (formato, largos, duplicados).
- Cada pregunta trae la cita del documento que la fundamenta; si no aparece en el texto se muestra un aviso.
- Archivos: firma real contra extensión, tamaño máximo, PDF cifrado/dañado, DOCX con límite de
  descompresión. `.doc` y `.docm` se rechazan. PDF escaneado: lo lee el modelo (máx. 100 páginas).
- Límites: 10 generaciones por minuto por IP, una generación simultánea por usuario, tope diario y
  presupuesto mensual configurables. Doble envío del formulario de guardado bloqueado por token.
- `ia_uso` registra usuario, proveedor, modelo, tokens, costo y resultado; nunca el contenido.

## Migración
`scripts/migrate_20261115_01_ia_uso.py` (corre sola en `bootstrap_schema.py`): crea la tabla vacía `ia_uso`.
Aditiva; no modifica tablas existentes.

## Reversión
1. Revertir el commit (quita botón, rutas, menú y servicios; el alta manual queda como estaba).
2. Opcional: `DROP TABLE ia_uso; DELETE FROM system_config WHERE config_key LIKE 'ia\_%';
   DELETE FROM app_schema_versions WHERE version='20261115_ia_uso';`
Las trivias ya creadas con IA son trivias normales y siguen funcionando.
