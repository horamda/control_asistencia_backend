# Matrices SKAP operativas

Modelo `operativa_0_4` separado del histórico 1–5. Las evaluaciones se vinculan al
ID del empleado (legajo dentro de una empresa), año, rol evaluado y sucursal histórica.
El importador no modifica el puesto ni la sucursal actuales del empleado.

## Puesta en marcha

1. Respaldar la base y conservar los Excel originales fuera del repositorio.
2. Ejecutar `python scripts/migrate_20260919_01_skap_matrices.py` (aditiva, repetible).
3. Actualizar el backend y la app Flutter juntos. El nuevo contenido se consulta
   en la pantalla **Mis evaluaciones**. El backend anterior no sirve estos endpoints.
4. Panel: `/skap/matrices/importar`. Subir un Excel, revisar vínculos y seleccionar
   evaluaciones. Solo admin/RR. HH. de la empresa pueden importar o revertir.

CLI reproducible: `python scripts/import_skap_matrices.py archivo.xlsx --empresa-id 1
--report instance/skap_revision/resultado.json`. Sin `--apply` solo genera informe.
`--mapping` acepta equivalencias confirmadas (nombre original → ID de empleado).
`--exclude-sheet ADMINISTRATIVO` excluye ejemplos de esa hoja en los archivos
iniciales; no se aplica automáticamente a futuros archivos.

## Cálculos y límites

- 0 es una evaluación válida. NA no aporta puntaje ni estándar al denominador.
- Un dato ausente es `sin_evaluar`; se muestra resultado incompleto, no cero.
- Cumplimiento: suma de mínimo(puntaje, estándar) / suma de estándares aplicables × 100.
  Cada contribución se limita por competencia, sin compensar brechas con fortalezas.
  `obtenido` conserva la suma original; `acreditado` es la suma limitada y `expertas`
  cuenta puntajes 4. Los resúmenes se recalculan al consultar (también los ya cargados);
  los archivos, respuestas y resúmenes de importación originales permanecen intactos.
- Las críticas son únicamente A. Una criticidad desconocida impide informar
  cumplimiento crítico definitivo. No se deduce la criticidad por color o vecindad.
- Se conservan los valores y fórmulas de resumen originales como referencia.
  No se ejecutan fórmulas, macros, vínculos externos ni instrucciones del archivo.
- El parser reconoce el formato de los Excel de Almacén y Distribución, con
  encabezado ESTANDAR en F, nombres desde H y competencias en D. Otros formatos
  deben validarse antes de incorporarlos. Archivo máximo 12 MB, contenido 80 MB.
- Los materiales de formación se conservan en el lote de origen; no constituyen
  capacitaciones realizadas ni planes aprobados.
- Las acciones automáticas son propuestas, sin fechas ni responsables inventados.

## Carga inicial verificada

Archivos de Almacén y Distribución: 33 evaluaciones, 28 legajos, 621 respuestas,
18 evaluaciones de Casa Central y 15 de Dolores. Se excluyeron las tres personas
de ejemplo de Administrativo 2019 presentes en ambos libros. Se guardaron seis
equivalencias de nombres confirmadas por el usuario. Las 162 acciones generadas
son propuestas pendientes de asignación. Se preservaron 16 respuestas NA y dos
puntajes ausentes. La conciliación cotejó cada respuesta y su resumen con la
extracción del archivo de origen. Respaldo e informes privados en
`instance/skap_revision/` (excluidos de Git).

## Privacidad e integridad

- API móvil: `/api/skap/matrices` y `/api/skap/matrices/<id>` derivan el empleado
  del JWT, nunca de parámetros. Son solo de lectura, sin rankings.
- Panel personal: `/skap/mis-evaluaciones`, vínculo vigente usuario → empleado.
- Admin/RR. HH.: empresa del usuario. Supervisor: sus reportes directos y su propia
  evaluación; esta última no es editable. Empleado: solo su evaluación.
- La escala anterior continúa disponible; sus listados administrativos quedan
  limitados por empresa. Los supervisores usan la nueva vista con alcance individual.
- Las evaluaciones tienen clave única empresa/empleado/sucursal/rol/año. Importar
  respuestas idénticas las omite; diferencias en una clave existente abortan el lote.
- Cada archivo es una transacción. Un lote de varios archivos CLI se confirma
  archivo por archivo; el informe registra cada resultado por separado.
- Reversión disponible desde Importaciones mientras no exista seguimiento editado.
  Conserva el lote original y registra auditoría. Las equivalencias de nombres
  confirmadas se conservan para futuras cargas.

## Verificación

`python -m pytest tests/test_skap_matrices.py tests/test_skap_service.py
tests/test_skap_routes.py tests/test_skap_seed_service.py`

Los tests ejercitan SQL y transacciones en una base SQLite aislada usando una
adaptación de la migración; la aplicación productiva usa MySQL. Debe comprobarse
también la migración y la importación en MySQL antes del despliegue.
