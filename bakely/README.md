# BAKELY · WMS / MES de la Planta de Almidones y Licores UPEC

Plataforma Django que digitaliza la planta piloto de la Universidad Politécnica Estatal del Carchi:
**Línea A** (almidón de papa y yuca) y **Línea B** (fermentación, destilación y licores), conectada al CEDI y a Odoo.

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # ajuste credenciales MySQL y claves
```

Cree la base en MySQL (o desde DBeaver):

```sql
CREATE DATABASE bakely_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'bakely'@'localhost' IDENTIFIED BY 'cambia-esta-clave';
GRANT ALL PRIVILEGES ON bakely_db.* TO 'bakely'@'localhost';
```

```bash
python manage.py migrate
python manage.py seed_bakely --demo          # catálogo, 92 ubicaciones, 9 equipos, usuarios y operación de ejemplo
python manage.py runserver
```

Prueba rápida sin MySQL: `DB_ENGINE=sqlite python manage.py migrate` (y los demás comandos con la misma variable).

### Usuarios de ejemplo (clave inicial `Bakely2026!` — cámbiela)

| Usuario | Rol | Edita |
|---|---|---|
| `director` | Administrador General | Todo, libera lotes, usuarios, bitácora |
| `op.recepcion` | Operario | Recepción, lavado y molienda |
| `op.almidones` | Operario | Extracción y secado (PC-2) |
| `op.fermentacion` | Operario | Tanques e inoculación (PC-3) |
| `op.destilacion` | Operario | Cortes de destilación (PCC-1) |
| `op.envasado` | Operario | Envasado, sellos y QR |
| `op.almacen` | Operario | WMS, picking y despacho al CEDI |
| `cliente.demo` | Cliente | Solo tienda y trazabilidad |

## Mapa del código

| Archivo | Qué contiene |
|---|---|
| `core/models.py` | Categoría, Producto (`ImageField`, flujo, parámetros), UbicacionWMS, Equipo (tanque/alambique), OrdenProduccion, Lote (genealogía, QR), UnidadSerializada, RegistroEtapa (eBR), CorteDestilacion (PCC-1), LecturaIoT, Existencia, MovimientoKardex, ConteoCiclico (IRA), Despacho, Pedido, RegistroAuditoria |
| `core/permissions.py` | Regla RBAC única en 3 formas: funciones, decoradores/mixins HTML y permisos DRF |
| `core/services.py` | Kardex transaccional (`SELECT … FOR UPDATE`), picking FEFO/FIFO, liberación de lotes, contrato CEDI, IoT, auditoría con detección de sobrescritura administrativa |
| `core/views.py` | Vistas HTML de los módulos 0–6 |
| `core/api_views.py` · `core/serializers.py` | ViewSets REST, endpoint IoT y contrato `despacho_planta_hacia_cedi` |
| `core/exports.py` · `core/reportes_render.py` | eBR PDF con membrete UPEC y QR, bitácora Excel/CSV, Kardex Excel/PDF, manifiesto PDF/JSON |
| `core/odoo.py` | Conector XML-RPC: productos, fabricación, compras y ventas |
| `core/management/commands/` | `seed_bakely`, `simular_iot`, `mqtt_bridge` |
| `templates/` | Landing, tienda con pestañas, visor QR, tablero con diales y candados, WMS, eBR, despachos, informes, usuarios |
| `iot/` | Firmware ESP32 de ejemplo y flujo Node-RED |

## Regla de permisos

- **Operarios ven todo** el terminal, pero **solo editan su estación**. En las demás, los formularios aparecen deshabilitados con un candado que dice qué estación los registra.
- El bloqueo no es solo visual: cada POST/PUT pasa por `puede_editar_estacion()` y cada intento denegado queda en la bitácora.
- **Administrador**: edita todo. Si modifica un dato registrado por otro usuario, la bitácora lo marca como *sobrescritura administrativa* (resaltado en el Excel).
- **Cliente**: tienda, carrito y visor QR. El terminal le responde 403.
- Los registros eBR y el Kardex son de solo inserción; las correcciones se registran como nuevas entradas.

## API

```
POST /api/token/                                  usuario+clave → token
GET  /api/catalogo/?linea=BEBIDA                  público
GET  /api/trazabilidad/<uuid-qr>/                 público
GET  /api/planta/{productos,ubicaciones,existencias,kardex,equipos,ordenes,lotes,ebr,unidades}/
GET  /api/planta/equipos/TQ-01/serie/?variable=TEMP&horas=12
POST /api/planta/lotes/<codigo>/liberar/          solo administrador
POST /api/iot/lecturas/                           cabecera X-Device-Key
GET  /api/cedi/despachos/<id>/contrato/           JSON despacho_planta_hacia_cedi
POST /api/cedi/despachos/<id>/confirmar/          descarga Kardex y envía al CEDI
POST /api/cedi/confirmacion/                      webhook del CEDI (Bearer CEDI_API_TOKEN)
```

Lectura IoT (individual o lista de hasta 500):

```json
[{"dispositivo": "esp32-tq01", "variable": "temperatura", "valor": 24.3, "ts": "2026-10-13T10:00:00-05:00"}]
```

Variables aceptadas: temperatura, ph, brix, densidad, abv, temp_vapor, humedad, nivel, presion.
Una lectura fuera de los límites del equipo pone el equipo en **ALERTA** (borde rojo pulsante en el tablero) y vuelve a OPERANDO cuando todas sus variables regresan al rango.

## IoT sin hardware

```bash
python manage.py simular_iot --intervalo 5 --ciclos 0       # lecturas continuas
python manage.py simular_iot --alerta TQ-01:TEMP:29          # forzar una alerta
python manage.py mqtt_bridge --host 192.168.1.50             # con ESP32 reales vía Mosquitto
```

## Pruebas

```bash
python manage.py test core      # 19 pruebas: RBAC, PC/PCC, Kardex, FEFO, IoT, CEDI y exportaciones
```

## Pendientes antes de producción

- **Fotografías reales**: el catálogo trae el texto de cada foto requerida (`imagen_alt`); súbalas desde *Maestros → Productos*. Mientras tanto se muestra un marcador con esa descripción.
- **Sello UPEC**: `static/img/sello-upec.svg` es un marcador genérico; reemplácelo por el sello institucional oficial.
- **Límites PCC-1**: el límite de metanol (`CorteDestilacion.LIMITE_METANOL_MG_100ML_AA`) y los rangos de ABV son parametrizables; valídelos contra la norma INEN vigente y el registro sanitario ARCSA.
- `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` propio, HTTPS y `python manage.py collectstatic` al desplegar.
- Las librerías de interfaz (Bootstrap grid, Lucide, Chart.js, fuente Barlow) se cargan por CDN. Si el terminal de planta no tiene internet, cópielas a `static/vendor/`.
