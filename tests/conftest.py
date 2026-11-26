"""Permite importar el paquete ``aura`` desde la raíz del repositorio."""
import os
import sys

import matplotlib

matplotlib.use("Agg")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
