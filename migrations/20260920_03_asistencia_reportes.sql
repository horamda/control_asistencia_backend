CREATE OR REPLACE VIEW asistencia_marcas_reporte AS
SELECT m.id,m.empresa_id,m.empleado_id,m.asistencia_id,m.fecha,m.hora,m.accion,m.metodo,m.tipo_marca,m.lat,m.lon,m.foto,m.gps_ok,m.gps_distancia_m,m.gps_tolerancia_m,m.gps_ref_lat,m.gps_ref_lon,m.estado,m.observaciones,m.fecha_creacion,m.corregida_manualmente, 0 AS es_resumen
FROM asistencia_marcas m
UNION ALL
SELECT NULL,a.empresa_id,a.empleado_id,a.id,a.fecha,a.hora_entrada,'ingreso',COALESCE(a.metodo_entrada, 'manual'),'jornada',a.lat_entrada,a.lon_entrada,a.foto_entrada,a.gps_ok_entrada,a.gps_distancia_entrada_m,a.gps_tolerancia_entrada_m,a.gps_ref_lat_entrada,a.gps_ref_lon_entrada,a.estado,a.observaciones,a.created_at,0, 1 AS es_resumen
FROM asistencias a
WHERE a.hora_entrada IS NOT NULL AND NOT EXISTS (SELECT 1 FROM asistencia_marcas m WHERE m.empleado_id=a.empleado_id AND m.fecha=a.fecha)
UNION ALL
SELECT NULL,a.empresa_id,a.empleado_id,a.id,a.fecha,a.hora_salida,'egreso',COALESCE(a.metodo_salida, 'manual'),'jornada',a.lat_salida,a.lon_salida,a.foto_salida,a.gps_ok_salida,a.gps_distancia_salida_m,a.gps_tolerancia_salida_m,a.gps_ref_lat_salida,a.gps_ref_lon_salida,a.estado,a.observaciones,a.created_at,0, 1 AS es_resumen
FROM asistencias a
WHERE a.hora_salida IS NOT NULL AND NOT EXISTS (SELECT 1 FROM asistencia_marcas m WHERE m.empleado_id=a.empleado_id AND m.fecha=a.fecha);
