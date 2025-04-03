"""
CLI Edictos
"""

from datetime import datetime

import click
import sys

from lib.exceptions import MyAnyError

from portal_notarias.app import create_app
from portal_notarias.blueprints.edictos.tasks import enviar_email_acuse_recibido as enviar_email_acuse_recibido_task
from portal_notarias.blueprints.edictos.tasks import enviar_email_republicacion as enviar_email_republicacion_task
from portal_notarias.blueprints.edictos.models import Edicto
from portal_notarias.blueprints.edictos_acuses.models import EdictoAcuse
from portal_notarias.extensions import database

app = create_app()
app.app_context().push()
database.app = app


@click.group()
def cli():
    """Edictos"""


@click.command()
@click.option("--fecha", default="", type=str, help="Fecha para consultar en edictos_acuses")
@click.option("--probar", is_flag=True, help="Probar sin cambiar la BD")
def republicar(fecha, probar):
    """Republicar Edictos, toma los registros de edictos_acuses para insertar Edictos"""
    click.echo("Republicando Edictos: ", nl=False)

    # Si NO viene la fecha, por defecto se usa la fecha de hoy
    fecha_dt = datetime.now().date()

    # Si viene la fecha, validar
    if fecha != "":
        try:
            fecha_dt = datetime.strptime(fecha, "%Y-%m-%d").date()
        except ValueError:
            click.echo("Error: El formato de la fecha debe ser YYYY-MM-DD.")
            sys.exit(1)

    # Consultar edictos_acuses, filtrados por la fecha
    edictos_acuses = EdictoAcuse.query.filter(EdictoAcuse.fecha == fecha_dt).filter(EdictoAcuse.estatus == "A").all()

    # Inicializar listado de mensajes
    mensajes = []

    # Bucle por edictos_acuses
    for edicto_acuse in edictos_acuses:
        click.echo(".", nl=False)

        # El Edicto original es el que se subio
        edicto_original = edicto_acuse.edicto

        # Si en edicto_original, edicto_id_original es CERO, se va actualizar con su mismo id
        if edicto_original.edicto_id_original == 0:
            edicto_original.edicto_id_original = edicto_original.id
            edicto_original.save()
            click.echo("@", nl=False)

        # Puede que ya este publicado, asi que consultamos
        edicto_ya_republicado = (
            Edicto.query.filter(Edicto.edicto_id_original == edicto_original.id)
            .filter(Edicto.fecha == fecha_dt)
            .filter(Edicto.estatus == "A")
            .first()
        )

        # Si existe el Edicto, con ese id original y fecha, se omite
        if edicto_ya_republicado:
            continue

        # Determinar la cantidad de Edictos que tienen edicto_id_original
        edictos_ya_publicados_cantidad = (
            Edicto.query.filter(Edicto.edicto_id_original == edicto_original.id).filter(Edicto.estatus == "A").count()
        )

        # Crear Edicto
        edicto = Edicto(
            autoridad=edicto_original.autoridad,
            fecha=fecha_dt,  # Fecha de republicacion
            descripcion=edicto_original.descripcion,
            expediente=edicto_original.expediente,
            numero_publicacion=int(edictos_ya_publicados_cantidad) + 1,
            archivo=edicto_original.archivo,
            url=edicto_original.url,
            acuse_num=0,
            edicto_id_original=edicto_original.id,
        )

        # Si probar es falso, insertar el edicto
        if probar is False:
            edicto.save()

        # Poner un + en pantalla
        click.echo("+", nl=False)

        # Agregar el mensaje
        mensajes.append(f"{edicto.autoridad.clave} {edicto.fecha} {edicto.descripcion}")

    # Mostrar mensaje final
    click.echo()
    click.echo("\n".join(mensajes))


@click.command()
@click.argument("edicto_id", type=int)
def enviar_email_acuse_recibido(edicto_id: int):
    """Enviar mensaje de acuse de recibo de un Edicto"""

    # Ejecutar tarea
    try:
        mensaje = enviar_email_acuse_recibido_task(edicto_id)
    except MyAnyError as error:
        click.echo(f"Error: {error}")
        sys.exit(1)

    # Mensaje de termino
    click.echo(mensaje)


@click.command()
@click.argument("edicto_id", type=int)
def enviar_email_republicacion(edicto_id: int):
    """Enviar mensaje de republicacion de un Edicto"""

    # Ejecutar tarea
    try:
        mensaje = enviar_email_republicacion_task(edicto_id)
    except MyAnyError as error:
        click.echo(f"Error: {error}")
        sys.exit(1)

    # Mensaje de termino
    click.echo(mensaje)


cli.add_command(enviar_email_acuse_recibido)
cli.add_command(enviar_email_republicacion)
cli.add_command(republicar)
