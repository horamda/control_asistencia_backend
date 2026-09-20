# Trivias: borrado completo y participacion sin ranking

Desde el detalle de una trivia:
- **Eliminar trivia** muestra cantidades y exige escribir el numero de trivia.
  El POST elimina preguntas, respuestas, resultados, ganador, notificaciones,
  sectores y exclusiones. Recalcula el anual y conserva un registro de auditoria.
- **Participacion sin ranking** permite agregar o quitar personas en esa trivia.
  Conserva puntajes e historial personal; excluye su aporte al ranking de la
  trivia y al anual. El bloqueo de participacion existente sigue siendo independiente.

Ambas operaciones requieren un usuario activo admin/rrhh y proteccion CSRF.
La eliminacion, cambios de elegibilidad y finalizacion reconstruyen la competencia
con bloqueo de la trivia y una sola transaccion; si falla, se revierte.

Antes de desplegar en otro entorno:

```powershell
python scripts/migrate_20260920_02_trivia_ranking_exclusiones.py
```

Migracion aditiva e idempotente: crea una tabla vacia con unicidad por trivia/persona.
Aplicada a la base configurada el 20/09/2026, sin excluir personas ni borrar trivias.
El backend requiere esta tabla antes de iniciar con la nueva version.
Contrato movil 1.28.0: `fuera_ranking` en estado, finalizar e historial propio.
Flutter muestra la condicion sin ocultar el puntaje personal.

Validacion: tests de repositorio con SQL aislado y claves foraneas, rollback
ante error, preservacion de otras trivias, recambio del ganador, cierre atomico,
confirmacion de borrado, roles/CSRF y API personal; test de modelos Flutter y
analisis estatico de las pantallas modificadas. El panel nuevo no fue comprobado
visualmente en produccion; requiere desplegar el codigo.
