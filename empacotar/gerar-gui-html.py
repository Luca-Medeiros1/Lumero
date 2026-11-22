"""Gera o lumero_gui.html a partir do modelo, com o ícone embutido (rode depois de mudar o modelo)."""
import base64, os
raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
icone = base64.b64encode(open(os.path.join(raiz, "assets", "lumero.svg"), "rb").read()).decode()
modelo = open(os.path.join(raiz, "empacotar", "gui-modelo.html"), encoding="utf-8").read()
open(os.path.join(raiz, "lumero_gui.html"), "w", encoding="utf-8").write(modelo.replace("__ICONE__", icone))
print("lumero_gui.html gerado")
