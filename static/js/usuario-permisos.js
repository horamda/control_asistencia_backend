/* Usuarios del panel: con rol admin las casillas de permisos no se aplican (acceso total). Al elegir admin se
   atenua la grilla y se muestra el aviso; las casillas se siguen enviando igual (inert no las deshabilita), asi
   cambiar de rol no borra los permisos ya marcados. */
(function () {
  var rol = document.querySelector('select[name="rol"]');
  var grilla = document.querySelector("[data-permisos-grilla]");
  if (!rol || !grilla) return;
  var avisoAdmin = document.querySelector('[data-permisos-aviso="admin"]');
  var avisoRol = document.querySelector('[data-permisos-aviso="rol"]');

  function actualizar() {
    var admin = rol.value === "admin";
    if (admin) grilla.setAttribute("inert", "");
    else grilla.removeAttribute("inert");
    if (avisoAdmin) avisoAdmin.hidden = !admin;
    if (avisoRol) avisoRol.hidden = admin;
  }

  rol.addEventListener("change", actualizar);
  actualizar();
})();
