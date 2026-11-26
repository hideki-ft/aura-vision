"""Seguimiento ByteTrack ligero: IDs estables."""
import numpy as np

from aura.vision.seguimiento import ByteTrackLigero, iou_matriz


def test_iou():
    m = iou_matriz([[0, 0, 10, 10]], [[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]])
    assert np.allclose(m, [[1.0, 1 / 3, 0.0]])


def test_dos_personas_mantienen_su_id():
    tr = ByteTrackLigero(cuadros_para_confirmar=2)
    ids = []
    for i in range(60):
        a = [100 + 3 * i, 100, 160 + 3 * i, 300]
        b = [500 - 3 * i, 120, 560 - 3 * i, 330]
        orden = [a, b] if i % 2 else [b, a]                   # el orden de las detecciones cambia
        pistas = tr.actualizar(orden, [0.9, 0.9], i / 30)
        ids.append({p.id: round(float(p.caja[0])) for p in pistas})
    assert set(ids[-1]) == set(ids[5])
    assert len({k for d in ids for k in d}) == 2


def test_oclusion_breve_conserva_el_id():
    tr = ByteTrackLigero()
    for i in range(20):
        p = tr.actualizar([[100 + 2 * i, 100, 160 + 2 * i, 300]], [0.9], i / 30)
    id0 = p[0].id
    for i in range(20, 35):                                   # 0.5 s sin detección
        tr.actualizar(np.zeros((0, 4)), [], i / 30)
    p = tr.actualizar([[170, 100, 230, 300]], [0.9], 35 / 30)
    assert p and p[0].id == id0


def test_caida_no_cambia_el_id():
    """Al caer, la caja pasa de vertical a horizontal en < 0.5 s: el ID debe mantenerse."""
    from aura.sintetico import Escena, a_pixeles
    T, K, C, B = a_pixeles(Escena().de_pie(2).caer().tumbado(2))
    tr = ByteTrackLigero()
    ids = set()
    for i in range(len(T)):
        ids |= {p.id for p in tr.actualizar([B[i]], [0.9], T[i])}
    assert len(ids) == 1
