# Campeón de la Seguridad

Acceso: Seguridad e Higiene → Campeón de la Seguridad (`/seguridad-higiene/campeon`).
Consulta mensual o anual por empresa. El período abierto muestra resultados
provisionales; solo los períodos finalizados admiten confirmación.

## Reglas editables

Valores iniciales por empresa:

- Seguro aprobado: +1 punto.
- Inseguro aprobado: 0 puntos; impide ser elegible porque el máximo inicial es 0.
- Mínimo 3 seguros en 3 fechas distintas.
- Agrupación por sucursal; se puede elegir puesto, sucursal y puesto o toda la empresa.
- Solo empleados activos; se puede incluir también inactivos.
- Empates: todos los candidatos con el mayor puntaje elegible comparten el reconocimiento.

Los puntos por seguro aceptan enteros de 1 a 1000; los puntos por inseguro, de
-1000 a 0. Los mínimos y el máximo de inseguros también son editables. Guardar
recalcula propuestas de cualquier período; no cambia reconocimientos confirmados.

Cada empleado se cuenta una vez por evento, aunque tenga reportes repetidos en
una fecha. El requisito de fechas distintas se aplica a los seguros. Los empleados
sin observaciones aparecen con cero y el motivo de no elegibilidad. Las fichas y
relaciones actuales de FichaYa determinan nombre, legajo, puesto y sucursal.
Los externos no participan. Accidentes e incidentes no suman, restan ni excluyen.

## Confirmación y permisos

`ver` permite consultar; `editar` modifica reglas; `aprobar` confirma un grupo.
Todos los POST usan la protección CSRF del panel. Se aplica el alcance de empresa
del usuario. Las reglas llevan revisión para impedir sobrescribir cambios ajenos.

La confirmación vuelve a calcular los resultados y comprueba la firma de los datos
mostrados. Si cambiaron reglas, empleados o puntajes exige revisar nuevamente.
No se puede confirmar un período abierto, sin elegibles o ya confirmado para ese
grupo y agrupación. Una clave única y un bloqueo de empresa evitan duplicaciones.
Cambiar la agrupación permite reconocimientos de otro alcance (por ejemplo, empresa
y sucursal); ambos quedan visibles en el historial del período.

Se guardan ganadores empatados, puntos, reglas, revisión, datos de ficha y usuario
que confirmó. Las reglas y resultados originales permanecen consultables aunque
se cambie la configuración. Las modificaciones y confirmaciones tienen auditoría.
La selección final requiere revisión humana; más observaciones no equivalen por
sí solas a menor riesgo ni a una comparación uniforme entre puestos.

## Instalación

`python scripts/migrate_20261007_01_seguridad_campeon.py`

Crea `sh_campeon_reglas` y `sh_campeon_premios`, sin alterar reportes ni conceder
premios. Aplicada a la base configurada el 07/10/2026. El backend necesita despliegue.
Esta funcionalidad es administrativa; no se agregaron endpoints de premios a Flutter.
