# Kit Progresa

Una rutina de Claude que cada semana revisa los expedientes de tus asesoradas en
Google Drive, arma una hoja maestra con el resumen de cada una y te manda un
semáforo por Telegram: quién va bien, a quién revisar y por qué.

Corre en la nube de Anthropic, así que funciona con tu computadora apagada.
Este repositorio solo tiene código: ningún dato de alumnas.

La guía de la clase, paso a paso y en PDF:
[docs/Guia-Rutinas-IA-Gerardo-Tello.pdf](docs/Guia-Rutinas-IA-Gerardo-Tello.pdf).

## Qué necesitas

- Claude Pro o Max (las rutinas usan tu suscripción).
- El conector de **Google Drive** conectado en claude.ai.
- Un bot de Telegram, si quieres el aviso ahí (opcional).
- Tu plantilla de Google Sheets por asesorada.

## 1. Organiza tu Drive

```
Progresa/                          ← tu carpeta raíz (el nombre es libre)
  1. MARIA SOTO/
    MESOCICLO 1                    ← copia de tu plantilla
  2. ROSA ISELA/
    MESOCICLO 1
  CHECK IN (Respuestas)            ← hoja vinculada a tu formulario de check-in
```

- Cada asesorada tiene su carpeta, que empieza con un número y un punto.
- Dentro va su hoja `MESOCICLO N`. Si hay varias, se usa la de número mayor.
- En el formulario de check-in, activa **Recopilar direcciones de correo** y
  agrega la pregunta **Nombre completo**. Con eso se empareja cada respuesta con
  su asesorada.
- En las respuestas del formulario, usa **Vincular a Hojas de cálculo** y deja
  esa hoja en la carpeta raíz.
- La rutina crea y mantiene la hoja **Control del coach**: una fila por asesorada
  por semana, la más reciente arriba. La versión anterior se va a la papelera.

## 2. Prepara el entorno de la nube

En claude.ai/code, en la pantalla de nueva sesión, abre el selector de entorno
y toca el ícono de ajustes de tu entorno de nube.

- **Acceso a la red:** deja activados los administradores de paquetes y agrega
  el dominio `api.telegram.org`.
- **Variables de entorno**, solo si usas Telegram:
  ```
  TELEGRAM_BOT_TOKEN=el_token_que_te_da_BotFather
  TELEGRAM_CHAT_ID=tu_numero_de_userinfobot
  ```
  Cualquiera que use ese entorno puede leer estas variables, así que el entorno
  debe ser solo tuyo. Si el token se filtra, sácale uno nuevo con `/revoke` en
  @BotFather.

## 3. Crea las rutinas

Son dos, con la misma configuración y distinto prompt y horario:

| Rutina | Horario sugerido | Qué hace |
|---|---|---|
| Resumen semanal | El día después de tu check-in, por ejemplo sábado 8:07 a. m. | Regenera la hoja maestra y te manda el semáforo, los pagos y las renovaciones |
| Aviso de inactividad | Diario, por ejemplo 9:07 a. m. | Solo te escribe si alguna asesorada lleva 5 días o más sin registrar |

En las dos:

- **Repositorio (fuente):** `https://github.com/tellocoach/kit-progresa`. La rutina
  lo clona al empezar y usa el script de ahí.
- **Modelo:** Haiku 5.5. La rutina solo mueve archivos; los cálculos los hace
  el script, así que gasta muy poco.
- **Conector:** Google Drive.
- **Instrucciones:** copia el prompt de [prompt_rutina.md](prompt_rutina.md) y pon
  el id de tu carpeta raíz.
- **Entorno:** el que preparaste en el paso 2. No necesita script de
  configuración.

## Cómo se actualiza

Cada corrida clona este repositorio y corre `instalar.sh`, que copia el script
del propio repositorio. Cuando hay mejoras, la siguiente corrida ya las usa.

No uses `curl … | bash` en el prompt: las rutinas bloquean, por seguridad, el
código descargado de internet y ejecutado al vuelo. Declarar el repositorio
como fuente es la forma permitida.

## Pagos y renovaciones

El script lee el sistema de pagos de la pestaña INTRO:

- **Fechas de pago:** C37, D37 y E37. La casilla de «pagado» va debajo (C38).
- **Cantidad:** C35.
- **Fin del mesociclo:** 12 semanas desde la fecha de inicio (D11 de
  REVISIONES INTEGRALES).

Avisa en el resumen semanal cuando el siguiente pago está a 7 días o menos,
cuando un pago ya pasó y su casilla sigue sin marcar, y cuando el mesociclo
termina en 7 días o menos («toca renovar»). La hoja maestra guarda el próximo
pago y el fin del mesociclo de cada asesorada.

## Inactividad

Cuenta los días desde el último registro de pasos, sueño o check-in. Las series
de entrenamiento no cuentan, porque la plantilla no les pone fecha. Si una
asesorada no ha registrado nada desde su fecha de inicio, también avisa. El
umbral es de 5 días y se cambia en `CONFIG`.

## Si tu plantilla es distinta

Las celdas que lee el script están al inicio de
[rutina_progresa.py](rutina_progresa.py), en `CONFIG`: nombre, correo, peso,
fecha de inicio, bloques de cada semana y palabras clave del semáforo. Haz un
fork, ajústalas y cambia la dirección en `instalar.sh` y en tu prompt.

## Cómo decide el semáforo

- **Rojo:** dolor, malestar, lesión o enfermedad en el check-in o en las notas
  de las series; «¿cómo andas hoy?» de 5.
- **Naranja:** cansancio o desánimo, apego fuera de 90–110 %, 5 o más días sin
  registrar, o sin check-in en los últimos 7 días.
- **Verde:** todo lo demás.
- Las preguntas de «¿requieres algún ajuste…?» que no se contestan con «no»
  aparecen como «pide ajuste de dieta» o «de rutina».

## Demo en vivo: pagos por Telegram

Una rutina básica, sin programa, para armarla en clase: le escribes a tu bot
«pago María Soto 1500 efectivo» y la rutina lo agrega a la hoja «Pagos» de tu
Drive, calcula su próximo pago y te contesta con el total del mes. Cada mañana a
las 9 te avisa a quién le toca pagar. Las instrucciones están en
[demo_pagos.md](demo_pagos.md).

## Privacidad

- Los datos de salud se quedan en tu Drive y en tu hoja maestra.
- Telegram solo recibe categorías («dolor reportado», «pide ajuste»), nunca el
  texto completo del check-in.
- El script no guarda nada fuera de la corrida.
