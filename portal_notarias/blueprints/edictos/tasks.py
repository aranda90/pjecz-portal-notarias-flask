"""
Edictos, tareas en el fondo
"""

import logging
from datetime import datetime
import os

import sendgrid
from dotenv import load_dotenv
from sendgrid.helpers.mail import Email, To, Cc, Content, Mail

from lib.exceptions import MyNotExistsError, MyUnknownError
from lib.tasks import set_task_error, set_task_progress
from portal_notarias.app import create_app
from portal_notarias.blueprints.edictos.models import Edicto
from portal_notarias.blueprints.usuarios.models import Usuario
from portal_notarias.extensions import database

load_dotenv()  # Take environment variables from .env

bitacora = logging.getLogger(__name__)
bitacora.setLevel(logging.INFO)
formato = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")
empunadura = logging.FileHandler("logs/edictos.log")
empunadura.setFormatter(formato)
bitacora.addHandler(empunadura)

app = create_app()
app.app_context().push()
database.app = app

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "")
TIMEZONE = "America/Mexico_City"


def get_base_url():
    """Detectar si estamos en producción o desarrollo y retornar la URL base apropiada"""
    # Detectar entorno basado en variables de entorno o configuración
    environment = os.getenv("FLASK_ENV", "development")

    if environment == "production" or os.getenv("GAE_ENV", "").startswith("standard"):
        # Entorno de producción (Google App Engine o FLASK_ENV=production)
        return "https://notarias.justiciadigital.gob.mx"
    # Entorno de desarrollo local
    return "http://127.0.0.1:5001"


def republicacion_edictos(edicto_id: int, nueva_fecha: datetime) -> str:
    """Republicacion de edictos según la fecha elegida"""
    # Iniciar progreso
    set_task_progress(0, f"Iniciando republicación del edicto {edicto_id}.")
    # Obtener el edicto original
    edicto_original = Edicto.query.get(edicto_id)
    if not edicto_original:
        mensaje_error = f"El edicto {edicto_id} no existe."
        set_task_error(mensaje_error)
        raise MyNotExistsError(mensaje_error)
    # Validar que el edicto esté activo
    if edicto_original.estatus != "A":
        mensaje_error = f"El edicto {edicto_id} no está activo."
        set_task_error(mensaje_error)
        raise MyNotExistsError(mensaje_error)
    # Crear el nuevo edicto para republicación
    nuevo_edicto = Edicto(
        descripcion=edicto_original.descripcion,
        expediente=edicto_original.expediente,
        numero_publicacion=edicto_original.numero_publicacion,
        archivo=edicto_original.archivo,
        url=edicto_original.url,
        acuse_num=1,  # Reiniciar el contador de acuses
        fecha=nueva_fecha.date(),  # Nueva fecha de publicación
        estatus="A",  # Activar el nuevo edicto
        autoridad_id=edicto_original.autoridad_id,
        edicto_id_original=edicto_original.id,  # Relacionar con el original
    ).save()
    mensaje_final = f"Terminar republicacion del {nuevo_edicto.id}."
    set_task_progress(100, mensaje_final)
    bitacora.info(mensaje_final)
    return mensaje_final


def enviar_email_acuse_recibido(edicto_id: int) -> str:
    """Enviar mensaje de acuse de recibo de un Edicto"""

    # Consultar el edicto
    edicto = Edicto.query.get(edicto_id)

    # Si el edicto NO existe, causa un error y se termina
    if not edicto:
        mensaje = f"El edicto {edicto_id} no existe"
        bitacora.error(mensaje)
        raise MyNotExistsError(mensaje)

    # Si el estatus del edicto no es 'A', causa un error y se termina
    if edicto.estatus != "A":
        mensaje = f"El edicto {edicto_id} no esta activo"
        bitacora.error(mensaje)
        raise MyNotExistsError(mensaje)

    # Validar que se tiene el remitente y crear el remitente
    if SENDGRID_FROM_EMAIL == "":
        mensaje_error = "ERROR: No esta configurada la variable SENDGRID_FROM_EMAIL."
        bitacora.error(mensaje_error)
        return mensaje_error
    from_email = Email(SENDGRID_FROM_EMAIL)

    # Validar que se tiene SENDGRID_API_KEY y crear el cliente de SendGrid
    if SENDGRID_API_KEY == "":
        mensaje_error = "ERROR: No esta configurada la variable SENDGRID_API_KEY."
        bitacora.error(mensaje_error)
        return mensaje_error
    sendgrid_client = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)

    # Iniciar tarea
    mensaje_inicial = f"Inicia el envio del mensaje de acuse de recibo del edicto {edicto_id}"
    set_task_progress(0, mensaje_inicial)
    bitacora.info(mensaje_inicial)

    # Momento en que se elabora este mensaje
    momento = datetime.now()
    momento_str = momento.strftime("%d/%B/%Y %I:%M%p")

    # Definir el URL que lo llevara al acuse de recibo (detecta automáticamente el entorno)
    base_url = get_base_url()
    url = f"{base_url}/edictos/{edicto_id}"

    # Elaborar el contenido del mensaje de correo electronico
    contenidos = [
        "<h1>Plataforma Web</h1>",
        "<h2>PODER JUDICIAL DEL ESTADO DE COAHUILA DE ZARAGOZA</h2>",
        f"<p>Fecha de elaboración: {momento_str}.</p>",
        "<p>Ingrese el token recibido en el enlace de más abajo para validar que usted es el dueño de este correo electrónico.</p>",
        "<h2>TOKEN</h2>",
        f"<h1><code>{edicto.descripcion}</code></h1>",
        f"<h3><a href='{url}'>enlace de validación</a></h3>",
    ]
    content = Content("text/html", "".join(contenidos))

    # Obtener el email del usuario que pertenece a la autoridad del edicto
    usuario = Usuario.query.filter_by(autoridad_id=edicto.autoridad_id, estatus="A").first()
    if not usuario or not usuario.email:
        mensaje_error = f"ERROR: No se encontró un usuario activo con email para la autoridad {edicto.autoridad.clave}"
        set_task_error(mensaje_error)
        bitacora.error(mensaje_error)
        raise MyNotExistsError(mensaje_error)

    # Definir el destinatario principal (quien hace la publicación)
    to_email = To(usuario.email)

    # Definir copia para lucia.aranda@pjecz.gob.mx
    cc_email = Cc("lucia.aranda@pjecz.gob.mx")

    # Definir el asunto
    subject = f"Acuse de recibido del Edicto {edicto.descripcion}"

    # Enviar mensaje
    try:
        mail = Mail(from_email, to_email, subject, content)
        mail.add_cc(cc_email)
        sendgrid_client.client.mail.send.post(request_body=mail.get())
    except Exception as error:
        mensaje_error = f"ERROR: Fallo el envio del mensaje a {usuario.email} por error de SendGrid. {error}"
        set_task_error(mensaje_error)
        bitacora.error(mensaje_error)
        raise MyUnknownError(mensaje_error) from error

    # Mensaje de termino
    mensaje_final = f"Ya envie el mensaje de acuse de recibo del edicto {edicto_id}"
    set_task_progress(100, mensaje_final)
    bitacora.info(mensaje_final)
    return mensaje_final


def enviar_email_republicacion(edicto_id: int) -> str:
    """Enviar mensaje de republicacion de un Edicto"""

    # Consultar el edicto
    edicto = Edicto.query.get(edicto_id)

    # Si el edicto NO existe, causa un error y se termina
    if not edicto:
        mensaje = f"El edicto {edicto_id} no existe"
        bitacora.error(mensaje)
        raise MyNotExistsError(mensaje)

    # Si el estatus del edicto no es 'A', causa un error y se termina
    if edicto.estatus != "A":
        mensaje = f"El edicto {edicto_id} no esta activo"
        bitacora.error(mensaje)
        raise MyNotExistsError(mensaje)

    # Validar que se tiene el remitente y crear el remitente
    if SENDGRID_FROM_EMAIL == "":
        mensaje_error = "ERROR: No esta configurada la variable SENDGRID_FROM_EMAIL."
        bitacora.error(mensaje_error)
        return mensaje_error
    from_email = Email(SENDGRID_FROM_EMAIL)

    # Validar que se tiene SENDGRID_API_KEY y crear el cliente de SendGrid
    if SENDGRID_API_KEY == "":
        mensaje_error = "ERROR: No esta configurada la variable SENDGRID_API_KEY."
        bitacora.error(mensaje_error)
        return mensaje_error
    sendgrid_client = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)

    # Iniciar tarea
    mensaje_inicial = f"Inicia el envio del mensaje de republicacion del edicto {edicto_id}"
    set_task_progress(0, mensaje_inicial)
    bitacora.info(mensaje_inicial)

    # Momento en que se elabora este mensaje
    momento = datetime.now()
    momento_str = momento.strftime("%d/%B/%Y %I:%M%p")

    # Definir el URL que lo llevara al edicto republicado (detecta automáticamente el entorno)
    base_url = get_base_url()
    url = f"{base_url}/edictos/{edicto_id}"

    # Elaborar el contenido del mensaje de correo electronico
    contenidos = [
        "<h1>Plataforma Web</h1>",
        "<h2>PODER JUDICIAL DEL ESTADO DE COAHUILA DE ZARAGOZA</h2>",
        f"<p>Fecha de elaboración: {momento_str}.</p>",
        "<p>Se ha realizado la republicación del siguiente edicto:</p>",
        "<h2>EDICTO REPUBLICADO</h2>",
        f"<h3>Descripción: <code>{edicto.descripcion}</code></h3>",
        f"<p>Expediente: {edicto.expediente}</p>",
        f"<p>Fecha de republicación: {edicto.fecha}</p>",
        f"<p>Número de publicación: {edicto.numero_publicacion}</p>",
        f"<h3><a href='{url}'>Ver edicto republicado</a></h3>",
    ]
    content = Content("text/html", "".join(contenidos))

    # Obtener el email del usuario que pertenece a la autoridad del edicto
    usuario = Usuario.query.filter_by(autoridad_id=edicto.autoridad_id, estatus="A").first()
    if not usuario or not usuario.email:
        mensaje_error = f"ERROR: No se encontró un usuario activo con email para la autoridad {edicto.autoridad.clave}"
        set_task_error(mensaje_error)
        bitacora.error(mensaje_error)
        raise MyNotExistsError(mensaje_error)

    # Definir el destinatario principal (quien hace la publicación)
    to_email = To(usuario.email)

    # Definir copia para lucia.aranda@pjecz.gob.mx
    cc_email = Cc("lucia.aranda@pjecz.gob.mx")

    # Definir el asunto
    subject = f"Republicación del Edicto {edicto.descripcion}"

    # Enviar mensaje
    try:
        mail = Mail(from_email, to_email, subject, content)
        mail.add_cc(cc_email)
        sendgrid_client.client.mail.send.post(request_body=mail.get())
    except Exception as error:
        mensaje_error = f"ERROR: Fallo el envio del mensaje a {usuario.email} por error de SendGrid. {error}"
        set_task_error(mensaje_error)
        bitacora.error(mensaje_error)
        raise MyUnknownError(mensaje_error) from error

    # Mensaje de termino
    mensaje_final = f"Ya envie el mensaje de republicacion del edicto {edicto_id}"
    set_task_progress(100, mensaje_final)
    bitacora.info(mensaje_final)
    return mensaje_final
