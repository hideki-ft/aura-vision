// Pose en el navegador: YOLOX-tiny + RTMPose con ONNX Runtime Web (mismo pre/posproceso que rtmlib).
// Nada sale del navegador: los cuadros de la cámara se procesan en el propio dispositivo.
const ort = globalThis.ort;

export class EstimadorPoseWeb {
  static async crear(base, modeloPose = "rtmpose_s", alProgreso = () => {}, usarGPU = true) {
    const e = new EstimadorPoseWeb();
    ort.env.wasm.numThreads = globalThis.crossOriginIsolated ? Math.min(4, navigator.hardwareConcurrency || 2) : 1;
    const proveedores = [];
    if (usarGPU && navigator.gpu && (await navigator.gpu.requestAdapter().catch(() => null))) proveedores.push("webgpu");
    proveedores.push("wasm");
    const cargar = async (nombre) => {
      alProgreso(`Descargando ${nombre}…`);
      const r = await fetch(`${base}${nombre}.onnx`);
      if (!r.ok) throw new Error(`No se pudo descargar ${nombre} (${r.status})`);
      const buf = new Uint8Array(await r.arrayBuffer());
      for (const p of proveedores) {
        try { alProgreso(`Preparando ${nombre} (${p})…`); return [await ort.InferenceSession.create(buf, { executionProviders: [p], graphOptimizationLevel: "all" }), p]; }
        catch (err) { console.warn(`${nombre}: ${p} no disponible`, err); }
      }
      throw new Error(`No se pudo crear la sesión de ${nombre}`);
    };
    [e.det, e.proveedor] = await cargar("yolox_tiny");
    [e.pose] = await cargar(modeloPose);
    e.modeloPose = modeloPose;
    e.cvDet = new OffscreenCanvas(416, 416); e.ctxDet = e.cvDet.getContext("2d", { willReadFrequently: true });
    e.cvPose = new OffscreenCanvas(192, 256); e.ctxPose = e.cvPose.getContext("2d", { willReadFrequently: true });
    alProgreso("Calentando los modelos (la primera vez puede tardar unos segundos)…");
    const prueba = new OffscreenCanvas(320, 240);                   // primera inferencia: compila/prepara
    await e.detectar(prueba, 320, 240); await e.estimar(prueba, [[100, 20, 220, 230]]);
    return e;
  }

  // Cajas [x1,y1,x2,y2] de personas. fuente: <video>, <canvas> o ImageBitmap de tamaño ancho×alto.
  async detectar(fuente, ancho, alto) {
    const S = 416, ratio = Math.min(S / alto, S / ancho), c = this.ctxDet;
    c.fillStyle = "rgb(114,114,114)"; c.fillRect(0, 0, S, S);
    c.drawImage(fuente, 0, 0, Math.floor(ancho * ratio), Math.floor(alto * ratio));
    const d = c.getImageData(0, 0, S, S).data, n = S * S, x = new Float32Array(3 * n);
    for (let i = 0; i < n; i++) { x[i] = d[4 * i + 2]; x[n + i] = d[4 * i + 1]; x[2 * n + i] = d[4 * i]; }   // BGR, 0-255
    const out = await this.det.run({ [this.det.inputNames[0]]: new ort.Tensor("float32", x, [1, 3, S, S]) });
    const dets = out[this.det.outputNames[0]], lab = out[this.det.outputNames[1]];
    const cajas = [];
    for (let i = 0; i < dets.dims[1]; i++) {
      const s = dets.data[5 * i + 4];
      if (s > 0.3 && (!lab || Number(lab.data[i]) === 0))
        cajas.push([0, 1, 2, 3].map((k) => dets.data[5 * i + k] / ratio));
    }
    return cajas;
  }

  // Puntos clave (17 × [x, y]) y confianzas para cada caja, en un solo lote.
  async estimar(fuente, cajas) {
    if (!cajas.length) return [];
    const W = 192, H = 256, n = W * H, lote = new Float32Array(cajas.length * 3 * n), geo = [];
    const media = [123.675, 116.28, 103.53], dt = [58.395, 57.12, 57.375];
    cajas.forEach((b, j) => {
      const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
      let sw = (b[2] - b[0]) * 1.25, sh = (b[3] - b[1]) * 1.25;
      if (sw > sh * W / H) sh = sw * H / W; else sw = sh * W / H;
      const c = this.ctxPose; c.clearRect(0, 0, W, H);
      c.drawImage(fuente, cx - sw / 2, cy - sh / 2, sw, sh, 0, 0, W, H);
      const d = c.getImageData(0, 0, W, H).data, o = j * 3 * n;
      for (let i = 0; i < n; i++) {                       // BGR normalizado como en rtmlib
        lote[o + i] = (d[4 * i + 2] - media[0]) / dt[0];
        lote[o + n + i] = (d[4 * i + 1] - media[1]) / dt[1];
        lote[o + 2 * n + i] = (d[4 * i] - media[2]) / dt[2];
      }
      geo.push([cx, cy, sw, sh]);
    });
    const out = await this.pose.run({ [this.pose.inputNames[0]]: new ort.Tensor("float32", lote, [cajas.length, 3, H, W]) });
    const sx = out[this.pose.outputNames[0]], sy = out[this.pose.outputNames[1]];
    const Wx = sx.dims[2], Wy = sy.dims[2];
    return geo.map(([cx, cy, sw, sh], j) => {
      const kps = [], scores = [];
      for (let k = 0; k < 17; k++) {
        let bx = 0, mx = -Infinity, by = 0, my = -Infinity;
        const ox = (j * 17 + k) * Wx, oy = (j * 17 + k) * Wy;
        for (let i = 0; i < Wx; i++) if (sx.data[ox + i] > mx) { mx = sx.data[ox + i]; bx = i; }
        for (let i = 0; i < Wy; i++) if (sy.data[oy + i] > my) { my = sy.data[oy + i]; by = i; }
        const s = (mx + my) / 2;
        const lx = s > 0 ? bx / 2 : -1, ly = s > 0 ? by / 2 : -1;
        kps.push([lx / W * sw + cx - sw / 2, ly / H * sh + cy - sh / 2]); scores.push(s);
      }
      return { kps, scores };
    });
  }
}
