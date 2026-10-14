"""
Carga datos iniciales de BAKELY: catálogo de 9 ítems, zonas WMS, equipos con límites IoT,
usuarios por estación, órdenes, lotes, eBR, cortes PCC-1, Kardex y un despacho al CEDI.

    python manage.py seed_bakely            # idempotente sobre catálogo/ubicaciones/usuarios
    python manage.py seed_bakely --demo     # además genera operación de ejemplo
    python manage.py seed_bakely --password MiClave2026!
"""
import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import services
from core.models import (
    Categoria, ConteoCiclico, CorteDestilacion, Despacho, DetalleDespacho, Equipo, Estacion, Existencia,
    LecturaIoT, Lote, OrdenProduccion, PerfilUsuario, Producto, RegistroEtapa, Rol, UbicacionWMS,
    UnidadSerializada, Zona,
)

User = get_user_model()

CATEGORIAS = [
    ("tuberculos", "Tubérculos para almidón", "MP", "ALMIDON", "sprout"),
    ("insumos-fermentacion", "Insumos de fermentación", "INS", "BEBIDA", "flask-conical"),
    ("empaques", "Envases y empaques", "EMP", "COMUN", "package"),
    ("almidones", "Almidones Andinos", "PT", "ALMIDON", "wheat"),
    ("licores-destilados", "Licores destilados", "PT", "BEBIDA", "wine"),
    ("bebidas-fermentadas", "Bebidas fermentadas", "PT", "BEBIDA", "beer"),
]

PRODUCTOS = [
    dict(codigo="MP-TUB-001", nombre="Papa Andina / Yuca para Almidón", cat="tuberculos", linea="ALMIDON",
         unidad_medida="kg", regla_rotacion="FIFO", zona_wms_default="ZONA-REC", estacion_responsable="RECEPCION",
         imagen_alt="Tubérculos seleccionados de papa andina y yuca en tolva de lavado",
         descripcion_corta="Tubérculos frescos seleccionados de productores del Carchi.",
         descripcion_tecnica="Papa (Solanum tuberosum, variedades andinas) y yuca (Manihot esculenta) seleccionadas "
                             "por materia seca. Se reciben a granel, se pesan y se inspeccionan en PC-1.",
         flujo_operativo=["Recepción y pesaje", "Análisis PC-1", "Lavado", "Rallado"],
         parametros_tecnicos={"humedad_max_pct": 82, "impurezas_max_pct": 3, "materia_seca_min_pct": 18},
         vida_util_dias=15),
    dict(codigo="MP-LEV-002", nombre="Levadura Enológica Seleccionada", cat="insumos-fermentacion", linea="BEBIDA",
         unidad_medida="kg", regla_rotacion="FEFO", zona_wms_default="ZONA-FRIO", estacion_responsable="FERMENTACION",
         imagen_alt="Empaque hermético al vacío de levadura seca activa",
         descripcion_corta="Saccharomyces cerevisiae seca activa en empaque al vacío.",
         descripcion_tecnica="Cepa seleccionada para fermentación alcohólica limpia. Conservar a 4–8 °C. "
                             "Rehidratar a 35–38 °C antes de inocular.",
         flujo_operativo=["Almacén frío", "Reactivación", "Inoculación en tanque"],
         parametros_tecnicos={"temp_almacen_c": [4, 8], "dosis_g_hl": [20, 30]}, vida_util_dias=540),
    dict(codigo="EMP-BOT-003", nombre="Botella de Vidrio 750 ml con Tapa", cat="empaques", linea="BEBIDA",
         unidad_medida="und", regla_rotacion="FIFO", zona_wms_default="ZONA-EMP", estacion_responsable="ENVASADO",
         imagen_alt="Botella de vidrio transparente de 750 ml con corcho sintético",
         descripcion_corta="Botella de vidrio flint/ámbar de 750 ml con corcho sintético.",
         descripcion_tecnica="Vidrio tipo III, boca para corcho de 19 mm. Inspección física de fisuras y limpieza "
                             "antes de la línea de llenado.",
         flujo_operativo=["Inspección física", "Enjuague", "Línea de llenado"], parametros_tecnicos={"capacidad_ml": 750},
         contenido_neto=Decimal("1")),
    dict(codigo="EMP-SAC-004", nombre="Saco Multicapa 25 kg para Almidón", cat="empaques", linea="ALMIDON",
         unidad_medida="und", regla_rotacion="FIFO", zona_wms_default="ZONA-EMP", estacion_responsable="ENVASADO",
         imagen_alt="Saco de papel kraft industrial multicapa con barrera antihumedad",
         descripcion_corta="Saco kraft de 3 pliegos con lámina interna antihumedad.",
         descripcion_tecnica="Papel kraft extensible + film PE intermedio. Válvula de llenado. Apto para contacto "
                             "con alimentos.",
         flujo_operativo=["Envasado de almidón seco", "Cosido / sellado", "Paletizado"],
         parametros_tecnicos={"capacidad_kg": 25}),
    dict(codigo="PT-ALM-PAP-01", nombre="Almidón Nativo de Papa Andina", cat="almidones", linea="ALMIDON",
         unidad_medida="kg", regla_rotacion="FEFO", zona_wms_default="ZONA-ALM-SECOS", estacion_responsable="ALMIDONES",
         imagen_alt="Polvo blanco ultrafino de almidón de papa en cuenco junto a saco sellado de 25 kg",
         descripcion_corta="Almidón de alta pureza, gran poder espesante y geles transparentes.",
         descripcion_tecnica="Almidón nativo extraído por vía húmeda, secado a 45–50 °C. Humedad ≤ 12 %, "
                             "cenizas ≤ 0,5 %. Granulometría fina tras tamizado.",
         flujo_operativo=["Extracción", "Sedimentación", "Secado PC-2", "Tamizado", "Envasado", "Bodega ZONA-ALM-SECOS"],
         parametros_tecnicos={"humedad_max_pct": 12, "cenizas_max_pct": 0.5, "temp_secado_c": [45, 50]},
         presentacion="Saco multicapa 25 kg · también bolsa 1 kg", contenido_neto=Decimal("25"),
         notas_sensoriales="Polvo blanco brillante, inodoro, tacto crujiente característico.",
         usos_recomendados="Espesante de salsas y sopas, rebozados, repostería, embutidos.",
         alergenos="Libre de gluten.", precio_venta=Decimal("3.20"), vida_util_dias=730, publicado_tienda=True),
    dict(codigo="PT-ALM-YUC-02", nombre="Almidón de Yuca Fermentado (Agrio)", cat="almidones", linea="ALMIDON",
         unidad_medida="kg", regla_rotacion="FEFO", zona_wms_default="ZONA-ALM-SECOS", estacion_responsable="ALMIDONES",
         imagen_alt="Almidón agrio de yuca granulado seco para panificación sin gluten",
         descripcion_corta="Almidón agrio con poder de expansión para pan de yuca y panificación sin gluten.",
         descripcion_tecnica="Obtenido por sedimentación y fermentación natural en reposo; secado solar o "
                             "mecánico. Alto poder de expansión en horneo.",
         flujo_operativo=["Sedimentación con reposo", "Fermentación natural", "Secado solar/mecánico", "Almacenamiento FEFO"],
         parametros_tecnicos={"humedad_max_pct": 13, "cenizas_max_pct": 0.5},
         presentacion="Saco 25 kg · bolsa 1 kg", contenido_neto=Decimal("25"),
         notas_sensoriales="Aroma ligeramente ácido característico de la fermentación.",
         usos_recomendados="Pan de yuca, pandebono, galletas y masas sin gluten.",
         alergenos="Libre de gluten.", precio_venta=Decimal("3.60"), vida_util_dias=540, publicado_tienda=True),
    dict(codigo="PT-LIC-AGU-01", nombre="Aguardiente Artesanal Andino 40° GL", cat="licores-destilados",
         linea="BEBIDA", unidad_medida="bot", regla_rotacion="FEFO", zona_wms_default="ZONA-LIC-PT",
         estacion_responsable="DESTILACION",
         imagen_alt="Botella de 750 ml con aguardiente cristalino, tapón de madera y etiqueta artesanal UPEC",
         descripcion_corta="Destilado en alambique de cobre, solo el corte de corazón.",
         descripcion_tecnica="Aguardiente obtenido por destilación fraccionada de mostos fermentados. 40 % ABV. "
                             "Separación de cabezas y colas validada en PCC-1 (control de metanol).",
         flujo_operativo=["Fermentación", "Destilación fraccionada (corte de corazón)", "Estabilización", "Envasado serializado"],
         parametros_tecnicos={"requiere_pcc1": True, "tolerancia_abv": 0.5},
         graduacion_abv=Decimal("40"), presentacion="Botella de vidrio 750 ml", contenido_neto=Decimal("0.750"),
         notas_sensoriales="Cristalino. Nariz limpia con notas de caña y fruta blanca; final cálido y seco.",
         usos_recomendados="Solo, en canelazo o como base de coctelería andina.",
         alergenos="Contiene alcohol. Venta exclusiva a mayores de 18 años.",
         precio_venta=Decimal("14.50"), vida_util_dias=3650, publicado_tienda=True, requiere_mayoria_edad=True),
    dict(codigo="PT-LIC-MAC-02", nombre="Licor Macerado de Frutas Andinas 28° GL", cat="licores-destilados",
         linea="BEBIDA", unidad_medida="bot", regla_rotacion="FEFO", zona_wms_default="ZONA-LIC-PT",
         estacion_responsable="DESTILACION",
         imagen_alt="Botella de vidrio con licor color rubí brillante de mora y taxo",
         descripcion_corta="Maceración en frío de mora y taxo sobre destilado base.",
         descripcion_tecnica="Bebida espirituosa a partir del destilado base, maceración en frío de frutos andinos "
                             "y jarabe simple. Filtrado abrillantador. 28 % ABV.",
         flujo_operativo=["Maceración en tanque", "Ajuste de grado", "Filtrado abrillantador", "Envasado", "Trazabilidad por botella"],
         parametros_tecnicos={"requiere_pcc1": True, "tolerancia_abv": 0.5},
         graduacion_abv=Decimal("28"), presentacion="Botella de vidrio 750 ml", contenido_neto=Decimal("0.750"),
         notas_sensoriales="Rubí brillante. Frutos rojos maduros, acidez del taxo, dulzor medio.",
         usos_recomendados="Digestivo frío, sobre helado o en coctelería.",
         alergenos="Contiene alcohol. Venta exclusiva a mayores de 18 años.",
         precio_venta=Decimal("12.00"), vida_util_dias=1095, publicado_tienda=True, requiere_mayoria_edad=True),
    dict(codigo="PT-BEB-CER-03", nombre="Cerveza Artesanal Andina 5.5° GL", cat="bebidas-fermentadas",
         linea="BEBIDA", unidad_medida="bot", regla_rotacion="FEFO", zona_wms_default="ZONA-LIC-PT",
         estacion_responsable="FERMENTACION",
         imagen_alt="Botella ámbar de 330 ml de cerveza artesanal con corona metálica",
         descripcion_corta="Cerveza carbonatada de cereales y tubérculos malteados.",
         descripcion_tecnica="Maceración, cocción con lúpulo, fermentación fría y maduración en cuarentena. 5,5 % ABV.",
         flujo_operativo=["Maceración", "Cocción y lupulado", "Fermentación fría", "Embotellado", "Cuarentena de maduración"],
         parametros_tecnicos={"tolerancia_abv": 0.3}, graduacion_abv=Decimal("5.5"),
         presentacion="Botella ámbar 330 ml", contenido_neto=Decimal("0.330"),
         notas_sensoriales="Ámbar, espuma cremosa, notas de pan tostado y amargor moderado.",
         usos_recomendados="Servir a 6–8 °C. Marida con hornado y quesos andinos.",
         alergenos="Contiene gluten (cebada) y alcohol. Solo mayores de 18 años.",
         precio_venta=Decimal("2.80"), vida_util_dias=180, publicado_tienda=True, requiere_mayoria_edad=True),
]

UBICACIONES = [
    (Zona.REC, 2, 1, 2, 5000, "kg"), (Zona.TANQUES, 1, 1, 3, 3000, "L"), (Zona.DEST, 1, 1, 2, 500, "L"),
    (Zona.SEC, 1, 2, 2, 800, "kg"), (Zona.ALM_SECOS, 3, 3, 4, 1000, "kg"), (Zona.LIC_PT, 2, 4, 3, 240, "bot"),
    (Zona.FRIO, 1, 2, 2, 50, "kg"), (Zona.EMP, 2, 2, 2, 5000, "und"), (Zona.MER, 1, 1, 3, 3000, "kg"),
    (Zona.DESP, 1, 1, 4, 2000, "kg"),
]

EQUIPOS = [
    ("RAL-01", "Ralladora de tubérculos", "RALLADOR", "RECEPCION", Zona.REC, 500, "kg", "", {}),
    ("SED-01", "Sedimentador de lechada", "SEDIMENT", "ALMIDONES", Zona.SEC, 2000, "L", "esp32-sed01", {"PH": [5.5, 7.0]}),
    ("SEC-01", "Túnel de secado", "SECADOR", "ALMIDONES", Zona.SEC, 400, "kg", "esp32-sec01",
     {"TEMP": [45, 50], "HUM": [0, 12]}),
    ("TQ-01", "Tanque fermentador 1", "TANQUE", "FERMENTACION", Zona.TANQUES, 1000, "L", "esp32-tq01",
     {"TEMP": [22, 26], "PH": [3.8, 4.2], "BRIX": [0, 24]}),
    ("TQ-02", "Tanque fermentador 2", "TANQUE", "FERMENTACION", Zona.TANQUES, 1000, "L", "esp32-tq02",
     {"TEMP": [22, 26], "PH": [3.8, 4.2], "BRIX": [0, 24]}),
    ("TQ-03", "Fermentador frío cerveza", "TANQUE", "FERMENTACION", Zona.TANQUES, 500, "L", "esp32-tq03",
     {"TEMP": [10, 14], "PH": [4.0, 4.6], "BRIX": [0, 16]}),
    ("ALB-01", "Alambique fraccionado cobre", "ALAMBIQUE", "DESTILACION", Zona.DEST, 250, "L", "esp32-alb01",
     {"TVAP": [78, 96], "ABV": [0, 85]}),
    ("MAC-01", "Tanque de maceración", "MACERADOR", "DESTILACION", Zona.DEST, 300, "L", "esp32-mac01", {"TEMP": [4, 12]}),
    ("LLE-01", "Llenadora semiautomática", "LLENADORA", "ENVASADO", Zona.LIC_PT, 0, "bot", "", {}),
]

USUARIOS = [
    ("director", "Director", "de Planta", Rol.ADMIN, ""),
    ("op.recepcion", "Ana", "Recepción", Rol.OPERARIO, Estacion.RECEPCION),
    ("op.almidones", "Luis", "Almidones", Rol.OPERARIO, Estacion.ALMIDONES),
    ("op.fermentacion", "María", "Fermentación", Rol.OPERARIO, Estacion.FERMENTACION),
    ("op.destilacion", "Jorge", "Destilación", Rol.OPERARIO, Estacion.DESTILACION),
    ("op.envasado", "Carla", "Envasado", Rol.OPERARIO, Estacion.ENVASADO),
    ("op.almacen", "Pedro", "Almacén", Rol.OPERARIO, Estacion.ALMACEN),
    ("cliente.demo", "Cliente", "Demo", Rol.CLIENTE, ""),
]


class Command(BaseCommand):
    help = "Carga catálogo, WMS, equipos y usuarios de BAKELY (y operación demo con --demo)."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true")
        parser.add_argument("--password", default="Bakely2026!")

    @transaction.atomic
    def handle(self, *args, **opts):
        cats = {}
        for i, (slug, nombre, tipo, linea, icono) in enumerate(CATEGORIAS):
            cats[slug], _ = Categoria.objects.update_or_create(
                slug=slug, defaults=dict(nombre=nombre, tipo=tipo, linea=linea, icono=icono, orden=i))
        for p in PRODUCTOS:
            p = dict(p)
            cat = cats[p.pop("cat")]
            Producto.objects.update_or_create(codigo=p["codigo"], defaults={**p, "categoria": cat})
        self.stdout.write(self.style.SUCCESS(f"Catálogo: {Producto.objects.count()} ítems"))

        for zona, racks, niveles, posiciones, cap, uni in UBICACIONES:
            for r in range(1, racks + 1):
                for n in range(1, niveles + 1):
                    for pos in range(1, posiciones + 1):
                        UbicacionWMS.objects.get_or_create(
                            zona=zona, rack=f"R{r:02}", nivel=f"N{n}", posicion=f"P{pos:02}",
                            defaults=dict(capacidad=cap, unidad_capacidad=uni,
                                          temperatura_controlada=zona == Zona.FRIO,
                                          descripcion=dict(Zona.choices)[zona]))
        self.stdout.write(self.style.SUCCESS(f"WMS: {UbicacionWMS.objects.count()} ubicaciones"))

        for cod, nom, tipo, est, zona, cap, uni, dev, lim in EQUIPOS:
            Equipo.objects.update_or_create(codigo=cod, defaults=dict(
                nombre=nom, tipo=tipo, estacion=est, capacidad=cap, unidad_capacidad=uni, dispositivo_iot=dev,
                limites=lim, ubicacion=UbicacionWMS.objects.filter(zona=zona).first()))

        for username, nombre, apellido, rol, est in USUARIOS:
            u, creado = User.objects.get_or_create(username=username, defaults=dict(
                first_name=nombre, last_name=apellido, email=f"{username}@upec.edu.ec",
                is_staff=rol == Rol.ADMIN, is_superuser=rol == Rol.ADMIN))
            if creado:
                u.set_password(opts["password"])
                u.save()
            PerfilUsuario.objects.update_or_create(usuario=u, defaults=dict(rol=rol, estacion=est))
        self.stdout.write(self.style.SUCCESS(f"Usuarios listos (clave inicial: {opts['password']})"))

        if opts["demo"]:
            self._demo()

    # ------------------------------------------------------------------ operación demo
    def _demo(self):
        if OrdenProduccion.objects.exists():
            self.stdout.write("Ya existe operación demo; se omite.")
            return
        random.seed(7)
        admin = User.objects.get(username="director")
        ops = {e: User.objects.get(perfil__estacion=e) for e in Estacion.values}
        P = {p.codigo: p for p in Producto.objects.all()}
        U = lambda z: UbicacionWMS.objects.filter(zona=z).order_by("id")
        hoy = timezone.localdate()
        ahora = timezone.now()
        mv = services.registrar_movimiento

        # --- Recepción de materias primas
        mp_papa = Lote.objects.create(codigo="MP-TUB-2610-01", producto=P["MP-TUB-001"], tipo="MP",
                                      cantidad_inicial=2000, unidad="kg", proveedor="Asoc. Productores San Gabriel",
                                      origen_geografico="San Gabriel, Montúfar", fecha_elaboracion=hoy - timedelta(days=9),
                                      estacion_responsable="RECEPCION", creado_por=ops["RECEPCION"], estado="LIBERADO")
        mv(user=ops["RECEPCION"], tipo="ENTRADA", lote=mp_papa, cantidad=2000, ubicacion_destino=U(Zona.REC)[0])
        mp_lev = Lote.objects.create(codigo="MP-LEV-2609-01", producto=P["MP-LEV-002"], tipo="MP", cantidad_inicial=5,
                                     unidad="kg", proveedor="Distribuidora enológica", estado="LIBERADO",
                                     fecha_caducidad=hoy + timedelta(days=400), estacion_responsable="RECEPCION",
                                     creado_por=ops["RECEPCION"])
        mv(user=admin, tipo="ENTRADA", lote=mp_lev, cantidad=5, ubicacion_destino=U(Zona.FRIO)[0])
        bot = Lote.objects.create(codigo="EMP-BOT-2609-01", producto=P["EMP-BOT-003"], tipo="MP", cantidad_inicial=1200,
                                  unidad="und", proveedor="Vidriería", estado="LIBERADO", creado_por=admin)
        mv(user=admin, tipo="ENTRADA", lote=bot, cantidad=1200, ubicacion_destino=U(Zona.EMP)[0])

        # --- Línea A: almidón de papa
        oa = OrdenProduccion.objects.create(codigo="OP-A-2610-001", linea="ALMIDON", producto=P["PT-ALM-PAP-01"],
                                            cantidad_planificada=300, unidad="kg", estado="CERRADA", etapa_actual="ALMACEN",
                                            equipo=Equipo.objects.get(codigo="SEC-01"), creada_por=admin,
                                            fecha_inicio=ahora - timedelta(days=7), fecha_cierre=ahora - timedelta(days=5))
        mv(user=ops["RECEPCION"], tipo="CONSUMO", lote=mp_papa, cantidad=1500, ubicacion_origen=U(Zona.REC)[0], orden=oa)
        pt_alm = Lote.objects.create(codigo="PT-ALM-PAP-2610-01", producto=P["PT-ALM-PAP-01"], orden=oa, tipo="PT",
                                     cantidad_inicial=250, unidad="kg", fecha_elaboracion=hoy - timedelta(days=5),
                                     fecha_caducidad=hoy + timedelta(days=725), humedad_final_pct=Decimal("11.4"),
                                     cenizas_pct=Decimal("0.32"), certificado_inocuidad="UPEC-LAB-2610-118",
                                     estacion_responsable="ALMIDONES", creado_por=ops["ALMIDONES"])
        pt_alm.lotes_origen.add(mp_papa)
        for et, ctrl, est, vars_, t in [
            ("Recepción e inspección", "PC-1", "RECEPCION", {"humedad_pct": 78.5, "impurezas_pct": 1.8, "materia_seca_pct": 21.5}, 7),
            ("Rallado y extracción", "GEN", "RECEPCION", {"agua_l": 3000}, 7),
            ("Secado controlado", "PC-2", "ALMIDONES", {"temp_secado_c": 47.5, "humedad_final_pct": 11.4}, 6),
        ]:
            RegistroEtapa.objects.create(orden=oa, lote=pt_alm, estacion=est, etapa=et, control=ctrl, variables=vars_,
                                         registrado_por=ops[est], firmado=True, fecha=ahora - timedelta(days=t),
                                         aprobado_por=admin, fecha_aprobacion=ahora - timedelta(days=t - 1))
        mv(user=ops["ALMIDONES"], tipo="PRODUCCION", lote=pt_alm, cantidad=250, ubicacion_destino=U(Zona.ALM_SECOS)[0], orden=oa)
        merma = Lote.objects.create(codigo="MER-PULPA-2610-01", producto=P["MP-TUB-001"], orden=oa, tipo="INT",
                                    cantidad_inicial=1180, unidad="kg", estado="RECHAZADO", creado_por=admin)
        mv(user=admin, tipo="ENTRADA", lote=merma, cantidad=1180, ubicacion_destino=U(Zona.MER)[0], orden=oa)
        mv(user=admin, tipo="MERMA", lote=merma, cantidad=1180, ubicacion_origen=U(Zona.MER)[0], orden=oa,
           motivo_merma="PULPA")
        services.liberar_lote(admin, pt_alm)

        # --- Línea B: aguardiente
        alb = Equipo.objects.get(codigo="ALB-01")
        tq = Equipo.objects.get(codigo="TQ-01")
        ob = OrdenProduccion.objects.create(codigo="OP-B-2610-001", linea="BEBIDA", producto=P["PT-LIC-AGU-01"],
                                            cantidad_planificada=60, unidad="bot", estado="PROC", etapa_actual="DESTILACION",
                                            equipo=tq, creada_por=admin, fecha_inicio=ahora - timedelta(days=4))
        pt_agu = Lote.objects.create(codigo="PT-AGU-2610-01", producto=P["PT-LIC-AGU-01"], orden=ob, tipo="PT",
                                     cantidad_inicial=48, unidad="bot", fecha_elaboracion=hoy - timedelta(days=1),
                                     fecha_caducidad=hoy + timedelta(days=3650), abv_final=Decimal("40.1"),
                                     certificado_inocuidad="UPEC-LAB-2610-121", estacion_responsable="ENVASADO",
                                     creado_por=ops["ENVASADO"])
        pt_agu.lotes_origen.add(mp_lev)
        RegistroEtapa.objects.create(orden=ob, lote=pt_agu, estacion="FERMENTACION", etapa="Inoculación del mosto",
                                     control="PC-3", equipo=tq, variables={"brix_inicial": 19.2, "ph": 3.95, "temp_c": 24.1},
                                     registrado_por=ops["FERMENTACION"], firmado=True, fecha=ahora - timedelta(days=4))
        reg = RegistroEtapa.objects.create(orden=ob, lote=pt_agu, estacion="DESTILACION", etapa="Destilación fraccionada",
                                           control="PCC-1", equipo=alb, registrado_por=ops["DESTILACION"], firmado=True,
                                           fecha=ahora - timedelta(days=1))
        CorteDestilacion.objects.create(
            registro=reg, alambique=alb, volumen_carga_l=200, abv_carga=Decimal("9.5"), cabezas_l=Decimal("1.6"),
            abv_cabezas=Decimal("78"), corazon_l=Decimal("21.5"), abv_corazon=Decimal("68.5"), colas_l=Decimal("9"),
            abv_colas=Decimal("25"), temp_vapor_corte_cabeza_c=Decimal("80.5"), temp_vapor_corte_cola_c=Decimal("94"),
            metanol_mg_100ml_aa=Decimal("38"),
            curva_termica=[[m, round(78 + m * 0.18, 1), round(80 - m * 0.55, 1)] for m in range(0, 100, 5)])
        mv(user=ops["ENVASADO"], tipo="PRODUCCION", lote=pt_agu, cantidad=48, ubicacion_destino=U(Zona.LIC_PT)[0], orden=ob)
        for i in range(1, 49):
            UnidadSerializada.objects.create(lote=pt_agu, serial=f"AGU-2610-{i:05}", sello_fiscal=f"SF-{uuid.uuid4().hex[:8].upper()}",
                                             ubicacion=U(Zona.LIC_PT)[0], envasado_por=ops["ENVASADO"])
        services.liberar_lote(admin, Lote.objects.get(pk=pt_agu.pk))

        # --- Cerveza en cuarentena de maduración
        oc = OrdenProduccion.objects.create(codigo="OP-B-2610-002", linea="BEBIDA", producto=P["PT-BEB-CER-03"],
                                            cantidad_planificada=400, unidad="bot", estado="PROC", etapa_actual="FERMENTACION",
                                            equipo=Equipo.objects.get(codigo="TQ-03"), creada_por=admin,
                                            fecha_inicio=ahora - timedelta(days=2))

        # --- Estados de equipos y lecturas IoT (últimas 12 h)
        Equipo.objects.filter(codigo__in=["TQ-01", "TQ-03", "ALB-01", "SEC-01"]).update(estado="OPERANDO")
        Equipo.objects.filter(codigo="TQ-01").update(nivel_actual=820)
        Equipo.objects.filter(codigo="TQ-03").update(nivel_actual=430)
        Equipo.objects.filter(codigo="ALB-01").update(nivel_actual=180)
        perfiles = {"TQ-01": (ob, {"TEMP": (24, .8), "PH": (4.0, .08), "BRIX": (9, 3)}),
                    "TQ-03": (oc, {"TEMP": (12, .7), "PH": (4.3, .1), "BRIX": (8, 2)}),
                    "ALB-01": (ob, {"TVAP": (88, 5), "ABV": (62, 10)}),
                    "SEC-01": (None, {"TEMP": (47.5, 1.2), "HUM": (14, 3)})}
        lecturas = []
        for cod, (orden, vars_) in perfiles.items():
            eq = Equipo.objects.get(codigo=cod)
            for k in range(72):
                ts = ahora - timedelta(minutes=10 * (72 - k))
                for var, (media, sd) in vars_.items():
                    if var == "BRIX":
                        val = max(1.0, media + 10 - k * 0.14 + random.gauss(0, .2))
                    elif var == "HUM":
                        val = max(9.0, media - k * 0.04 + random.gauss(0, .2))
                    else:
                        val = random.gauss(media, sd / 2)
                    lecturas.append(LecturaIoT(equipo=eq, orden=orden, variable=var, valor=round(Decimal(val), 3),
                                               dispositivo=eq.dispositivo_iot, timestamp=ts,
                                               fuera_de_rango=eq.fuera_de_rango(var, round(val, 3))))
        LecturaIoT.objects.bulk_create(lecturas)
        # Una alerta reciente para ver el borde iluminado en rojo
        services.procesar_lectura_iot(dispositivo="esp32-tq03", variable="TEMP", valor=15.2)

        # --- Conteos cíclicos (IRA)
        for ex in Existencia.objects.filter(cantidad__gt=0)[:6]:
            ConteoCiclico.objects.create(ubicacion=ex.ubicacion, lote=ex.lote, cantidad_sistema=ex.cantidad,
                                         cantidad_fisica=ex.cantidad - (random.choice([0, 0, 0, 1]) * ex.cantidad / 20),
                                         usuario=ops["ALMACEN"])

        # --- Despacho al CEDI en preparación
        d = Despacho.objects.create(codigo="DSP-2610-0001", cedi_destino="CEDI-CARCHI-01",
                                    fecha_programada=ahora + timedelta(days=1), transportista="Transportes del Norte",
                                    placa_vehiculo="CAA-1234", conductor="José Pozo", guia_remision="001-001-000245",
                                    creado_por=ops["ALMACEN"])
        DetalleDespacho.objects.create(despacho=d, lote=pt_alm, ubicacion_origen=U(Zona.ALM_SECOS)[0], cantidad=200,
                                       unidades_empaque=8, codigo_palet="PAL-2610-01")
        DetalleDespacho.objects.create(despacho=d, lote=pt_agu, ubicacion_origen=U(Zona.LIC_PT)[0], cantidad=24,
                                       unidades_empaque=24, codigo_palet="CJ-2610-04")
        self.stdout.write(self.style.SUCCESS("Operación demo creada (2 líneas, eBR, PCC-1, IoT, Kardex, despacho)."))
