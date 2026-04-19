# Matriz de Permisos por Endpoint

Documento generado automaticamente desde rutas activas del backend.

## Convenciones

| Campo | Descripcion |
|---|---|
| `Auth` | Tipo de autenticacion requerida. |
| `Roles` | Roles permitidos para endpoints web con `role_required`. |
| `Handler` | Archivo y funcion que atiende la ruta. |

## WEB

| Metodo(s) | Endpoint | Auth | Roles | Handler |
|---|---|---|---|---|
| `GET` | `/asistencias/` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:listado` |
| `GET,POST` | `/asistencias/editar/<int:asistencia_id>` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:editar` |
| `POST` | `/asistencias/eliminar/<int:asistencia_id>` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:eliminar` |
| `POST` | `/asistencias/generar-ausentes` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:generar_ausentes_post` |
| `GET` | `/asistencias/horario-esperado` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:horario_esperado` |
| `GET,POST` | `/asistencias/nuevo` | sesion web | admin, rrhh, supervisor | `web/asistencias/asistencias_routes.py:nuevo` |
| `GET` | `/auditoria/` | sesion web | admin | `web/auditoria/auditoria_routes.py:listado` |
| `GET` | `/configuracion-empresa/` | sesion web | admin | `web/configuracion/configuracion_empresa_routes.py:listado` |
| `GET,POST` | `/configuracion-empresa/editar/<int:empresa_id>` | sesion web | admin | `web/configuracion/configuracion_empresa_routes.py:editar` |
| `GET` | `/dashboard` | sesion web | usuario autenticado | `web/web_routes.py:dashboard` |
| `GET` | `/adelantos/` | sesion web | admin, rrhh | `web/adelantos/adelantos_routes.py:listado` |
| `GET` | `/adelantos/export.csv` | sesion web | admin, rrhh | `web/adelantos/adelantos_routes.py:export_csv` |
| `POST` | `/adelantos/aprobar/<int:adelanto_id>` | sesion web | admin, rrhh | `web/adelantos/adelantos_routes.py:aprobar` |
| `POST` | `/adelantos/rechazar/<int:adelanto_id>` | sesion web | admin, rrhh | `web/adelantos/adelantos_routes.py:rechazar` |
| `GET` | `/pedidos-mercaderia/` | sesion web | admin, rrhh | `web/pedidos_mercaderia/pedidos_mercaderia_routes.py:listado` |
| `GET` | `/pedidos-mercaderia/export.csv` | sesion web | admin, rrhh | `web/pedidos_mercaderia/pedidos_mercaderia_routes.py:export_csv` |
| `POST` | `/pedidos-mercaderia/aprobar/<int:pedido_id>` | sesion web | admin, rrhh | `web/pedidos_mercaderia/pedidos_mercaderia_routes.py:aprobar` |
| `POST` | `/pedidos-mercaderia/rechazar/<int:pedido_id>` | sesion web | admin, rrhh | `web/pedidos_mercaderia/pedidos_mercaderia_routes.py:rechazar` |
| `GET,POST` | `/pedidos-mercaderia/articulos/importar-csv` | sesion web | admin, rrhh | `web/pedidos_mercaderia/pedidos_mercaderia_routes.py:importar_csv` |
| `GET` | `/empleado-excepciones/` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:listado` |
| `POST` | `/empleado-excepciones/api` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:api_create` |
| `GET` | `/empleado-excepciones/api/<int:excepcion_id>` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:api_get` |
| `PUT` | `/empleado-excepciones/api/<int:excepcion_id>` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:api_update` |
| `GET,POST` | `/empleado-excepciones/editar/<int:excepcion_id>` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:editar` |
| `POST` | `/empleado-excepciones/eliminar/<int:excepcion_id>` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:eliminar` |
| `GET,POST` | `/empleado-excepciones/nuevo` | sesion web | admin, rrhh | `web/empleado_excepciones/empleado_excepciones_routes.py:nuevo` |
| `GET` | `/empleado-horarios/` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:listado` |
| `GET,POST` | `/empleado-horarios/<int:empleado_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:asignar` |
| `GET,POST` | `/empleado-horarios/<int:empleado_id>/editar/<int:asignacion_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:editar` |
| `POST` | `/empleado-horarios/<int:empleado_id>/eliminar/<int:asignacion_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:eliminar` |
| `POST` | `/empleado-horarios/api` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:api_asignar` |
| `DELETE` | `/empleado-horarios/api/<int:asignacion_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:api_eliminar` |
| `PUT` | `/empleado-horarios/api/<int:asignacion_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:api_editar` |
| `GET` | `/empleado-horarios/api/<int:empleado_id>` | sesion web | admin, rrhh | `web/empleado_horarios/empleado_horarios_routes.py:api_historial` |
| `GET` | `/empleado-roles/` | sesion web | admin | `web/roles/empleado_roles_routes.py:listado` |
| `GET,POST` | `/empleado-roles/<int:empleado_id>` | sesion web | admin | `web/roles/empleado_roles_routes.py:editar` |
| `GET` | `/empleados/` | sesion web | admin, rrhh | `web/empleados/empleados_routes.py:listado` |
| `GET` | `/empleados/activar/<int:emp_id>` | sesion web | admin, rrhh | `web/empleados/empleados_routes.py:activar` |
| `GET` | `/empleados/desactivar/<int:emp_id>` | sesion web | admin, rrhh | `web/empleados/empleados_routes.py:desactivar` |
| `GET,POST` | `/empleados/editar/<int:emp_id>` | sesion web | admin, rrhh | `web/empleados/empleados_routes.py:editar` |
| `GET,POST` | `/empleados/nuevo` | sesion web | admin, rrhh | `web/empleados/empleados_routes.py:nuevo` |
| `GET` | `/empresas/` | sesion web | admin | `web/empresas/empresas_routes.py:listado` |
| `GET` | `/empresas/activar/<int:empresa_id>` | sesion web | admin | `web/empresas/empresas_routes.py:activar` |
| `GET` | `/empresas/desactivar/<int:empresa_id>` | sesion web | admin | `web/empresas/empresas_routes.py:desactivar` |
| `GET,POST` | `/empresas/editar/<int:empresa_id>` | sesion web | admin | `web/empresas/empresas_routes.py:editar` |
| `GET,POST` | `/empresas/nuevo` | sesion web | admin | `web/empresas/empresas_routes.py:nuevo` |
| `GET` | `/francos/` | sesion web | admin, rrhh | `web/francos/francos_routes.py:listado` |
| `GET,POST` | `/francos/editar/<int:franco_id>` | sesion web | admin, rrhh | `web/francos/francos_routes.py:editar` |
| `POST` | `/francos/eliminar/<int:franco_id>` | sesion web | admin, rrhh | `web/francos/francos_routes.py:eliminar` |
| `GET,POST` | `/francos/nuevo` | sesion web | admin, rrhh | `web/francos/francos_routes.py:nuevo` |
| `GET` | `/horarios/` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:listado` |
| `GET` | `/horarios/activar/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:activar` |
| `GET` | `/horarios/api` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:api_list` |
| `POST` | `/horarios/api` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:api_create` |
| `DELETE` | `/horarios/api/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:api_delete` |
| `GET` | `/horarios/api/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:api_get` |
| `PUT` | `/horarios/api/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:api_update` |
| `GET` | `/horarios/desactivar/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:desactivar` |
| `GET,POST` | `/horarios/editar/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:editar` |
| `POST` | `/horarios/eliminar/<int:horario_id>` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:eliminar` |
| `GET,POST` | `/horarios/nuevo` | sesion web | admin, rrhh | `web/horarios/horarios_routes.py:nuevo` |
| `GET` | `/justificaciones/` | sesion web | admin, rrhh, supervisor | `web/justificaciones/justificaciones_routes.py:listado` |
| `GET,POST` | `/justificaciones/editar/<int:justificacion_id>` | sesion web | admin, rrhh, supervisor | `web/justificaciones/justificaciones_routes.py:editar` |
| `POST` | `/justificaciones/eliminar/<int:justificacion_id>` | sesion web | admin, rrhh, supervisor | `web/justificaciones/justificaciones_routes.py:eliminar` |
| `GET,POST` | `/justificaciones/nuevo` | sesion web | admin, rrhh, supervisor | `web/justificaciones/justificaciones_routes.py:nuevo` |
| `GET` | `/localidades/` | sesion web | admin | `web/localidades/localidades_routes.py:listado` |
| `GET,POST` | `/localidades/editar/<codigo_postal>` | sesion web | admin | `web/localidades/localidades_routes.py:editar` |
| `POST` | `/localidades/eliminar/<codigo_postal>` | sesion web | admin | `web/localidades/localidades_routes.py:eliminar` |
| `GET,POST` | `/localidades/nuevo` | sesion web | admin | `web/localidades/localidades_routes.py:nuevo` |
| `GET,POST` | `/login` | publico | - | `web/auth/web_auth_routes.py:login` |
| `GET` | `/logout` | publico | - | `web/auth/web_auth_routes.py:logout` |
| `GET` | `/puestos/` | sesion web | admin | `web/puestos/puestos_routes.py:listado` |
| `GET` | `/puestos/activar/<int:puesto_id>` | sesion web | admin | `web/puestos/puestos_routes.py:activar` |
| `GET` | `/puestos/desactivar/<int:puesto_id>` | sesion web | admin | `web/puestos/puestos_routes.py:desactivar` |
| `GET,POST` | `/puestos/editar/<int:puesto_id>` | sesion web | admin | `web/puestos/puestos_routes.py:editar` |
| `GET,POST` | `/puestos/nuevo` | sesion web | admin | `web/puestos/puestos_routes.py:nuevo` |
| `GET,POST` | `/qr-puerta/` | sesion web | admin, rrhh | `web/qr_puerta/qr_puerta_routes.py:generar` |
| `GET` | `/qr-puerta/imprimir/<int:empresa_id>` | sesion web | admin, rrhh | `web/qr_puerta/qr_puerta_routes.py:imprimir` |
| `GET` | `/qr-puerta/reimprimir/<int:historial_id>` | sesion web | admin, rrhh | `web/qr_puerta/qr_puerta_routes.py:reimprimir` |
| `GET` | `/roles/` | sesion web | admin | `web/roles/roles_routes.py:listado` |
| `GET,POST` | `/roles/editar/<int:rol_id>` | sesion web | admin | `web/roles/roles_routes.py:editar` |
| `POST` | `/roles/eliminar/<int:rol_id>` | sesion web | admin | `web/roles/roles_routes.py:eliminar` |
| `GET,POST` | `/roles/nuevo` | sesion web | admin | `web/roles/roles_routes.py:nuevo` |
| `GET` | `/sectores/` | sesion web | admin | `web/sectores/sectores_routes.py:listado` |
| `GET` | `/sectores/activar/<int:sector_id>` | sesion web | admin | `web/sectores/sectores_routes.py:activar` |
| `GET` | `/sectores/desactivar/<int:sector_id>` | sesion web | admin | `web/sectores/sectores_routes.py:desactivar` |
| `GET,POST` | `/sectores/editar/<int:sector_id>` | sesion web | admin | `web/sectores/sectores_routes.py:editar` |
| `GET,POST` | `/sectores/nuevo` | sesion web | admin | `web/sectores/sectores_routes.py:nuevo` |
| `GET` | `/sucursales/` | sesion web | admin | `web/sucursales/sucursales_routes.py:listado` |
| `GET` | `/sucursales/activar/<int:sucursal_id>` | sesion web | admin | `web/sucursales/sucursales_routes.py:activar` |
| `GET` | `/sucursales/desactivar/<int:sucursal_id>` | sesion web | admin | `web/sucursales/sucursales_routes.py:desactivar` |
| `GET,POST` | `/sucursales/editar/<int:sucursal_id>` | sesion web | admin | `web/sucursales/sucursales_routes.py:editar` |
| `GET,POST` | `/sucursales/nuevo` | sesion web | admin | `web/sucursales/sucursales_routes.py:nuevo` |
| `GET` | `/usuarios/` | sesion web | admin | `web/usuarios/usuarios_routes.py:listado` |
| `GET` | `/usuarios/activar/<int:user_id>` | sesion web | admin | `web/usuarios/usuarios_routes.py:activar` |
| `GET` | `/usuarios/desactivar/<int:user_id>` | sesion web | admin | `web/usuarios/usuarios_routes.py:desactivar` |
| `GET,POST` | `/usuarios/editar/<int:user_id>` | sesion web | admin | `web/usuarios/usuarios_routes.py:editar` |
| `GET,POST` | `/usuarios/nuevo` | sesion web | admin | `web/usuarios/usuarios_routes.py:nuevo` |
| `GET` | `/vacaciones/` | sesion web | admin, rrhh | `web/vacaciones/vacaciones_routes.py:listado` |
| `GET,POST` | `/vacaciones/editar/<int:vacacion_id>` | sesion web | admin, rrhh | `web/vacaciones/vacaciones_routes.py:editar` |
| `POST` | `/vacaciones/eliminar/<int:vacacion_id>` | sesion web | admin, rrhh | `web/vacaciones/vacaciones_routes.py:eliminar` |
| `GET,POST` | `/vacaciones/nuevo` | sesion web | admin, rrhh | `web/vacaciones/vacaciones_routes.py:nuevo` |

## API

| Metodo(s) | Endpoint | Auth | Roles | Handler |
|---|---|---|---|---|
| `POST` | `/api/v1/mobile/auth/login` | publico | - | `routes/mobile_v1_routes.py:auth_login` |
| `POST` | `/api/v1/mobile/auth/refresh` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:auth_refresh` |
| `GET` | `/api/v1/mobile/me` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me` |
| `GET` | `/api/v1/mobile/me/asistencias` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_asistencias` |
| `GET` | `/api/v1/mobile/me/estadisticas` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_estadisticas` |
| `GET` | `/api/v1/mobile/me/config-asistencia` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_config_asistencia` |
| `GET` | `/api/v1/mobile/me/eventos-seguridad` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_eventos_seguridad` |
| `POST` | `/api/v1/mobile/me/fichadas/entrada` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:fichar_entrada` |
| `POST` | `/api/v1/mobile/me/fichadas/salida` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:fichar_salida` |
| `POST` | `/api/v1/mobile/me/fichadas/scan` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:fichar_scan_qr` |
| `GET` | `/api/v1/mobile/me/horario-esperado` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_horario_esperado` |
| `GET` | `/api/v1/mobile/me/marcas` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_marcas` |
| `PUT` | `/api/v1/mobile/me/password` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_update_password` |
| `PUT` | `/api/v1/mobile/me/perfil` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_update_profile` |
| `DELETE` | `/api/v1/mobile/me/perfil/foto` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_delete_profile_photo` |
| `GET` | `/api/v1/mobile/me/adelantos/resumen` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_adelantos_resumen` |
| `GET` | `/api/v1/mobile/me/adelantos` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_adelantos_list` |
| `GET` | `/api/v1/mobile/me/adelantos/<int:adelanto_id>` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_adelantos_detail` |
| `GET` | `/api/v1/mobile/me/adelantos/estado` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_adelantos_estado` |
| `POST` | `/api/v1/mobile/me/adelantos` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_adelantos_create` |
| `GET` | `/api/v1/mobile/me/pedidos-mercaderia/resumen` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_resumen` |
| `GET` | `/api/v1/mobile/me/pedidos-mercaderia/estado` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_estado` |
| `GET` | `/api/v1/mobile/me/pedidos-mercaderia/articulos` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_articulos` |
| `GET` | `/api/v1/mobile/me/pedidos-mercaderia` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_list` |
| `GET` | `/api/v1/mobile/me/pedidos-mercaderia/<int:pedido_id>` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_detail` |
| `POST` | `/api/v1/mobile/me/pedidos-mercaderia` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_create` |
| `PUT` | `/api/v1/mobile/me/pedidos-mercaderia/<int:pedido_id>` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_update` |
| `DELETE` | `/api/v1/mobile/me/pedidos-mercaderia/<int:pedido_id>` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_pedidos_mercaderia_cancel` |
| `POST` | `/api/v1/mobile/me/qr` | token movil (Bearer) | empleado autenticado | `routes/mobile_v1_routes.py:me_generar_qr` |
| `POST` | `/auth/login` | publico | - | `routes/auth_routes.py:login` |
| `GET` | `/media/empleados/foto/<dni>` | publico | - | `routes/media_routes.py:empleado_foto` |
| `GET` | `/empleados/imagen/<dni>` | publico | - | `routes/media_routes.py:empleado_imagen` |
| `GET` | `/media/legajos/adjunto/<int:adjunto_id>` | sesion web | admin, rrhh, supervisor | `routes/media_routes.py:legajo_adjunto` |
