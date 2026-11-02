#!/bin/bash
# Instala o actualiza el comando `progresa` desde este repositorio.
# La rutina lo corre al empezar cada vez, así que siempre usa la última versión.
set -e
BASE="https://raw.githubusercontent.com/tellocoach/kit-progresa/main"

python3 -c "import openpyxl" 2>/dev/null || pip install -q openpyxl >/dev/null 2>&1 || true

mkdir -p /opt/progresa
curl -fsSL "$BASE/rutina_progresa.py" -o /opt/progresa/rutina_progresa.py

# pip y python3 pueden ser versiones distintas en la nube: el envoltorio
# apunta python3 a donde pip dejó openpyxl.
cat > /usr/local/bin/progresa <<'WRAP'
#!/bin/bash
PYTHONPATH="$(pip show openpyxl 2>/dev/null | sed -n 's/^Location: //p')" exec python3 /opt/progresa/rutina_progresa.py "$@"
WRAP
chmod +x /usr/local/bin/progresa

echo "progresa instalado (versión $(sha256sum /opt/progresa/rutina_progresa.py | cut -c1-12))"
