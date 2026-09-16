# Aigües de Barcelona para Home Assistant

Este `custom_component` permite importar los datos de [Aigües de Barcelona](https://www.aiguesdebarcelona.cat/) en [Home Assistant](https://www.home-assistant.io/).

Puedes ver el 🚰 consumo de agua que has hecho directamente en Home Assistant, y con esa información también puedes crear tus propias automatizaciones y avisos :)

Si te gusta el proyecto, dale a ⭐ **Star** ! 😊

## Login automático

La API valida el login contra un reCAPTCHA que comprueba con Google en su servidor, así
que el token no se puede pedir con una petición normal: hace falta que el script de
reCAPTCHA se ejecute en un navegador de verdad sobre el dominio del sitio. Por eso hasta
ahora había que copiar el token a mano de la 🍪 cookie `ofexTokenJwt` cada hora.

Si le das una clave de API de [Browserless](https://www.browserless.io/) al configurar la
integración, eso se resuelve solo. Browserless carga una página en blanco en el dominio de
Aigües de Barcelona, resuelve el reto de imágenes y devuelve el token de reCAPTCHA. **El
login lo hace Home Assistant**, con ese token, desde tu propia conexión.

Eso último importa: **tu NIF y tu contraseña no salen de Home Assistant**. El servicio
remoto solo genera un captcha, que no lleva nada de tu cuenta. Y la petición de login sale
de tu IP, que es la que el sitio está acostumbrado a ver.

Si dejas la clave vacía, todo funciona como antes y se te pedirá el token a mano.

### Lo que cuesta

Browserless regala 1000 unidades al mes sin pedir tarjeta. Medido sobre el login real:

| concepto | unidades |
| --- | --- |
| la sesión de navegador, 18 a 25 segundos | 1 |
| resolver el reto de imágenes | 10 |
| **un login completo** | **11** |
| leer contratos y consumos | 0 |

Con una consulta diaria son 330 unidades al mes, un tercio del plan gratuito. Las lecturas
no pasan por Browserless: una vez hay token, Home Assistant llama a la API por su cuenta.

Y por eso la integración consulta **una vez al día**: el token dura una hora, así que cada
consulta gasta un login. Cada cuatro horas serían 1980 unidades al mes y no caben. No se
pierde nada, porque la lectura del contador llega con uno a cuatro días de retraso.

## Uso

Esta integración expone un `sensor` con el último valor disponible de la lectura de agua del día de hoy.
La lectura que se muestra, puede estar demorada **hasta 4 días o más** (normalmente es 1-2 días).

La información se consulta **cada 4 horas** para no sobresaturar el servicio.

## Instalación

1. Via [HACS](https://hacs.xyz/), busca e instala este componente personalizado.

[![Install repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=duhow&repository=hass-aigues-barcelona&category=integration)

2. Cuando lo tengas descargado, agrega la integración en Home Assistant.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=aigues_barcelona)

## Ayuda

No soy un experto en Home Assistant, hay conceptos que son nuevos para mí en cuanto a la parte Developer. Así que puede que tarde en implementar las nuevas requests.

Se agradece cualquier Pull Request si tienes conocimiento en la materia :)

Si encuentras algún error, puedes abrir un Issue.

## To-Do

- [x] Sensor de último consumo disponible
- [x] Soportar múltiples contratos
- [x] **BETA** Publicar el consumo en [Energía](https://www.home-assistant.io/docs/energy/)
