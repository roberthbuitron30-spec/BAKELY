from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import (
    CorteDestilacion, Estacion, Lote, MovimientoKardex, PerfilUsuario, RegistroEtapa, Rol, UbicacionWMS,
)

User = get_user_model()


class GlassMixin:
    """Aplica clases CSS del tema a todos los widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            css = "form-check-input" if isinstance(f.widget, forms.CheckboxInput) else "form-control glass-input"
            if isinstance(f.widget, forms.Select):
                css = "form-select glass-input"
            f.widget.attrs.setdefault("class", css)

    def bloquear(self):
        """Deshabilita todos los campos (vista de solo lectura con candado)."""
        for f in self.fields.values():
            f.disabled = True
        return self


# ------------------------------------------------------------------ eBR
class RegistroEtapaForm(GlassMixin, forms.ModelForm):
    variables_texto = forms.CharField(
        label="Variables medidas", required=False,
        help_text="Una por línea: clave = valor (p. ej. ph = 3.9)",
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "temp_secado_c = 48\nhumedad_final_pct = 11.4"}),
    )

    class Meta:
        model = RegistroEtapa
        fields = ["estacion", "etapa", "control", "equipo", "lote", "cantidad_entrada", "cantidad_salida",
                  "merma", "observaciones"]
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 2})}
        labels = {"estacion": "Estación", "cantidad_entrada": "Cantidad de entrada",
                  "cantidad_salida": "Cantidad de salida", "control": "Punto de control"}

    def clean_variables_texto(self):
        out = {}
        for linea in (self.cleaned_data.get("variables_texto") or "").splitlines():
            if not linea.strip():
                continue
            if "=" not in linea:
                raise forms.ValidationError(f"Línea inválida: «{linea}». Use clave = valor.")
            k, v = [x.strip() for x in linea.split("=", 1)]
            try:
                out[k] = float(v.replace(",", "."))
            except ValueError:
                out[k] = v
        return out


class CorteDestilacionForm(GlassMixin, forms.ModelForm):
    class Meta:
        model = CorteDestilacion
        exclude = ["registro", "curva_termica"]
        labels = {
            "cabezas_l": "Cabezas (L)", "abv_cabezas": "ABV cabezas (%)", "corazon_l": "Corazón (L)",
            "abv_corazon": "ABV corazón (%)", "colas_l": "Colas (L)", "abv_colas": "ABV colas (%)",
            "temp_vapor_corte_cabeza_c": "Vapor al corte de cabeza (°C)",
            "temp_vapor_corte_cola_c": "Vapor al corte de cola (°C)",
        }


# ------------------------------------------------------------------ WMS
class MovimientoForm(GlassMixin, forms.Form):
    tipo = forms.ChoiceField(choices=MovimientoKardex.Tipo.choices)
    lote = forms.ModelChoiceField(queryset=Lote.objects.exclude(estado="AGOTADO").select_related("producto"))
    cantidad = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)
    ubicacion_origen = forms.ModelChoiceField(queryset=UbicacionWMS.objects.filter(activa=True), required=False,
                                              label="Ubicación de origen")
    ubicacion_destino = forms.ModelChoiceField(queryset=UbicacionWMS.objects.filter(activa=True), required=False,
                                               label="Ubicación de destino")
    motivo_merma = forms.ChoiceField(choices=[("", "—")] + list(MovimientoKardex.MotivoMerma.choices), required=False,
                                     label="Motivo de merma")
    referencia = forms.CharField(max_length=80, required=False)


class RecepcionMPForm(GlassMixin, forms.Form):
    """Recepción de tubérculos/insumos: crea lote MP + entrada a Kardex."""
    producto = forms.ModelChoiceField(queryset=None)
    cantidad = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3, label="Peso neto / cantidad")
    proveedor = forms.CharField(max_length=120)
    origen_geografico = forms.CharField(max_length=120, required=False, label="Procedencia (parroquia/cantón)")
    ubicacion = forms.ModelChoiceField(queryset=UbicacionWMS.objects.filter(activa=True), label="Ubicación")
    fecha_caducidad = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Producto
        self.fields["producto"].queryset = Producto.objects.filter(categoria__tipo__in=["MP", "INS", "EMP"])
        self.fields["producto"].widget.attrs["class"] = "form-select glass-input"


# ------------------------------------------------------------------ Usuarios (admin)
class UsuarioPlantaForm(GlassMixin, forms.ModelForm):
    rol = forms.ChoiceField(choices=Rol.choices)
    estacion = forms.ChoiceField(choices=[("", "— Sin estación —")] + list(Estacion.choices), required=False,
                                 label="Estación asignada")
    estacion_activa = forms.BooleanField(required=False, initial=True, label="Puede editar su estación")
    codigo_empleado = forms.CharField(max_length=20, required=False, label="Código de empleado")
    cedula = forms.CharField(max_length=13, required=False, label="Cédula")
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        perfil = getattr(self.instance, "perfil", None) if self.instance.pk else None
        if perfil:
            for f in ("rol", "estacion", "estacion_activa", "codigo_empleado", "cedula"):
                self.fields[f].initial = getattr(perfil, f)
        if not self.instance.pk:
            self.fields["password1"].required = True
            self.fields["password2"].required = True

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                validate_password(p1, self.instance)
        if data.get("rol") == Rol.OPERARIO and not data.get("estacion"):
            self.add_error("estacion", "Asigne una estación al operario.")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        user.is_staff = self.cleaned_data["rol"] == Rol.ADMIN
        if commit:
            user.save()
            from django.utils import timezone
            perfil, _ = PerfilUsuario.objects.get_or_create(usuario=user)
            perfil.rol = self.cleaned_data["rol"]
            perfil.estacion = self.cleaned_data.get("estacion") or ""
            perfil.estacion_activa = self.cleaned_data.get("estacion_activa", True)
            perfil.codigo_empleado = self.cleaned_data.get("codigo_empleado", "")
            perfil.cedula = self.cleaned_data.get("cedula", "")
            if self.cleaned_data.get("password1"):
                perfil.ultimo_cambio_clave = timezone.now()
            perfil.save()
        return user


# ------------------------------------------------------------------ Tienda
class CheckoutForm(GlassMixin, forms.Form):
    nombre = forms.CharField(max_length=120)
    email = forms.EmailField()
    telefono = forms.CharField(max_length=20, required=False, label="Teléfono")
    direccion = forms.CharField(max_length=200, label="Dirección de entrega")
    declara_mayor_edad = forms.BooleanField(
        required=False, label="Declaro ser mayor de 18 años (obligatorio si compro bebidas alcohólicas)"
    )
