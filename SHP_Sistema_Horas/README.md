# SHP — Sistema de Horas Personales (prototipo web UAM)

Aplicación web Flask con SQLite para registrar actividades y evidencias, configurar metas semestrales, validar registros, consultar historial y exportar reportes PDF.

## Requisitos
- Python 3.10 o superior
- pip

## Instalación en Windows
1. Extrae el ZIP.
2. Abre una terminal dentro de la carpeta `SHP_Sistema_Horas`.
3. Crea un entorno virtual:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
4. Instala las dependencias:
   ```powershell
   pip install -r requirements.txt
   ```
5. Ejecuta la aplicación:
   ```powershell
   python app.py
   ```
6. Abre `http://127.0.0.1:5000`.

## Pantallas de entrada
- Inicio de sesión de demostración.
- Registro de actividad: actividad del catálogo, fecha, horas, descripción y evidencia PDF/JPG/PNG.
- Configuración de metas semestrales por categoría.
- Administración del catálogo oficial (rol Coordinador).
- Validación de actividades con observaciones (rol Coordinador).

## Pantallas de salida
- Panel con indicadores de registros, horas validadas y pendientes.
- Progreso por categoría comparado con metas semestrales.
- Historial con filtros por mes, estado y categoría.
- Reporte PDF descargable con registros y horas validadas.

## Datos y archivos
- `shp.db` se crea automáticamente al iniciar y almacena los datos en SQLite.
- `uploads/` contiene los archivos de evidencia subidos.
- `SHP_SECRET_KEY` permite configurar una clave de sesión segura.

## Importante antes de producción
El acceso incluido es de demostración: deja probar los roles y pantallas, pero NO autentica realmente mediante Google Workspace UAM. Para producción se debe implementar OAuth institucional, validar el dominio de correo en el servidor, restringir la asignación de roles (un usuario no debe poder elegir Coordinador), configurar una `SHP_SECRET_KEY` fuerte, límites de tamaño de archivo, protección CSRF, HTTPS, copias de seguridad y políticas de privacidad. La selección de rol del formulario solo sirve para probar la interfaz local.
