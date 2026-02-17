import datetime


class Validator:
    def __init__(self):
        self.errors = []

    def add(self, message: str):
        self.errors.append(message)

    def require(self, value: str | None, label: str):
        if not (value or "").strip():
            self.add(f"{label} es requerido.")

    def is_int(self, value: str | None, label: str):
        if value and not str(value).isdigit():
            self.add(f"{label} debe ser numerico.")

    def in_set(self, value: str | None, label: str, allowed: set[str]):
        if value and value not in allowed:
            self.add(f"{label} invalido.")

    def email(self, value: str | None):
        if value and "@" not in value:
            self.add("Email invalido.")

    def date_iso(self, value: str | None, label: str):
        if value:
            try:
                datetime.date.fromisoformat(value)
            except ValueError:
                self.add(f"{label} invalida.")

    def ok(self):
        return len(self.errors) == 0


class EmpleadoValidator(Validator):
    def validate(self, form, require_password: bool, emp_id, exists_unique, exists_codigo):
        self.require(form.get("nombre"), "Nombre")
        self.require(form.get("apellido"), "Apellido")
        self.require(form.get("dni"), "DNI")
        self.require(form.get("email"), "Email")
        self.require(form.get("empresa_id"), "Empresa ID")
        self.require(form.get("sucursal_id"), "Sucursal ID")
        self.require(form.get("sector_id"), "Sector")
        self.require(form.get("puesto_id"), "Puesto")
        self.require(form.get("codigo_postal"), "Codigo postal")

        if require_password and not (form.get("password") or "").strip():
            self.add("Contrasena es requerida.")

        for field, label in [
            ("empresa_id", "Empresa ID"),
            ("sucursal_id", "Sucursal ID"),
            ("sector_id", "Sector"),
            ("puesto_id", "Puesto")
        ]:
            self.is_int((form.get(field) or "").strip(), label)

        self.email((form.get("email") or "").strip())

        self.in_set(
            (form.get("estado") or "").strip(),
            "Estado",
            {"activo", "inactivo", "suspendido"}
        )

        self.in_set(
            (form.get("sexo") or "").strip(),
            "Sexo",
            {"masculino", "femenino", "no_binario", "no_informa"}
        )

        self.date_iso((form.get("fecha_nacimiento") or "").strip(), "Fecha de nacimiento")
        self.date_iso((form.get("fecha_ingreso") or "").strip(), "Fecha de ingreso")

        try:
            fecha_nac = form.get("fecha_nacimiento") and datetime.date.fromisoformat(form.get("fecha_nacimiento"))
        except ValueError:
            fecha_nac = None
        try:
            fecha_ing = form.get("fecha_ingreso") and datetime.date.fromisoformat(form.get("fecha_ingreso"))
        except ValueError:
            fecha_ing = None
        if fecha_nac and fecha_ing and fecha_ing < fecha_nac:
            self.add("Fecha de ingreso debe ser posterior a fecha de nacimiento.")

        dni = (form.get("dni") or "").strip()
        if dni and exists_unique("dni", dni, emp_id):
            self.add("DNI ya registrado.")

        email = (form.get("email") or "").strip()
        if email and exists_unique("email", email, emp_id):
            self.add("Email ya registrado.")

        legajo = (form.get("legajo") or "").strip()
        if legajo and exists_unique("legajo", legajo, emp_id):
            self.add("Legajo ya registrado.")

        codigo_postal = (form.get("codigo_postal") or "").strip()
        if codigo_postal and not exists_codigo(codigo_postal):
            self.add("Codigo postal invalido.")

        return self.errors


class UsuarioValidator(Validator):
    def validate(self, form, require_password: bool, user_id, exists_unique):
        usuario = (form.get("usuario") or "").strip()
        empresa_id = (form.get("empresa_id") or "").strip()
        rol = (form.get("rol") or "").strip()
        if rol == "rh":
            rol = "rrhh"

        self.require(usuario, "Usuario")
        self.require(empresa_id, "Empresa")
        self.require(rol, "Rol")
        self.is_int(empresa_id, "Empresa")
        self.in_set(rol, "Rol", {"admin", "rrhh", "supervisor"})

        if require_password and not (form.get("password") or "").strip():
            self.add("Contrasena es requerida.")

        if usuario and exists_unique(usuario, user_id):
            self.add("Usuario ya registrado.")

        return self.errors, usuario, int(empresa_id) if empresa_id.isdigit() else None, rol
