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

Este proyecto vive en **Windows 11** en producción; la Mac solo se usa para
desarrollo/pruebas. Los comandos de `docker compose` son idénticos en ambos
sistemas — lo único que cambia es cómo arranca Docker Desktop y cómo se
instala el servicio de `cloudflared`, marcado abajo en cada caso.

1. **Docker Desktop** — <https://www.docker.com/products/docker-desktop/>.
   - **Windows 11:** Docker Desktop necesita **WSL2**. Si el instalador no lo
     habilita solo, abre PowerShell **como administrador** y corre
     `wsl --install`, reinicia, y luego instala Docker Desktop normal. Durante
     la instalación, deja marcada la opción "Use WSL 2 instead of Hyper-V".
   - **Mac:** instálalo normal, sin pasos extra.
   - En ambos: ábrelo una vez, y en **Settings → General** activa **"Start
     Docker Desktop when you sign in"** (o equivalente) — sin esto, aunque
     los contenedores tengan reinicio automático, no hay Docker corriendo
     para reiniciarlos. Ver sección 3.5 para el detalle completo.
2. **Git** — en Windows, instala [Git for Windows](https://git-scm.com/download/win)
   (trae Git Bash, que entiende los mismos comandos de este documento; en
   `cmd`/PowerShell puro algunos comandos con comillas simples de Linux no
   funcionan igual).
3. **cloudflared** (opcional, solo para el link público de citas):
   - Windows: `winget install --id Cloudflare.cloudflared` (PowerShell como
     administrador).
   - Mac: `brew install cloudflared`
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

### 3.5. Que los contenedores arranquen solos al prender la computadora

`docker-compose.yml` ya trae `restart: unless-stopped` en ambos servicios
(viene incluido al clonar, no hay que tocar nada) — eso le dice a Docker
"si el motor de Docker se reinicia, vuelve a levantar estos contenedores",
y sobrevive un `docker compose up -d` o un reinicio del sistema. Pero eso
**no alcanza por sí solo**: si Docker Desktop no está corriendo, no hay quién
reinicie nada. Hacen falta las dos cosas juntas:

1. **`restart: unless-stopped`** en el compose (✅ ya está, ver paso 1).
2. **Docker Desktop arrancando solo** al prender la computadora:
   - **Windows 11:** Docker Desktop → ícono de engranaje (Settings) →
     **General** → marca **"Start Docker Desktop when you log in"**.
     Adicionalmente, en **Settings → General**, verifica que **"Open
     Docker Dashboard when Docker Desktop starts"** no te moleste si
     prefieres que arranque silencioso en segundo plano.
   - **Mac:** Docker Desktop → ícono de ballena → **Settings** →
     **General** → marca **"Start Docker Desktop when you sign in to your
     computer"**.

Con las dos cosas activas: prendes la computadora → inicias sesión → Docker
Desktop arranca solo → los contenedores (que quedaron con
`restart: unless-stopped` desde la última vez que corriste `docker compose
up -d`) se levantan solos, sin que nadie abra una terminal.

> Si alguna vez corres `docker compose down` (no solo `stop`), eso **borra**
> los contenedores — al volver a prenderlos vas a necesitar `docker compose
> up -d` una vez más para recrearlos (los datos en los volúmenes no se
> pierden, solo hay que recrear los contenedores). Para pausar sin perder el
> auto-arranque, usa `docker compose stop` en vez de `down`.

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

> ⚠️ **En Windows con Git Bash:** Git Bash traduce automáticamente
> cualquier argumento que empiece con `/` a una ruta de Windows dentro de
> la carpeta de instalación de Git (ej. `/var/lib/...` se convierte en
> `C:/Program Files/Git/var/lib/...`), lo que rompe rutas que en realidad
> viven DENTRO del contenedor Linux. El `docker cp` de arriba no se ve
> afectado (el `container:` antes de la ruta lo protege), pero el `chown`
> sí. Si ves un error tipo `chown: cannot access 'C:/Program
> Files/Git/var/lib/...'`, usa doble slash al inicio para que Git Bash no
> la toque:
> ```bash
> docker compose exec -u root web chown -R odoo:odoo //var/lib/odoo/filestore/Platinium
> ```
> (Si usas PowerShell o cmd.exe en vez de Git Bash, este problema no
> existe y el comando original funciona tal cual.)

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

**6.3. Instalarlo como servicio permanente** (recomendado — si solo lo corres
a mano en una terminal, se muere apenas apagues la computadora o cierres esa
terminal, y el link público dejará de funcionar hasta que lo vuelvas a
lanzar).

#### En Windows 11 (PowerShell **como administrador**)

```powershell
cloudflared service install --config C:\ruta\a\git-init\cloudflared\config.yml
```

Esto registra `cloudflared` como **Servicio de Windows** (arranca con el
sistema, no depende de que nadie inicie sesión). Verifica que quedó
corriendo:

```powershell
Get-Service cloudflared
```

Debe decir `Status: Running`. Si no, revisa el Visor de Eventos de Windows
(Event Viewer → Windows Logs → Application, busca "cloudflared") o corre
`cloudflared tunnel --config C:\ruta\a\git-init\cloudflared\config.yml run
citas-platinum-spa` a mano para ver el error directamente en pantalla.

#### En Mac

```bash
ln -sf "$(pwd)/cloudflared/config.yml" ~/.cloudflared/config.yml
cloudflared service install
```

⚠️ **Bug conocido de `cloudflared service install`** (visto en macOS,
versión 2026.9.0): genera el servicio SIN el subcomando `tunnel run` ni
`--config`, así que arranca y se cae al instante. Verifica y corrige si
hace falta:

```bash
pgrep -fl cloudflared   # si no aparece nada corriendo, hay que arreglar el plist
```

Edita `~/Library/LaunchAgents/com.cloudflare.cloudflared.plist` y asegúrate
de que `ProgramArguments` sea exactamente esto (reemplaza la ruta del
binario por la que te dé `which cloudflared` si no usas Homebrew en Apple
Silicon):

```xml
<key>ProgramArguments</key>
<array>
    <string>/opt/homebrew/bin/cloudflared</string>
    <string>tunnel</string>
    <string>--config</string>
    <string>/Users/TU_USUARIO/.cloudflared/config.yml</string>
    <string>run</string>
    <string>citas-platinum-spa</string>
</array>
```

Luego recarga el servicio:

```bash
launchctl unload ~/Library/LaunchAgents/com.cloudflare.cloudflared.plist
launchctl load ~/Library/LaunchAgents/com.cloudflare.cloudflared.plist
pgrep -fl cloudflared   # ahora si deberia aparecer corriendo
```

Con esto, el túnel arranca solo cada vez que prendes la computadora — no
depende de dejar una terminal abierta.

**Alternativa rápida (no permanente, cualquier SO):** para probar algo
puntual sin instalar el servicio, corre en primer plano desde la carpeta
`git-init`:

```bash
cloudflared tunnel --config cloudflared/config.yml run citas-platinum-spa
```

Pero se cae en cuanto cierras esa terminal o apagas la computadora.

**6.4. Probar:** <https://citas.platinum-spaypeluqueria.co.uk/salon/citas>

## Notas

- ⚠️ **Solo una máquina debe tener el túnel corriendo a la vez.** El túnel
  `citas-platinum-spa` y el dominio público apuntan a **una** base de datos
  Odoo local — la de la máquina donde `cloudflared` esté corriendo en ese
  momento. Si lo dejas activo en la Mac **y** lo activas en la Windows al
  mismo tiempo, Cloudflare reparte las visitas entre ambas sin avisar, y
  cada una tiene datos distintos (citas, clientes) → vas a perder reservas
  o ver información inconsistente. Cuando la Windows quede como la máquina
  "viva" de producción: en la Mac, para el servicio con
  `launchctl unload ~/Library/LaunchAgents/com.cloudflare.cloudflared.plist`
  (o desinstálalo con `cloudflared service uninstall`) y sigue usando
  `http://localhost:8069` en la Mac solo para desarrollo/pruebas, sin
  exponerlo a internet.
- **No repitas** la restauración de la base de datos si ya la hiciste una
  vez en esa máquina — `docker compose down` / `up` normales conservan los
  volúmenes (`odoo-db-data`, `odoo-web-data`); solo hace falta restaurar tras
  un `docker compose down -v` (que sí borra los volúmenes) o en una máquina
  nueva de verdad.
- Si el link público (`citas.platinum-spaypeluqueria.co.uk`) da error 530
  ("no hay túnel activo") pero `http://localhost:8069` sí funciona, es que
  el proceso `cloudflared` no está corriendo — revisa con `pgrep -fl
  cloudflared` y, si instalaste el servicio permanente (sección 6.3), con
  `launchctl list | grep cloudflare`.
- El gestor de bases de datos web (`/web/database/manager`) está
  deliberadamente **deshabilitado** (`list_db = False` en `odoo.conf`) por
  seguridad, ya que el sitio está expuesto a internet vía Cloudflare Tunnel.
  Todo respaldo/restauración futuro se hace por línea de comandos como en el
  paso 4.
- Las credenciales del túnel de Cloudflare y cualquier respaldo de base de
  datos (contiene datos reales de clientes) **no se suben a git** a
  propósito — transpórtalos por fuera (USB, Drive, AirDrop).
