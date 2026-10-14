"""
BAKELY · Conector Odoo (XML-RPC externo, sin dependencias)

Cubre los cuatro módulos pedidos: Compras, Inventario, Fabricación y Ventas.
Configure ODOO_URL, ODOO_DB, ODOO_USER y ODOO_PASSWORD (clave API) en .env.

Uso:
    from core.odoo import OdooCliente
    oc = OdooCliente()
    oc.sincronizar_producto(producto)          # crea/actualiza product.product
    oc.crear_orden_fabricacion(orden)          # mrp.production
    oc.registrar_pedido_venta(pedido)          # sale.order
"""
import xmlrpc.client

from django.conf import settings


class OdooError(Exception):
    pass


class OdooCliente:
    def __init__(self):
        c = settings.BAKELY
        if not c.get("ODOO_URL"):
            raise OdooError("ODOO_URL no configurado.")
        self.url, self.db, self.user, self.pwd = c["ODOO_URL"], c["ODOO_DB"], c["ODOO_USER"], c["ODOO_PASSWORD"]
        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(self.db, self.user, self.pwd, {})
        if not self.uid:
            raise OdooError("Autenticación con Odoo fallida.")
        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    def call(self, modelo, metodo, *args, **kw):
        return self.models.execute_kw(self.db, self.uid, self.pwd, modelo, metodo, list(args), kw)

    # ------------------------------------------------------------ Inventario
    def sincronizar_producto(self, p):
        vals = {"name": p.nombre, "default_code": p.codigo, "list_price": float(p.precio_venta),
                "description_sale": p.descripcion_corta, "sale_ok": p.publicado_tienda, "type": "product"}
        if p.odoo_product_id:
            self.call("product.product", "write", [p.odoo_product_id], vals)
            return p.odoo_product_id
        existentes = self.call("product.product", "search", [["default_code", "=", p.codigo]], limit=1)
        pid = existentes[0] if existentes else self.call("product.product", "create", vals)
        type(p).objects.filter(pk=p.pk).update(odoo_product_id=pid)
        return pid

    def stock_odoo(self, p):
        pid = p.odoo_product_id or self.sincronizar_producto(p)
        r = self.call("product.product", "read", [pid], fields=["qty_available"])
        return r[0]["qty_available"] if r else 0

    # ------------------------------------------------------------ Fabricación
    def crear_orden_fabricacion(self, orden):
        pid = orden.producto.odoo_product_id or self.sincronizar_producto(orden.producto)
        mo = self.call("mrp.production", "create", {
            "product_id": pid, "product_qty": float(orden.cantidad_planificada), "origin": orden.codigo,
        })
        type(orden).objects.filter(pk=orden.pk).update(odoo_mrp_id=mo)
        return mo

    # ------------------------------------------------------------ Compras
    def crear_solicitud_compra(self, producto, cantidad, proveedor_id):
        pid = producto.odoo_product_id or self.sincronizar_producto(producto)
        return self.call("purchase.order", "create", {
            "partner_id": proveedor_id,
            "order_line": [(0, 0, {"product_id": pid, "product_qty": float(cantidad)})],
        })

    # ------------------------------------------------------------ Ventas
    def registrar_pedido_venta(self, pedido):
        partner = self.call("res.partner", "search", [["email", "=", pedido.email]], limit=1)
        partner_id = partner[0] if partner else self.call("res.partner", "create",
                                                          {"name": pedido.nombre, "email": pedido.email,
                                                           "phone": pedido.telefono})
        lineas = [(0, 0, {"product_id": d.producto.odoo_product_id or self.sincronizar_producto(d.producto),
                          "product_uom_qty": d.cantidad, "price_unit": float(d.precio_unitario)})
                  for d in pedido.detalles.select_related("producto")]
        return self.call("sale.order", "create", {"partner_id": partner_id, "client_order_ref": pedido.codigo,
                                                  "order_line": lineas})
