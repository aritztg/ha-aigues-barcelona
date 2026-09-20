# Aigües de Barcelona for Home Assistant

[![Test](https://github.com/aritztg/ha-aigues-barcelona/actions/workflows/test.yaml/badge.svg)](https://github.com/aritztg/ha-aigues-barcelona/actions/workflows/test.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Read your [Aigües de Barcelona](https://www.aiguesdebarcelona.cat/) water meter from
[Home Assistant](https://www.home-assistant.io/), with automatic login and no hourly token
copying.

[English](#english) · [Castellano](#castellano)

## About this fork

The original project, [duhow/hass-aigues-barcelona](https://github.com/duhow/hass-aigues-barcelona),
was archived on 19 September 2026. Its author invited people to carry it on elsewhere, so
this repository does that with his permission. From the thread on
[PR #47](https://github.com/duhow/hass-aigues-barcelona/pull/47#issuecomment-5741453298):

> Ahora mismo mis intereses han cambiado y desisto de mantener esta integración.
> Así que a la gente que quiera arreglar este problema, os animo a que pongáis un
> repositorio en común y lo tratéis de arreglar como consideréis.

In English: his interests have changed and he is giving up maintaining the integration, so
he encourages anyone who wants to fix the problem to set up a shared repository and fix it
as they see fit.

The integration is duhow's work, with contributions from martibarri and paissad.

## English

### What it does

The integration adds a `sensor` with your water meter's latest available reading, and
imports long-term statistics so consumption appears in Home Assistant's Energy dashboard.

Readings run one to four days behind. That is how Aigües de Barcelona publishes them, and
no integration can do better: the meter is read remotely, not live.

### Automatic login

The login endpoint validates a reCAPTCHA with Google server side, so the token cannot be
fetched with a plain HTTP request. The reCAPTCHA script has to run in a real browser on
the site's own domain. Until now that meant copying the `ofexTokenJwt` cookie out of your
browser roughly once an hour, a problem open since
[January 2023](https://github.com/duhow/hass-aigues-barcelona/issues/5).

Give the integration a [Browserless](https://www.browserless.io/) API key during setup and
it handles that itself. Browserless renders a stub page on the Aigües domain, solves the
challenge, and returns the reCAPTCHA token. Home Assistant then performs the login itself,
with that token, from your own connection.

Two consequences are worth spelling out:

- **Your NIF and password never leave Home Assistant.** The remote browser is only asked
  to mint a captcha token, which carries nothing about your account.
- The login arrives from your own IP, which is the one the site expects. Posting from a
  datacentre range is unreliable, because the site sits behind a WAF that answers rejected
  ranges with its own "information not available" screen.

Leave the key empty and everything works as before, asking you for the token by hand.

#### What it costs

Browserless gives 1000 units a month with no card. Measured against a real login:

| item | units |
| --- | --- |
| browser session, one block per 30 seconds | 1 to 4 |
| solving the image challenge | 10 |
| one complete login | 11 or 12, up to 14 |
| reading contracts and consumption | 0 |

The challenge is what varies. Google has solved it in 7 seconds and in 43, and the session
bills in 30-second blocks. It does not go above 14, because the challenge wait is capped at
60 seconds and the script at 20.

At one poll a day that comes to around 360 units a month, a little over a third of the free
plan. Readings themselves do not go through Browserless: once there is a token, Home
Assistant calls the API on its own.

That is why the integration polls once a day. The token lasts an hour, so every poll costs
a login, and every four hours would be 1980 units a month. Nothing is lost by waiting,
since the reading is days behind anyway.

### Installation

1. In [HACS](https://hacs.xyz/), add this repository as a custom repository
   (`aritztg/ha-aigues-barcelona`, category *Integration*).
2. Install Aigües de Barcelona and restart Home Assistant.
3. Go to Settings, then Devices & Services, then Add integration, and search for it.
4. Enter your NIF and password. Optionally add a Browserless API key for automatic login.

### Upgrading from 0.4.x

Version 0.6.0 changes which component owns the sensor's long-term statistics, and the
series recorded before the upgrade is not trustworthy. If your Energy dashboard shows
swings of hundreds of cubic metres, clear that history rather than keeping it.

### What 0.6.0 fixes

Water readings jumped up and down, and the Energy dashboard reported daily consumption of
around 956 m³, which was the meter's entire lifetime volume. Two faults caused it.

The newest reading was taken as `consumptions[-1]`, trusting an order the API never
promises. When the seven-day window came back shuffled, the sensor published a reading
from days earlier, so the meter appeared to run backwards.

Two components also wrote the same statistics series. The entity declared a `state_class`,
which makes Home Assistant's recorder compile statistics for it, while the integration
imported its own for the same id. The recorder counted consumption since it started
watching; the integration wrote the meter's absolute reading. They overwrote each other
every hour.

The entity no longer declares a `state_class`, which leaves the series to the integration.
That also keeps each reading timestamped when the water was used rather than when the data
arrived. The imported `sum` is clamped so it never decreases.

### Development

```bash
uv sync --group dev     # environment, including the Home Assistant test harness
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

`pre-commit install` wires the same checks into your commits. Ruff replaces what used to be
black, flake8, pyupgrade, isort and docformatter.

## Castellano

### Qué hace

La integración añade un `sensor` con la última lectura disponible de tu contador de agua, e
importa las estadísticas de largo plazo para que el consumo aparezca en el panel de Energía
de Home Assistant.

Las lecturas llegan con uno a cuatro días de retraso. Es como las publica Aigües de
Barcelona y ninguna integración puede mejorarlo: el contador se lee en remoto, no en vivo.

### Login automático

La API valida el login contra un reCAPTCHA que comprueba con Google en su servidor, así que
el token no se puede pedir con una petición normal. El script de reCAPTCHA tiene que
ejecutarse en un navegador de verdad sobre el dominio del sitio. Hasta ahora eso
significaba copiar a mano la cookie `ofexTokenJwt` cada hora, un problema abierto desde
[enero de 2023](https://github.com/duhow/hass-aigues-barcelona/issues/5).

Si le das una clave de API de [Browserless](https://www.browserless.io/) al configurar la
integración, se resuelve solo. Browserless carga una página en blanco en el dominio de
Aigües de Barcelona, resuelve el reto y devuelve el token de reCAPTCHA. El login lo hace
Home Assistant, con ese token, desde tu propia conexión.

Conviene dejar claras dos consecuencias:

- **Tu NIF y tu contraseña no salen de Home Assistant.** Al navegador remoto solo se le
  pide generar un token de captcha, que no lleva nada de tu cuenta.
- La petición de login sale de tu IP, que es la que el sitio está acostumbrado a ver.
  Enviarla desde un rango de centro de datos no es fiable, porque el sitio está tras un WAF
  que responde a los rangos rechazados con su pantalla de «información no disponible».

Si dejas la clave vacía, todo funciona como antes y se te pedirá el token a mano.

#### Lo que cuesta

Browserless regala 1000 unidades al mes sin pedir tarjeta. Medido sobre el login real:

| concepto | unidades |
| --- | --- |
| la sesión de navegador, un bloque por cada 30 segundos | 1 a 4 |
| resolver el reto de imágenes | 10 |
| un login completo | 11 o 12, hasta 14 |
| leer contratos y consumos | 0 |

Lo que varía es el reto. Google lo ha resuelto en 7 segundos unas veces y en 43 otras, y la
sesión se cobra por bloques de 30. Por encima de 14 no sube, porque la espera del reto está
limitada a 60 segundos y la del script a 20.

Con una consulta diaria salen unas 360 unidades al mes, poco más de un tercio del plan
gratuito. Las lecturas no pasan por Browserless: una vez hay token, Home Assistant llama a
la API por su cuenta.

Por eso la integración consulta una vez al día. El token dura una hora, así que cada
consulta gasta un login, y cada cuatro horas serían 1980 unidades al mes. No se pierde nada
por esperar, porque la lectura llega con días de retraso de todos modos.

### Instalación

1. En [HACS](https://hacs.xyz/), añade este repositorio como repositorio personalizado
   (`aritztg/ha-aigues-barcelona`, categoría *Integración*).
2. Instala Aigües de Barcelona y reinicia Home Assistant.
3. Ve a Ajustes, Dispositivos y servicios, Añadir integración, y búscala.
4. Introduce tu NIF y tu contraseña. Opcionalmente, añade una clave de Browserless para el
   login automático.

### Si vienes de la 0.4.x

La 0.6.0 cambia qué componente es dueño de las estadísticas de largo plazo del sensor, y la
serie registrada antes de actualizar no es fiable. Si tu panel de Energía muestra saltos de
cientos de metros cúbicos, borra ese histórico en vez de conservarlo.

### Qué arregla la 0.6.0

Las lecturas de agua daban saltos arriba y abajo, y el panel de Energía llegaba a informar
de un consumo diario de unos 956 m³, que era el volumen acumulado de toda la vida del
contador. Lo causaban dos fallos.

La lectura más reciente se cogía como `consumptions[-1]`, dando por supuesto un orden que
la API nunca promete. Cuando la ventana de siete días venía desordenada, el sensor
publicaba una lectura de días antes, y el contador parecía ir hacia atrás.

Además, dos componentes escribían la misma serie estadística. La entidad declaraba un
`state_class`, lo que hace que el recorder de Home Assistant compile estadísticas para
ella, mientras la integración importaba las suyas para ese mismo id. El recorder contaba el
consumo desde que empezó a observar; la integración escribía la lectura absoluta del
contador. Se pisaban cada hora.

La entidad ya no declara `state_class`, lo que deja la serie a la integración. Eso mantiene
además cada lectura fechada en el momento en que se gastó el agua y no en el que llegó el
dato. El `sum` importado se protege para que nunca decrezca.

### Desarrollo

```bash
uv sync --group dev     # entorno, incluido el banco de pruebas de Home Assistant
uv run pytest           # tests
uv run ruff check .     # linter
uv run ruff format .    # formateo
```

`pre-commit install` engancha las mismas comprobaciones a tus commits. Ruff sustituye a lo
que antes eran black, flake8, pyupgrade, isort y docformatter.

## Licence

[MIT](LICENSE), as in the original project.
