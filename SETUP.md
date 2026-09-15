# Instalar el sistema en una computadora nueva

Guía paso a paso para levantar Platinium Spa & Peluquería (Odoo 19 + módulo
`beauty_appointment`) desde cero en otra máquina.

## 0. Qué necesitas tener a mano antes de empezar

- **Un respaldo de la base de datos** (zip con `dump.sql` + carpeta `filestore/`
  + `manifest.json`). El código (este repo) y los datos (la base) viven
  separados — clonar el repo NO trae tus citas, clientes ni el logo.
- **El archivo de credenciales del túnel de Cloudflare**
  (`~/.cloudflared/20754198-e745-4374-ac0e-036f65079736.json`), solo si vas a
  reactivar el link público `citas.platinum-spaypeluqueria.co.uk`. Este
  archivo es secreto y a propósito NO está en git — tienes que copiarlo tú
  desde la máquina vieja (USB, AirDrop, etc.), o pedirlo a quien lo tenga.

## 1. Requisitos previos en la computadora nueva

1. **Docker Desktop** (incluye Docker Compose) — <https://www.docker.com/products/docker-desktop/>.
   Instálalo, ábrelo una vez y déjalo corriendo en segundo plano.
2. **Git**.
3. **cloudflared** (opcional, solo para el link público de citas):
   - Mac: `brew install cloudflared`
   - Windows: `winget install --id Cloudflare.cloudflared`
   - Linux: paquete `.deb`/`.rpm` desde la documentación oficial de Cloudflare.

## 2. Clonar el repositorio

```bash
git clone https://github.com/Heas06/git-init.git
cd git-init
```

Esto trae el código del módulo (`extra-addons/beauty_appointment`), la
configuración de Odoo (`config/odoo.conf`) y la configuración del túnel
(`cloudflared/config.yml`) — todo lo que hicimos hoy ya queda incluido.

## 3. Levantar los contenedores (todavía sin datos reales)

```bash
docker compose up -d
```

Crea 2 contenedores (`mi-crm-odoo-db-1` = Postgres, `mi-crm-odoo-web-1` =
Odoo) con volúmenes nuevos y **vacíos**. Como `config/odoo.conf` ya trae
`dbfilter = ^Platinium$`, si en este punto abres `http://localhost:8069` vas
a ver un error de "base de datos no encontrada" — es normal, todavía no
restauramos nada. No sigas por el asistente de "crear base de datos nueva".

## 4. Restaurar la base de datos real

Descomprime tu zip de respaldo en algún lado, por ejemplo `~/Desktop/restore/`.
Debe quedar con `dump.sql`, la carpeta `filestore/` y `manifest.json` sueltos
(no una subcarpeta extra).

**4.1. Crear la base vacía:**

```bash
docker compose exec db psql -U odoo -d postgres -c 'CREATE DATABASE "Platinium" OWNER odoo ENCODING '\''UTF8'\'' TEMPLATE template0;'
```

**4.2. Restaurar el SQL:**

```bash
docker compose exec -T db psql -U odoo -d "Platinium" -v ON_ERROR_STOP=1 < ~/Desktop/restore/dump.sql
```

> Si el backup fue generado en OTRA máquina con una versión más nueva de
> `pg_dump` (17/18), este paso puede fallar por comandos `\restrict` /
> `\unrestrict` o por `SET transaction_timeout` (funciones de Postgres 17+
> que este Postgres 15 no reconoce). Si pasa, límpialas antes de restaurar:
> ```bash
> grep -vE '^\\(restrict|unrestrict)' dump.sql | grep -v 'SET transaction_timeout' > dump_clean.sql
> ```
> y usa `dump_clean.sql` en el comando de arriba. Un respaldo generado
> directamente con `docker compose exec db pg_dump ...` (como el que te dejé
> en el Desktop) no tiene este problema.

**4.3. Copiar el filestore (adjuntos, logo, imágenes) dentro del contenedor:**

```bash
docker cp ~/Desktop/restore/filestore/. mi-crm-odoo-web-1:/var/lib/odoo/filestore/Platinium
docker compose exec -u root web chown -R odoo:odoo /var/lib/odoo/filestore/Platinium
```

**4.4. Reiniciar Odoo:**

```bash
docker compose restart web
```

## 5. Verificar que todo cargó bien

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8069/
```

Debe responder `200` o `303` (redirección normal al login) — nunca `500`.
Abre `http://localhost:8069` en el navegador y entra con tu usuario admin.

## 6. (Opcional) Reactivar el link público de citas

El túnel con nombre `citas-platinum-spa` y el DNS de
`citas.platinum-spaypeluqueria.co.uk` **ya existen** en tu cuenta de
Cloudflare — no hay que recrearlos, solo volver a correr el túnel desde la
máquina nueva.

**6.1. Iniciar sesión en Cloudflare** (una sola vez por máquina):

```bash
cloudflared tunnel login
```

Se abre el navegador — inicia sesión y elige el dominio
`platinum-spaypeluqueria.co.uk`.

**6.2. Poner el archivo de credenciales del túnel** en
`~/.cloudflared/20754198-e745-4374-ac0e-036f65079736.json` (cópialo desde la
máquina vieja — ver sección 0). Sin este archivo específico, `cloudflared
tunnel login` solo te da un certificado de cuenta, no las llaves de este
túnel puntual.

**6.3. Correr el túnel** (desde la carpeta `git-init`):

```bash
cloudflared tunnel --config cloudflared/config.yml run citas-platinum-spa
```

Déjalo corriendo en una terminal (o instálalo como servicio del sistema con
`cloudflared service install` si lo quieres permanente, sin depender de una
terminal abierta).

**6.4. Probar:** <https://citas.platinum-spaypeluqueria.co.uk/salon/citas>

## Notas

- **No repitas** la restauración de la base de datos si ya la hiciste una
  vez en esa máquina — `docker compose down` / `up` normales conservan los
  volúmenes (`odoo-db-data`, `odoo-web-data`); solo hace falta restaurar tras
  un `docker compose down -v` (que sí borra los volúmenes) o en una máquina
  nueva de verdad.
- El gestor de bases de datos web (`/web/database/manager`) está
  deliberadamente **deshabilitado** (`list_db = False` en `odoo.conf`) por
  seguridad, ya que el sitio está expuesto a internet vía Cloudflare Tunnel.
  Todo respaldo/restauración futuro se hace por línea de comandos como en el
  paso 4.
- Las credenciales del túnel de Cloudflare y cualquier respaldo de base de
  datos (contiene datos reales de clientes) **no se suben a git** a
  propósito — transpórtalos por fuera (USB, Drive, AirDrop).
