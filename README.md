# Aigües de Barcelona for Home Assistant

[![Test](https://github.com/aritztg/ha-aigues-barcelona/actions/workflows/test.yaml/badge.svg)](https://github.com/aritztg/ha-aigues-barcelona/actions/workflows/test.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

See how much water you are using, in Home Assistant, without copying a token out of your
browser every hour.

[English](#english) · [Castellano](#castellano)

## What this fork adds

The headline is the automatic login. Aigües de Barcelona guards its login with a reCAPTCHA,
and for the last three years the only way in was to copy a cookie by hand, roughly once an
hour. This version solves the captcha through [Browserless](https://www.browserless.io/),
comfortably inside its free tier, and your credentials never leave Home Assistant.

It also clears up three things left open in the original:

- Water readings that went backwards, which the Energy dashboard reported as negative
  consumption.
- Two components writing the same statistics series with different ideas of what the
  numbers meant, so they overwrote each other every hour.
- Tooling and CI that had not been touched since 2024. There are tests now, and they run.

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

You get a `sensor` with your meter's latest reading, plus long-term statistics, so your
water shows up in the Energy dashboard next to electricity and gas.

One thing to expect: readings run one to four days behind. That is simply how Aigües de
Barcelona publishes them. The meter is read remotely on their schedule, not yours, and no
integration can get around it.

### Automatic login

The login endpoint checks a reCAPTCHA with Google server side, so you cannot just ask for
a token over HTTP. The reCAPTCHA script has to run in a real browser, on the site's own
domain. That is why people have been copying the `ofexTokenJwt` cookie out of their browser
since [January 2023](https://github.com/duhow/hass-aigues-barcelona/issues/5).

Give the integration a [Browserless](https://www.browserless.io/) API key when you set it
up and that chore goes away. Browserless renders a stub page on the Aigües domain, solves
the challenge, and hands back the reCAPTCHA token. Home Assistant then logs in itself, with
that token, over your own connection.

Two things follow from that, and they are the reason it works this way:

- **Your NIF and password never leave Home Assistant.** The remote browser is only asked
  for a captcha token, which says nothing about your account.
- The login arrives from your own IP, which is the one the site expects. Sending it from a
  datacentre range tends to fail, since the site sits behind a WAF that answers rejected
  ranges with an "information not available" page that looks exactly like an outage.

Leave the key empty and nothing changes: you will be asked for the token by hand, as before.

#### What it costs

Browserless gives you 1000 units a month without asking for a card. A real login breaks
down like this:

| item | units |
| --- | --- |
| browser session, billed per 30-second block | 1 to 4 |
| solving the image challenge | 10 |
| one complete login | usually no more than 14 |
| reading contracts and consumption | 0 |

The variable part is the challenge itself. Google has taken anywhere from under 10 seconds
to around 45, and the session bills in 30-second blocks. It does not run away with your
quota, because the wait is capped at 60 seconds and the script at 20.

At one login a day that works out around 360 units a month, a little over a third of the
free plan. The readings themselves cost nothing: once there is a token, Home Assistant
talks to the API on its own.

Which is why it polls once a day. A token lasts an hour, so every poll costs a login, and
polling every four hours would need 1980 units a month. You lose nothing by waiting, since
the reading is days old regardless.

### Installation

1. In [HACS](https://hacs.xyz/), add this repository as a custom repository
   (`aritztg/ha-aigues-barcelona`, category *Integration*).
2. Install Aigües de Barcelona and restart Home Assistant.
3. Go to Settings, then Devices & Services, then Add integration, and search for it.
4. Enter your NIF and password. Add a Browserless API key too if you want the automatic
   login.

### Upgrading from 0.4.x

Version 0.6.0 changes which component owns the sensor's long-term statistics, and the
series recorded before the upgrade is not worth keeping. If your Energy dashboard is
showing swings of hundreds of cubic metres, that is the old data. Clear it.

### What 0.6.0 fixes

Readings jumped around, and the Energy dashboard once reported 956 m³ of water in a single
day, which happened to be the meter's entire lifetime volume. Two separate faults were
behind it.

The first: the newest reading was picked as `consumptions[-1]`, trusting an order the API
never promises. When the seven-day window came back shuffled, the sensor published a
reading from days earlier, and the meter appeared to run backwards.

The second was subtler. The entity declared a `state_class`, which tells Home Assistant's
recorder to compile statistics for it, while the integration imported statistics for that
same id. The recorder was counting consumption since it started watching; the integration
was writing the meter's absolute reading. Both were right by their own logic, and they
overwrote each other every hour.

The entity no longer declares a `state_class`, so the series belongs to the integration
alone. That has a second benefit: each reading keeps the timestamp of when the water was
actually used, rather than when the data happened to arrive. The imported `sum` is also
clamped so it can never decrease.

### Development

```bash
uv sync --group dev     # environment, including the Home Assistant test harness
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

`pre-commit install` wires the same checks into your commits. Ruff does the work that used
to need black, flake8, pyupgrade, isort and docformatter.

## Castellano

### Qué hace

Te da un `sensor` con la última lectura de tu contador, más las estadísticas de largo
plazo, así que el agua aparece en el panel de Energía junto a la luz y el gas.

Una cosa que conviene saber: las lecturas llegan con uno a cuatro días de retraso. Es
sencillamente como las publica Aigües de Barcelona. El contador se lee en remoto y a su
ritmo, no al tuyo, y ninguna integración puede saltárselo.

### Login automático

La API comprueba un reCAPTCHA con Google en su servidor, así que no puedes pedir un token
por HTTP y ya está. El script de reCAPTCHA tiene que ejecutarse en un navegador de verdad,
sobre el dominio del sitio. Por eso la gente lleva copiando a mano la cookie `ofexTokenJwt`
desde [enero de 2023](https://github.com/duhow/hass-aigues-barcelona/issues/5).

Dale a la integración una clave de API de [Browserless](https://www.browserless.io/) al
configurarla y te quitas esa tarea. Browserless carga una página en blanco en el dominio de
Aigües, resuelve el reto y devuelve el token de reCAPTCHA. El login lo hace después Home
Assistant, con ese token, por tu propia conexión.

De ahí salen dos cosas, y son la razón de que funcione así:

- **Tu NIF y tu contraseña no salen de Home Assistant.** Al navegador remoto solo se le
  pide un token de captcha, que no dice nada de tu cuenta.
- La petición de login sale de tu IP, que es la que el sitio espera. Enviarla desde un
  rango de centro de datos suele fallar, porque el sitio está tras un WAF que contesta a
  los rangos rechazados con una pantalla de «información no disponible» idéntica a una
  caída del servicio.

Si dejas la clave vacía no cambia nada: se te pedirá el token a mano, como hasta ahora.

#### Lo que cuesta

Browserless te da 1000 unidades al mes sin pedirte tarjeta. Un login real se reparte así:

| concepto | unidades |
| --- | --- |
| sesión de navegador, cobrada por bloques de 30 segundos | 1 a 4 |
| resolver el reto de imágenes | 10 |
| un login completo | normalmente no más de 14 |
| leer contratos y consumos | 0 |

La parte variable es el reto. Google ha tardado desde menos de 10 segundos hasta unos 45, y
la sesión se cobra por bloques de 30. No se te va de las manos, porque la espera está
limitada a 60 segundos y el script a 20.

Con un login al día salen unas 360 unidades al mes, poco más de un tercio del plan
gratuito. Las lecturas en sí no cuestan nada: una vez hay token, Home Assistant habla con
la API por su cuenta.

Por eso consulta una vez al día. Un token dura una hora, así que cada consulta gasta un
login, y hacerlo cada cuatro horas necesitaría 1980 unidades al mes. No pierdes nada por
esperar, porque la lectura tiene días de antigüedad de todos modos.

### Instalación

1. En [HACS](https://hacs.xyz/), añade este repositorio como repositorio personalizado
   (`aritztg/ha-aigues-barcelona`, categoría *Integración*).
2. Instala Aigües de Barcelona y reinicia Home Assistant.
3. Ve a Ajustes, Dispositivos y servicios, Añadir integración, y búscala.
4. Introduce tu NIF y tu contraseña. Añade también una clave de Browserless si quieres el
   login automático.

### Si vienes de la 0.4.x

La 0.6.0 cambia qué componente es dueño de las estadísticas de largo plazo del sensor, y la
serie registrada antes de actualizar no merece la pena conservarla. Si tu panel de Energía
muestra saltos de cientos de metros cúbicos, eso son los datos viejos. Bórralos.

### Qué arregla la 0.6.0

Las lecturas daban saltos, y el panel de Energía llegó a informar de 956 m³ de agua en un
solo día, que resultaban ser el volumen acumulado de toda la vida del contador. Detrás
había dos fallos distintos.

El primero: la lectura más reciente se cogía como `consumptions[-1]`, dando por supuesto un
orden que la API nunca promete. Cuando la ventana de siete días venía desordenada, el
sensor publicaba una lectura de días antes y el contador parecía ir hacia atrás.

El segundo era más sutil. La entidad declaraba un `state_class`, que le dice al recorder de
Home Assistant que compile estadísticas para ella, mientras la integración importaba
estadísticas para ese mismo id. El recorder contaba el consumo desde que empezó a observar;
la integración escribía la lectura absoluta del contador. Cada uno tenía razón según su
propia lógica, y se pisaban cada hora.

La entidad ya no declara `state_class`, así que la serie es solo de la integración. Eso
trae una segunda ventaja: cada lectura conserva la fecha de cuando se gastó el agua, y no
la de cuando llegó el dato. El `sum` importado además se protege para que nunca decrezca.

### Desarrollo

```bash
uv sync --group dev     # entorno, incluido el banco de pruebas de Home Assistant
uv run pytest           # tests
uv run ruff check .     # linter
uv run ruff format .    # formateo
```

`pre-commit install` engancha las mismas comprobaciones a tus commits. Ruff hace el trabajo
que antes necesitaba black, flake8, pyupgrade, isort y docformatter.

## Licence

[MIT](LICENSE), as in the original project.
