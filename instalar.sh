#!/bin/bash
# Instala o actualiza el comando `progresa`.
# La rutina declara este repositorio como fuente: lo clona al empezar cada
# corrida, así que copiar el script de aquí siempre da la última versión.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -c "import openpyxl" 2>/dev/null || pip install -q openpyxl >/dev/null 2>&1 || true

mkdir -p /opt/progresa
cp "$DIR/rutina_progresa.py" /opt/progresa/rutina_progresa.py

# pip y python3 pueden ser versiones distintas en la nube: el envoltorio
# apunta python3 a donde pip dejó openpyxl.
cat > /usr/local/bin/progresa <<'WRAP'
#!/bin/bash
PYTHONPATH="$(pip show openpyxl 2>/dev/null | sed -n 's/^Location: //p')" exec python3 /opt/progresa/rutina_progresa.py "$@"
WRAP
chmod +x /usr/local/bin/progresa

echo "progresa instalado (versión $(sha256sum /opt/progresa/rutina_progresa.py | cut -c1-12))"
