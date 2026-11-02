# Kit Progresa

Una rutina de Claude que cada semana revisa los expedientes de tus asesoradas en
Google Drive, arma una hoja maestra con el resumen de cada una y te manda un
semáforo por Telegram: quién va bien, a quién revisar y por qué.

Corre en la nube de Anthropic, así que funciona con tu computadora apagada.
Este repositorio solo tiene código: ningún dato de alumnas.

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

## 3. Crea la rutina

- **Modelo:** Haiku 5.5. La rutina solo mueve archivos; los cálculos los hace
  el script, así que gasta muy poco.
- **Conector:** Google Drive.
- **Instrucciones:** copia el texto de [prompt_rutina.md](prompt_rutina.md) y pon
  el id de tu carpeta raíz.
- **Horario:** tu día de check-in. Por ejemplo, el viernes a las 8:07 a. m. de
  México.

## Cómo se actualiza

Al empezar cada corrida, la rutina descarga la última versión de este
repositorio con `instalar.sh`. No tienes que copiar nada cuando hay mejoras.

## Si tu plantilla es distinta

Las celdas que lee el script están al inicio de
[rutina_progresa.py](rutina_progresa.py), en `CONFIG`: nombre, correo, peso,
fecha de inicio, bloques de cada semana y palabras clave del semáforo. Haz un
fork, ajústalas y cambia la dirección en `instalar.sh` y en tu prompt.

## Cómo decide el semáforo

- **Rojo:** dolor, malestar, lesión o enfermedad en el check-in o en las notas
  de las series; «¿cómo andas hoy?» de 5.
- **Naranja:** cansancio o desánimo, apego fuera de 90–110 %, 3 o más días sin
  registrar, o sin check-in en los últimos 7 días.
- **Verde:** todo lo demás.
- Las preguntas de «¿requieres algún ajuste…?» que no se contestan con «no»
  aparecen como «pide ajuste de dieta» o «de rutina».

## Privacidad

- Los datos de salud se quedan en tu Drive y en tu hoja maestra.
- Telegram solo recibe categorías («dolor reportado», «pide ajuste»), nunca el
  texto completo del check-in.
- El script no guarda nada fuera de la corrida.
