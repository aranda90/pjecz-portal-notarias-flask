"""
Edictos, vistas
"""

from datetime import datetime, date, time, timedelta
import json
from urllib.parse import quote

from flask import Blueprint, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from pytz import timezone
from werkzeug.datastructures import CombinedMultiDict
from werkzeug.exceptions import NotFound

from lib.datatables import get_datatable_parameters, output_datatable_json
from lib.exceptions import (
    MyAnyError,
    MyBucketNotFoundError,
    MyFilenameError,
    MyFileNotFoundError,
    MyNotAllowedExtensionError,
    MyNotValidParamError,
    MyUnknownExtensionError,
)
from lib.google_cloud_storage import get_blob_name_from_url, get_media_type_from_filename, get_file_from_gcs
from lib.safe_string import safe_clave, safe_expediente, safe_message, safe_string
from lib.storage import GoogleCloudStorage
from lib.time_to_text import dia_mes_ano
from portal_notarias.blueprints.usuarios.decorators import permission_required

from portal_notarias.blueprints.autoridades.models import Autoridad
from portal_notarias.blueprints.bitacoras.models import Bitacora
from portal_notarias.blueprints.modulos.models import Modulo
from portal_notarias.blueprints.permisos.models import Permiso
from portal_notarias.blueprints.edictos.models import Edicto
from portal_notarias.blueprints.edictos.forms import EdictoNewForm, EdictoEditForm
from portal_notarias.blueprints.edictos_acuses.models import EdictoAcuse


# Zona horaria
TIMEZONE = "America/Mexico_City"
local_tz = timezone(TIMEZONE)
medianoche = time.min

MODULO = "EDICTOS"

DASHBOARD_CANTIDAD_DIAS = 1
LIMITE_DIAS = 365  # Un anio
LIMITE_ADMINISTRADORES_DIAS = 3650  # Administradores pueden manipular diez anios
LIMITE_DIAS_ELIMINAR = LIMITE_DIAS_RECUPERAR = LIMITE_DIAS_EDITAR = 1

edictos = Blueprint("edictos", __name__, template_folder="templates")


@edictos.route("/edictos/acuses/<id_hashed>")
def checkout(id_hashed):
    """Acuse del Edicto"""
    edicto = Edicto.query.get_or_404(Edicto.decode_id(id_hashed))
    dia, mes, anio = dia_mes_ano(edicto.creado)
    # Primera publicación siempre es número 1
    numero_publicacion = 1
    return render_template(
        "edictos/print.jinja2",
        edicto=edicto,
        dia=dia,
        mes=mes.upper(),
        anio=anio,
        fecha_del_acuse=None,
        numero_publicacion=numero_publicacion,
    )


@edictos.route("/edictos/acuses/<id_hashed>/<edicto_acuse_id>")
def checkout_notaria(id_hashed, edicto_acuse_id):
    """Acuse de las republicaciones del Edicto para notarias"""
    edicto = Edicto.query.get_or_404(Edicto.decode_id(id_hashed))
    edicto_acuse = EdictoAcuse.query.get_or_404(edicto_acuse_id)
    
    # Para republicaciones, usar la fecha del acuse, no la fecha de creación del edicto
    dia, mes, anio = dia_mes_ano(edicto_acuse.fecha)
    fecha_del_acuse = edicto_acuse.fecha
    
    # Calcular el número de publicación basado en la posición del acuse
    # Obtener todos los acuses del edicto ordenados por fecha
    acuses = EdictoAcuse.query.filter_by(edicto_id=edicto.id, estatus="A").order_by(EdictoAcuse.fecha).all()
    
    # Encontrar la posición del acuse actual y sumar 2 (1 para la publicación original + 1 para base 1)
    numero_publicacion = 1  # Por defecto
    for i, acuse in enumerate(acuses):
        if acuse.id == int(edicto_acuse_id):
            numero_publicacion = i + 2  # +2 porque la primera publicación es 1, y los acuses empiezan en 2
            break
    
    return render_template(
        "edictos/print.jinja2",
        edicto=edicto,
        dia=dia,
        mes=mes.upper(),
        anio=anio,
        fecha_del_acuse=fecha_del_acuse,
        numero_publicacion=numero_publicacion,
    )


@edictos.before_request
@login_required
@permission_required(MODULO, Permiso.VER)
def before_request():
    """Permiso por defecto"""


@edictos.route("/edictos/datatable_json", methods=["GET", "POST"])
def datatable_json():
    """DataTable JSON para listado de Edictos"""
    # Tomar parámetros de Datatables
    draw, start, rows_per_page = get_datatable_parameters()
    # Consultar
    consulta = Edicto.query
    # Primero filtrar por columnas propias
    if "estatus" in request.form:
        consulta = consulta.filter_by(estatus=request.form["estatus"])
    else:
        consulta = consulta.filter_by(estatus="A")
    if "autoridad_id" in request.form:
        autoridad = Autoridad.query.get(request.form["autoridad_id"])
        if autoridad:
            consulta = consulta.filter_by(autoridad=autoridad)
    if "fecha_desde" in request.form:
        consulta = consulta.filter(Edicto.fecha >= request.form["fecha_desde"])
    if "fecha_hasta" in request.form:
        consulta = consulta.filter(Edicto.fecha <= request.form["fecha_hasta"])
    if "descripcion" in request.form:
        consulta = consulta.filter(Edicto.descripcion.contains(safe_string(request.form["descripcion"])))
    if "numero_publicacion" in request.form:
        consulta = consulta.filter(Edicto.numero_publicacion.contains(request.form["numero_publicacion"]))
    # Ordenar y paginar
    registros = consulta.order_by(Edicto.fecha.desc()).offset(start).limit(rows_per_page).all()
    total = consulta.count()
    # Elaborar datos para DataTable
    data = []
    for resultado in registros:
        # Crear un diccionario para almacenar el detalle
        detalle = {
            "descripcion": resultado.descripcion,
        }
        # Verificar si 'edicto_id_original' es igual a 0 o es igual al id del edicto
        if resultado.edicto_id_original in {0, resultado.id}:
            # Si es igual a 0, agregar la URL al diccionario
            detalle["url"] = url_for("edictos.detail", edicto_id=resultado.id)
        data.append(
            {
                "fecha": resultado.fecha.strftime("%Y-%m-%d %H:%M:%S"),
                "detalle": detalle,
                "expediente": resultado.expediente,
                "numero_publicacion": resultado.numero_publicacion,
                "archivo": {
                    "descargar_url": resultado.descargar_url,
                },
            }
        )
    # Entregar JSON
    return output_datatable_json(draw, total, data)


@edictos.route("/edictos/admin_datatable_json", methods=["GET", "POST"])
def admin_datatable_json():
    """DataTable JSON para listado de edictos administradores"""
    # Tomar parámetros de Datatables
    draw, start, rows_per_page = get_datatable_parameters()
    # Consultar
    consulta = Edicto.query
    if "estatus" in request.form:
        consulta = consulta.filter_by(estatus=request.form["estatus"])
    else:
        consulta = consulta.filter_by(estatus="A")
    if "autoridad_id" in request.form:
        consulta = consulta.filter(Edicto.autoridad_id == request.form["autoridad_id"])
    elif "autoridad_clave" in request.form:
        autoridad_clave = safe_clave(request.form["autoridad_clave"])
        if autoridad_clave != "":
            consulta = consulta.join(Autoridad).filter(Autoridad.clave.contains(autoridad_clave))

    if "fecha_desde" in request.form:
        consulta = consulta.filter(Edicto.fecha >= request.form["fecha_desde"])
    if "fecha_hasta" in request.form:
        consulta = consulta.filter(Edicto.fecha <= request.form["fecha_hasta"])
    if "descripcion" in request.form:
        consulta = consulta.filter(Edicto.descripcion.like("%" + safe_string(request.form["descripcion"]) + "%"))
    if "expediente" in request.form:
        try:
            expediente = safe_expediente(request.form["expediente"])
            consulta = consulta.filter_by(expediente=expediente)
        except (IndexError, ValueError):
            pass
    if "numero_publicacion" in request.form:
        consulta = consulta.filter(Edicto.numero_publicacion.contains(request.form["numero_publicacion"]))
    registros = consulta.order_by(Edicto.fecha.desc()).offset(start).limit(rows_per_page).all()
    total = consulta.count()
    # Elaborar datos para DataTable
    data = []
    for edicto in registros:
        data.append(
            {
                "creado": edicto.creado.strftime("%Y-%m-%d %H:%M:%S"),
                "autoridad_clave": edicto.autoridad.clave,
                "fecha": edicto.fecha.strftime("%Y-%m-%d %H:%M:%S"),
                "detalle": {
                    "descripcion": edicto.descripcion,
                    "url": url_for("edictos.detail", edicto_id=edicto.id),
                },
                "expediente": edicto.expediente,
                "numero_publicacion": edicto.numero_publicacion,
                "archivo": {
                    "descargar_url": url_for("edictos.download", url=quote(edicto.url)),
                },
            }
        )
    # Entregar JSON
    return output_datatable_json(draw, total, data)


@edictos.route("/edictos")
def list_active():
    """Listado de Edictos activos"""

    # Definir valores por defecto
    filtros = None
    titulo = None
    mostrar_filtro_autoridad_clave = True

    # Si es administrador
    plantilla = "edictos/list.jinja2"
    if current_user.can_admin(MODULO):
        plantilla = "edictos/list_admin.jinja2"

    # Si viene autoridad_id o autoridad_clave en la URL, agregar a los filtros
    autoridad = None
    try:
        if "autoridad_id" in request.args:
            autoridad_id = int(request.args.get("autoridad_id"))
            autoridad = Autoridad.query.get(autoridad_id)
        elif "autoridad_clave" in request.args:
            autoridad_clave = safe_clave(request.args.get("autoridad_clave"))
            autoridad = Autoridad.query.filter_by(clave=autoridad_clave).first()
        if autoridad is not None:
            filtros = {"estatus": "A", "autoridad_id": autoridad.id}
            titulo = f"Edictos de {autoridad.descripcion_corta}"
            mostrar_filtro_autoridad_clave = False
    except (TypeError, ValueError):
        pass

    # Si es administrador
    if titulo is None and current_user.can_admin(MODULO):
        titulo = "Todos los Edictos"
        filtros = {"estatus": "A"}

    # Si puede editar o crear, solo ve lo de su autoridad
    if titulo is None and (current_user.can_insert(MODULO) or current_user.can_edit(MODULO)):
        filtros = {"estatus": "A", "autoridad_id": current_user.autoridad.id}
        titulo = f"Edictos de {current_user.autoridad.descripcion_corta}"
        mostrar_filtro_autoridad_clave = False

    # De lo contrario, es observador
    if titulo is None:
        filtros = {"estatus": "A"}
        titulo = "Edictos"

    # Entregar
    return render_template(
        plantilla,
        autoridad=autoridad,
        filtros=json.dumps(filtros),
        titulo=titulo,
        mostrar_filtro_autoridad_clave=mostrar_filtro_autoridad_clave,
        estatus="A",
    )


@edictos.route("/edictos/inactivos")
@permission_required(MODULO, Permiso.ADMINISTRAR)
def list_inactive():
    """Listado de Edictos inactivos"""
    return render_template(
        "edictos/list.jinja2",
        filtros=json.dumps({"estatus": "B"}),
        titulo="Edictos inactivos",
        estatus="B",
    )


@edictos.route("/edictos/descargar", methods=["GET"])
@permission_required(MODULO, Permiso.ADMINISTRAR)
def download():
    """Descargar archivo desde Google Cloud Storage"""
    url = request.args.get("url")
    try:
        # Obtener nombre del blob
        blob_name = get_blob_name_from_url(url)
        # Obtener tipo de media
        media_type = get_media_type_from_filename(blob_name)
        # Obtener archivo
        archivo = get_file_from_gcs(current_app.config["CLOUD_STORAGE_DEPOSITO_EDICTOS"], blob_name)
    except MyAnyError as error:
        flash(str(error), "warning")
        return redirect(url_for("edictos.list_active"))
    # Entregar archivo
    return current_app.response_class(archivo, mimetype=media_type)


@edictos.route("/edictos/<int:edicto_id>")
def detail(edicto_id):
    """Detalle de un Edicto"""
    edicto = Edicto.query.get_or_404(edicto_id)
    return render_template("edictos/detail.jinja2", edicto=edicto)


@edictos.route("/edictos/nuevo", methods=["GET", "POST"])
@permission_required(MODULO, Permiso.CREAR)
def new():
    """Subir Edicto para una notaria"""
    # Definir la fecha del edicto, simpre es HOY, se usa para GCS
    hoy_date = datetime.today().date()

    # Validar autoridad
    autoridad = current_user.autoridad
    if autoridad.estatus != "A":
        flash("La Notaria no es activa.", "warning")
        return redirect(url_for("edictos.list_active"))
    if not autoridad.distrito.es_distrito_judicial:
        flash("El Distrito no es jurisdiccional.", "warning")
        return redirect(url_for("edictos.list_active"))
    if not autoridad.es_notaria:
        flash("La Notarias no tiene en verdadero el boleano que lo define como notaria.", "warning")
        return redirect(url_for("edictos.list_active"))
    if autoridad.directorio_edictos is None or autoridad.directorio_edictos == "":
        flash("La Notaria no tiene directorio para edictos.", "warning")
        return redirect(url_for("edictos.list_active"))

    # Si viene el formulario
    form = EdictoNewForm(CombinedMultiDict((request.files, request.form)))
    if form.validate_on_submit():
        es_valido = True

        # Validar la descripcion
        descripcion = safe_string(form.descripcion.data, max_len=64, save_enie=True)
        if descripcion == "":
            flash("La descripción es incorrecta.", "warning")
            es_valido = False

        # Validad que acuse_num se entero
        try:
            acuse_num = int(form.acuse_num.data)
        except ValueError:
            flash("Especificar una cantidad publicaciones válida.", "warning")
            es_valido = False

        # Validar que el acuse_num sea entre 1 y 5
        if not 1 <= acuse_num <= 5:
            flash("Especificar una cantidad de publicaciones entre 1 y 5.", "warning")
            es_valido = False

        # Si el usuario seleccionó la opcion de 1 en el radiobutton
        if acuse_num == 1:
            # Establecer la fecha de hoy en el primer campo de fecha
            form.fecha_acuse_1.data = hoy_date.strftime("%Y-%m-%d")

        # Validar las fechas de los acuses que se ingresan manualmente por el usuario
        limite_futuro_date = hoy_date + timedelta(days=30)
        fechas_acuses_list = []
        for i in range(1, acuse_num + 1):
            # Asegura de que 'i' esté correctamente definido dentro del bucle 'for'
            fecha_acuse_str = getattr(form, f"fecha_acuse_{i}").data
            # Verifica si fecha_acuse_str es None y maneja el caso adecuadamente
            if fecha_acuse_str is None:
                # Asignar la fecha actual como valor predeterminado
                fecha_acuse_str = hoy_date.strftime("%Y-%m-%d")
            # Asegura que la fecha_acuse_str sea una cadena de texto antes de pasarla a strptime()
            if isinstance(fecha_acuse_str, date):
                # Si ya es un objeto de fecha, no necesitas convertirlo
                fecha_acuse = fecha_acuse_str
            else:
                # Convierte la cadena de texto a un objeto de fecha
                fecha_acuse = datetime.strptime(fecha_acuse_str, "%Y-%m-%d").date()
            # Agrega la variable fecha_acuse a la lista fechas_acuses_list.
            fechas_acuses_list.append(fecha_acuse)

        for fecha_acuse in fechas_acuses_list:
            if fecha_acuse is None:  # Validar que NO sea nulo
                flash("Falta una de las fechas de publicación.", "warning")
                es_valido = False
                break
            if fecha_acuse < hoy_date:  # Validar que NO sea del pasado
                flash("La fecha de publicación no puede ser del pasado.", "warning")
                es_valido = False
                break
            if fecha_acuse > limite_futuro_date:  # Validar que NO sea posterior al limite permitido
                flash("Solo se permiten fechas de publicación hasta un mes en el futuro.", "warning")
                es_valido = False

        # Inicializar la liberia Google Cloud Storage con el directorio base, la fecha, las extensiones permitidas y los meses como palabras
        gcstorage = GoogleCloudStorage(
            base_directory=autoridad.directorio_edictos,
            upload_date=hoy_date,
            allowed_extensions=["pdf"],
            month_in_word=True,
            bucket_name=current_app.config["CLOUD_STORAGE_DEPOSITO_EDICTOS"],
        )

        # Validar archivo
        archivo = request.files["archivo"]
        try:
            gcstorage.set_content_type(archivo.filename)
        except (MyFilenameError, MyNotAllowedExtensionError, MyUnknownExtensionError):
            flash("Tipo de archivo no permitido o desconocido.", "warning")
            es_valido = False

        # Si NO es válido, entonces se vuelve a mostrar el formulario
        if es_valido is False:
            return render_template("edictos/new.jinja2", form=form)

        # Insertar el registro en la base de datos
        edicto = Edicto(
            autoridad=autoridad,
            fecha=hoy_date,
            acuse_num=acuse_num,
            descripcion=descripcion,
            numero_publicacion="1",  # Primera publicación siempre es "1"
        )
        edicto.save()

        # Insertar los acuses solo si la validación es exitosa
        for fecha_acuse in fechas_acuses_list:

            # Verificar que la fecha del acuse no sea la fecha de hoy
            if fecha_acuse != hoy_date:
                acuse = EdictoAcuse(
                    edicto_id=edicto.id,
                    fecha=fecha_acuse,
                )
                acuse.save()

        # Subir a Google Cloud Storage
        es_exitoso = True
        try:
            gcstorage.set_filename(hashed_id=edicto.encode_id(), description=descripcion)
            gcstorage.upload(archivo.stream.read())
        except (MyFilenameError, MyNotAllowedExtensionError, MyUnknownExtensionError):
            flash("Tipo de archivo no permitido o desconocido.", "warning")
            es_exitoso = False
        except Exception as error:
            flash(f"Error inesperado: {str(error)}", "danger")
            es_exitoso = False

        # Si se sube con exito, actualizar el registro del edicto con el archivo y la URL y mostrar el detalle
        if es_exitoso:
            edicto.archivo = gcstorage.filename
            edicto.url = gcstorage.url
            edicto.save()
            bitacora = Bitacora(
                modulo=Modulo.query.filter_by(nombre=MODULO).first(),
                usuario=current_user,
                descripcion=safe_message(
                    f"Portal de Notarías nuevo edicto de {edicto.autoridad.clave} sobre {edicto.descripcion[:16]}"
                ),
                url=url_for("edictos.detail", edicto_id=edicto.id),
            )
            bitacora.save()
            flash(bitacora.descripcion, "success")
            return redirect(bitacora.url)

        # Como no se subio con exito, se cambia el estatus a "B"
        edicto.estatus = "B"
        edicto.save()

    # Prellenado de los campos
    form.distrito.data = autoridad.distrito.nombre
    form.autoridad.data = autoridad.descripcion
    hoy_date = datetime.today().date()
    for i in range(1, 6):
        setattr(form, f"fecha_acuse_{i}", hoy_date.strftime("%Y-%m-%d"))
    return render_template("edictos/new.jinja2", form=form)


@edictos.route("/edictos/edicion/<int:edicto_id>", methods=["GET", "POST"])
@permission_required(MODULO, Permiso.MODIFICAR)
def edit(edicto_id):
    """Editar Edicto"""
    edicto = Edicto.query.get_or_404(edicto_id)

    # Validar autoridad
    autoridad = edicto.autoridad
    if autoridad.estatus != "A":
        flash("La Notaría no esta activa.", "warning")
        return redirect(url_for("edictos.list_active"))
    if not autoridad.distrito.es_distrito_judicial:
        flash("El Distrito no es jurisdiccional.", "warning")
        return redirect(url_for("edictos.list_active"))
    if not autoridad.es_notaria:
        flash("La Notaria no tiene en verdadero el boleano que la define como notaria.", "warning")
        return redirect(url_for("edictos.list_active"))
    if autoridad.directorio_edictos is None or autoridad.directorio_edictos == "":
        flash("La Notaria no tiene directorio para edictos.", "warning")
        return redirect(url_for("edictos.list_active"))

    # Si NO es administrador
    if not (current_user.can_admin(MODULO)):
        # Validar que le pertenezca
        if current_user.autoridad_id != edicto.autoridad_id:
            flash("No puede editar registros ajenos.", "warning")
            return redirect(url_for("edictos.list_active"))
        # Asegurar que edicto.creado tenga zona horaria
        if edicto.creado.tzinfo is None:
            edicto_creado = local_tz.localize(edicto.creado)  # Agregar la zona horaria si no la tiene
        else:
            edicto_creado = edicto.creado.astimezone(local_tz)  # Convertir a la zona horaria local si ya tiene una zona horaria
        # Si fue creado hace más de LIMITE_DIAS_EDITAR
        if edicto_creado < datetime.now(local_tz) - timedelta(days=LIMITE_DIAS_EDITAR):
            flash(f"Ya no puede editar porque fue creado hace más de {LIMITE_DIAS_EDITAR} día.", "warning")
            return redirect(url_for("edictos.detail", edicto_id=edicto.id))

    # Obtener los acuses asociados al edicto
    acuses = EdictoAcuse.query.filter_by(edicto_id=edicto.id).order_by(EdictoAcuse.fecha).all()

    # Si viene el formulario
    form = EdictoEditForm()
    if form.validate_on_submit():
        es_valido = True

        # Validar la descripción
        descripcion = safe_string(form.descripcion.data, save_enie=True)
        if descripcion == "":
            flash("La descripción es incorrecta.", "warning")
            es_valido = False

        # Guardar cambios en el edicto
        edicto.descripcion = descripcion
        edicto.save()

        # Actualizar los acuses
        for i, acuse in enumerate(acuses):
            if i + 2 <= 5:
                fecha_acuse_field = getattr(form, f"fecha_acuse_{i + 2}")
                fecha_acuse = fecha_acuse_field.data
                if fecha_acuse is None:
                    flash("Falta una de las fechas de publicación.", "warning")
                    es_valido = False
                    break
                if fecha_acuse < datetime.today().date():
                    flash("La fecha de publicación no puede ser del pasado.", "warning")
                    es_valido = False
                    break
                acuse.fecha = fecha_acuse
                acuse.save()

        if not es_valido:
            return render_template("edictos/edit.jinja2", form=form, edicto=edicto)
        # Registrar en la bitácora
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(
                f"Portal de Notarías editar edicto de {edicto.autoridad.clave} sobre {edicto.descripcion[:16]}"
            ),
            url=url_for("edictos.detail", edicto_id=edicto.id),
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)

    # Pre-llenar el formulario con los datos del edicto y los acuses
    form.distrito.data = autoridad.distrito.nombre
    form.autoridad.data = autoridad.descripcion
    form.descripcion.data = edicto.descripcion
    for i, acuse in enumerate(acuses):
        if i + 2 <= 5:  # Asegurarse de que no exceda el número de campos de fecha en el formulario
            fecha_acuse_field = getattr(form, f"fecha_acuse_{i + 2}")
            fecha_acuse_field.data = acuse.fecha
    return render_template("edictos/edit.jinja2", form=form, edicto=edicto)


@edictos.route("/edictos/eliminar/<int:edicto_id>")
@permission_required(MODULO, Permiso.CREAR)
def delete(edicto_id):
    """Eliminar Edicto"""
    edicto = Edicto.query.get_or_404(edicto_id)
    detalle_url = url_for("edictos.detail", edicto_id=edicto.id)
    # Validar que se pueda eliminar
    if edicto.estatus == "B":
        flash("El edicto ya está eliminado.", "warning")
        return redirect(detalle_url)

    # Si es administrador, puede eliminar
    if current_user.can_admin(MODULO):
        # Eliminar los edictos_acuses asociados
        EdictoAcuse.query.filter_by(edicto_id=edicto.id).update({"estatus": "B"}, synchronize_session=False)
        edicto.delete()
        # Eliminar los edictos_acuses asociados
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(f"Eliminado Edicto {edicto.descripcion}"),
            url=detalle_url,
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)

    # Si NO le pertenece, mostrar mensaje y redirigir
    if current_user.autoridad_id != edicto.autoridad_id:
        flash("No puede eliminar porque no le pertenece.", "warning")
        return redirect(detalle_url)

    # Si fue creado hace más de LIMITE_DIAS_EDITAR
    if edicto.creado >= datetime.now(local_tz) - timedelta(days=LIMITE_DIAS_ELIMINAR):
        # Eliminar los edictos_acuses asociados
        EdictoAcuse.query.filter_by(edicto_id=edicto.id).update({"estatus": "B"}, synchronize_session=False)
        edicto.delete()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=safe_message(
                f"Portal de Notarías eliminar edicto de {edicto.autoridad.clave} sobre {edicto.descripcion[:16]}"
            ),
            url=detalle_url,
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)
    # No se puede eliminar
    flash(f"Ya no puede eliminar porque fue creado hace más de {LIMITE_DIAS_ELIMINAR} día.", "warning")
    return redirect(detalle_url)


@edictos.route("/edictos/recuperar/<int:edicto_id>")
@permission_required(MODULO, Permiso.CREAR)
def recover(edicto_id):
    """Recuperar Edicto"""
    edicto = Edicto.query.get_or_404(edicto_id)
    detalle_url = url_for("edictos.detail", edicto_id=edicto.id)

    # Validar que se pueda recuperar
    if edicto.estatus == "A":
        flash("No puede eliminar este Edicto porque ya está activo.", "success")
        return redirect(detalle_url)

    # Evitar que se recupere si ya existe una con el mismo id
    if Edicto.query.filter_by(autoridad=current_user.autoridad, id=edicto.id, estatus="A").first():
        flash("No puede recuperar este Edicto porque ya existe uno activo con el mismo ID", "warning")
        return redirect(detalle_url)

    # Definir la descripción para la bitácora
    descripcion = safe_message(
        f"Portal de Notarías recuperar edicto de {edicto.autoridad.clave} sobre {edicto.descripcion[:16]}"
    )

    # Si es administrador, puede recuperar
    if current_user.can_admin(MODULO):
        # Recuperar los edictos_acuses asociados al edicto_id y cambiar su estatus a "A"
        EdictoAcuse.query.filter_by(edicto_id=edicto.id).update({EdictoAcuse.estatus: "A"})
        edicto.recover()
        # Registrar en la bitácora
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=descripcion,
            url=detalle_url,
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)

    # Si NO le pertenece, mostrar mensaje y redirigir
    if current_user.autoridad_id != edicto.autoridad_id:
        flash("No puede recuperar porque no le pertenece.", "warning")
        return redirect(detalle_url)

    # Si fue creado hace menos del límite de días, puede recuperar
    if edicto.creado >= datetime.now(local_tz) - timedelta(days=LIMITE_DIAS_RECUPERAR):
        # Recuperar los edictos_acuses asociados al edicto_id y cambiar su estatus a "A"
        EdictoAcuse.query.filter_by(edicto_id=edicto.id).update({EdictoAcuse.estatus: "A"})
        edicto.recover()
        bitacora = Bitacora(
            modulo=Modulo.query.filter_by(nombre=MODULO).first(),
            usuario=current_user,
            descripcion=descripcion,
            url=detalle_url,
        )
        bitacora.save()
        flash(bitacora.descripcion, "success")
        return redirect(bitacora.url)

    # No se puede recuperar
    flash(f"No se puede recuperar porque fue creado hace más de {LIMITE_DIAS_RECUPERAR} día.", "warning")
    return redirect(detalle_url)


@edictos.route("/edictos/ver_archivo_pdf/<int:edicto_id>")
def view_file_pdf(edicto_id):
    """Ver archivo PDF de Edicto para insertarlo en un iframe en el detalle"""

    # Consultar
    edicto = Edicto.query.get_or_404(edicto_id)

    # Obtener el contenido del archivo
    try:
        archivo = get_file_from_gcs(
            bucket_name=current_app.config["CLOUD_STORAGE_DEPOSITO_EDICTOS"],
            blob_name=get_blob_name_from_url(edicto.url),
        )
    except (MyBucketNotFoundError, MyFileNotFoundError, MyNotValidParamError) as error:
        raise NotFound("No se encontró el archivo.") from error

    # Entregar el archivo
    response = make_response(archivo)
    response.headers["Content-Type"] = "application/pdf"
    return response


@edictos.route("/edictos/tablero")
@permission_required(MODULO, Permiso.VER)
def dashboard():
    """Tablero de Edictos"""

    # Por defecto
    autoridad = None
    titulo = "Tablero de Edictos"

    # Si la autoridad del usuario es jurisdiccional o es notaria, se impone
    if current_user.autoridad.es_jurisdiccional or current_user.autoridad.es_notaria:
        autoridad = current_user.autoridad
        titulo = f"Tablero de Edictos de {autoridad.clave}"

    # Si aun no hay autoridad y viene autoridad_id o autoridad_clave en la URL
    if autoridad is None:
        try:
            if "autoridad_id" in request.args:
                autoridad = Autoridad.query.get(int(request.args.get("autoridad_id")))
            elif "autoridad_clave" in request.args:
                autoridad = Autoridad.query.filter_by(clave=safe_clave(request.args.get("autoridad_clave"))).first()
            if autoridad:
                titulo = f"{titulo} de {autoridad.clave}"
        except (TypeError, ValueError):
            pass

    # Si viene fecha_desde en la URL, validar
    fecha_desde = None
    try:
        if "fecha_desde" in request.args:
            fecha_desde = datetime.strptime(request.args.get("fecha_desde"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        pass

    # Si viene fecha_hasta en la URL, validar
    fecha_hasta = None
    try:
        if "fecha_hasta" in request.args:
            fecha_hasta = datetime.strptime(request.args.get("fecha_hasta"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        pass

    # Si fecha_desde y fecha_hasta están invertidas, corregir
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde

    # Si viene fecha_desde y falta fecha_hasta, calcular fecha_hasta sumando fecha_desde y DASHBOARD_CANTIDAD_DIAS
    if fecha_desde and not fecha_hasta:
        fecha_hasta = fecha_desde + timedelta(days=DASHBOARD_CANTIDAD_DIAS)

    # Si viene fecha_hasta y falta fecha_desde, calcular fecha_desde restando fecha_hasta y DASHBOARD_CANTIDAD_DIAS
    if fecha_hasta and not fecha_desde:
        fecha_desde = fecha_hasta - timedelta(days=DASHBOARD_CANTIDAD_DIAS)

    # Si no viene fecha_desde ni tampoco fecha_hasta, pero viene cantidad_dias en la URL, calcular fecha_desde y fecha_hasta
    if not fecha_desde and not fecha_hasta:
        cantidad_dias = DASHBOARD_CANTIDAD_DIAS  # Por defecto
        try:
            if "cantidad_dias" in request.args:
                cantidad_dias = int(request.args.get("cantidad_dias"))
        except (TypeError, ValueError):
            cantidad_dias = DASHBOARD_CANTIDAD_DIAS
        fecha_desde = datetime.now().date() - timedelta(days=cantidad_dias)
        fecha_hasta = datetime.now().date()

    # Definir el titulo
    titulo = f"{titulo} desde {fecha_desde.strftime('%Y-%m-%d')} hasta {fecha_hasta.strftime('%Y-%m-%d')}"

    # Si no hay autoridad
    if autoridad is None:
        return render_template(
            "edictos/dashboard.jinja2",
            autoridad=None,
            filtros=json.dumps(
                {
                    "fecha_desde": fecha_desde.strftime("%Y-%m-%d"),
                    "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d"),
                    "estatus": "A",
                }
            ),
            titulo=titulo,
        )

    # Entregar dashboard.jinja2
    return render_template(
        "edictos/dashboard.jinja2",
        autoridad=autoridad,
        filtros=json.dumps(
            {
                "autoridad_id": autoridad.id,
                "fecha_desde": fecha_desde.strftime("%Y-%m-%d"),
                "fecha_hasta": fecha_hasta.strftime("%Y-%m-%d"),
                "estatus": "A",
            }
        ),
        titulo=titulo,
    )
