/**
 * ShaderAuroraVeilCanvas (ESM)
 * Dual-Engine Atmospheric Aurora Veil Backdrop:
 * - Engine 1: Pure WebGL 1.0/2.0 with GLSL procedural noise ribbons and alpha blending
 * - Engine 2: High-performance 2D Canvas Fluid Fallback (activates seamlessly if WebGL is restricted/sandboxed)
 * - Layer 3: Ambient CSS drift on .hero-box
 */

const vertexShaderSource = `
attribute vec2 a_position;
void main() {
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const fragmentShaderSource = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

uniform vec2 u_resolution;
uniform float u_time;
uniform vec2 u_pointer;
uniform float u_intensity;

float saturate(float value) {
  return clamp(value, 0.0, 1.0);
}

mat2 rotate2d(float angle) {
  float s = sin(angle);
  float c = cos(angle);
  return mat2(c, -s, s, c);
}

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + vec2(45.32));
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);

  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));

  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
  float value = 0.0;
  float amplitude = 0.5;
  for (int i = 0; i < 4; i++) {
    value += amplitude * noise(p);
    p = rotate2d(0.72) * p * 2.03 + vec2(4.17);
    amplitude *= 0.5;
  }
  return value;
}

vec4 shaderColor(vec2 uv, vec2 p, float t, vec2 pointer, float intensity) {
  vec2 q = p;
  q.x += sin(q.y * 2.2 + t * 0.22) * 0.32;
  q.y += cos(q.x * 1.9 - t * 0.18) * 0.26;

  // Primary undulating Mint Aurora Ribbon (#59D8BE)
  float veilA = smoothstep(0.75, 0.02, abs(q.y + sin(q.x * 1.5 + t * 0.25) * 0.42));
  
  // Secondary flowing Rose Ember Ribbon (#EC5C13)
  float veilB = smoothstep(0.68, 0.02, abs(q.y * 0.85 - cos(q.x * 2.2 - t * 0.20) * 0.34));

  // Tertiary Golden Amber Accent Ribbon (#F0D46A)
  float veilC = smoothstep(0.62, 0.02, abs(q.y * 1.20 + sin(q.x * 2.6 + t * 0.28) * 0.28));

  // Organic micro-grain texture
  float grain = fbm(q * 3.2 + vec2(t * 0.05));

  vec3 mint = vec3(0.35, 0.86, 0.75);      // #59D8BE
  vec3 ember = vec3(0.93, 0.38, 0.18);     // #EC5C13
  vec3 gold = vec3(0.96, 0.80, 0.38);      // #F0D46A

  float alphaA = veilA * 0.45;
  float alphaB = veilB * 0.36;
  float alphaC = veilC * 0.28;
  float totalAlpha = clamp(alphaA + alphaB + alphaC, 0.0, 0.75) * intensity;

  vec3 rgb = (mint * alphaA + ember * alphaB + gold * alphaC) / max(totalAlpha, 0.001);
  rgb += vec3((grain - 0.5) * 0.035);

  // Subtle interactive pointer flare
  float pointerDist = length(p - pointer);
  float pointerGlow = smoothstep(0.45, 0.0, pointerDist) * 0.30;
  totalAlpha = clamp(totalAlpha + pointerGlow, 0.0, 0.85);
  rgb = mix(rgb, mint, pointerGlow);

  return vec4(clamp(rgb, 0.0, 1.0), totalAlpha);
}

void main() {
  vec2 uv = gl_FragCoord.xy / max(u_resolution.xy, vec2(1.0));
  vec2 p = (gl_FragCoord.xy * 2.0 - u_resolution.xy) / max(min(u_resolution.x, u_resolution.y), 1.0);
  vec2 pointer = u_pointer * 2.0 - vec2(1.0);
  pointer.x *= u_resolution.x / max(u_resolution.y, 1.0);

  gl_FragColor = shaderColor(uv, p, u_time, pointer, u_intensity);
}
`;

export class ShaderAuroraVeilEngine {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.container = canvas.parentElement;
    this.gl = null;
    this.program = null;
    this.buffer = null;
    this.ctx2D = null;
    this.use2DFallback = false;
    this.frameId = 0;
    this.disposed = false;
    this.visible = true;
    this.pointer = { x: 0.5, y: 0.5, active: false };
    this.intensity = options.intensity !== undefined ? options.intensity : 1.0;
    this.animate = options.animate !== undefined ? options.animate : true;

    this.init();
  }

  init() {
    let gl = null;
    try {
      gl =
        this.canvas.getContext("webgl2", { alpha: true, antialias: false, depth: false }) ||
        this.canvas.getContext("webgl", { alpha: true, antialias: false, depth: false }) ||
        this.canvas.getContext("experimental-webgl", { alpha: true, antialias: false, depth: false });
    } catch (_) {
      gl = null;
    }

    if (!gl) {
      console.info("WebGL unavailable; launching 2D fluid fallback engine.");
      this.init2DFallback();
      return;
    }

    const program = this.createProgram(gl, vertexShaderSource, fragmentShaderSource);
    if (!program) {
      console.warn("Shader program compile failed; launching 2D fluid fallback engine.");
      this.init2DFallback();
      return;
    }

    const buffer = gl.createBuffer();
    if (!buffer) {
      this.init2DFallback();
      return;
    }

    this.gl = gl;
    this.program = program;
    this.buffer = buffer;

    // Enable transparent alpha blending over hero container
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const positionLoc = gl.getAttribLocation(program, "a_position");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW
    );
    gl.useProgram(program);
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    this.attachEvents();
    this.start();
  }

  init2DFallback() {
    this.use2DFallback = true;

    // If canvas already attempted WebGL, calling getContext('2d') on the same element will return null.
    // Replace with a fresh canvas to guarantee clean 2D context acquisition.
    try {
      let ctx = this.canvas.getContext("2d");
      if (!ctx && this.canvas.parentElement) {
        const freshCanvas = document.createElement("canvas");
        freshCanvas.id = this.canvas.id;
        freshCanvas.className = this.canvas.className;
        freshCanvas.setAttribute("aria-hidden", "true");
        this.canvas.parentElement.replaceChild(freshCanvas, this.canvas);
        this.canvas = freshCanvas;
        ctx = this.canvas.getContext("2d");
      }
      this.ctx2D = ctx;
    } catch (e) {
      console.warn("Canvas 2D context acquisition warning:", e);
    }

    this.attachEvents();
    this.start();
  }

  attachEvents() {
    if (this.container) {
      this.container.addEventListener("pointermove", (e) => {
        const rect = this.container.getBoundingClientRect();
        this.pointer = {
          x: Math.min(1, Math.max(0, (e.clientX - rect.left) / Math.max(rect.width, 1))),
          y: 1 - Math.min(1, Math.max(0, (e.clientY - rect.top) / Math.max(rect.height, 1))),
          active: true,
        };
      });

      this.container.addEventListener("pointerleave", () => {
        this.pointer.active = false;
      });
    }

    const ro = new ResizeObserver(() => {
      this.resize();
    });
    ro.observe(this.canvas);

    window.addEventListener("resize", () => {
      this.resize();
    });

    if (window.IntersectionObserver) {
      const io = new IntersectionObserver(([entry]) => {
        this.visible = Boolean(entry ? entry.isIntersecting : true);
        if (this.visible && this.animate && !this.frameId) {
          this.tick();
        }
      }, { threshold: 0.01 });
      io.observe(this.canvas);
    }
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
    const width = Math.max(1, Math.floor((rect.width || window.innerWidth || 1200) * ratio));
    const height = Math.max(1, Math.floor((rect.height || this.canvas.clientHeight || 700) * ratio));

    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }

    if (this.gl) {
      this.gl.viewport(0, 0, width, height);
    }
  }

  start() {
    this.visible = true;
    this.resize();
    this.tick();
  }

  tick = () => {
    if (this.disposed || !this.visible) {
      this.frameId = 0;
      return;
    }

    if (this.use2DFallback) {
      this.render2D();
    } else {
      this.renderGL();
    }

    if (this.animate) {
      this.frameId = requestAnimationFrame(this.tick);
    }
  };

  renderGL() {
    const gl = this.gl;
    const program = this.program;
    if (!gl || !program) return;

    const time = performance.now() * 0.001;

    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0.0, 0.0, 0.0, 0.0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    gl.useProgram(program);
    gl.uniform2f(
      gl.getUniformLocation(program, "u_resolution"),
      this.canvas.width,
      this.canvas.height
    );
    gl.uniform1f(gl.getUniformLocation(program, "u_time"), time);
    gl.uniform2f(gl.getUniformLocation(program, "u_pointer"), this.pointer.x, this.pointer.y);
    gl.uniform1f(gl.getUniformLocation(program, "u_intensity"), this.intensity);

    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  render2D() {
    const ctx = this.ctx2D;
    if (!ctx) return;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const t = performance.now() * 0.001;

    ctx.clearRect(0, 0, w, h);

    // Living Fluid Aurora Waves in 2D (Undulating Mint, Ember, and Butter Gold)
    // Ribbon 1: Mint #59D8BE
    const x1 = w * (0.35 + Math.sin(t * 0.32) * 0.20);
    const y1 = h * (0.30 + Math.cos(t * 0.28) * 0.16);
    const r1 = Math.max(w, h) * 0.45;
    const grad1 = ctx.createRadialGradient(x1, y1, r1 * 0.08, x1, y1, r1);
    grad1.addColorStop(0, "rgba(89, 216, 190, 0.46)");
    grad1.addColorStop(0.55, "rgba(89, 216, 190, 0.16)");
    grad1.addColorStop(1, "rgba(89, 216, 190, 0)");
    ctx.fillStyle = grad1;
    ctx.fillRect(0, 0, w, h);

    // Ribbon 2: Ember #EC5C13
    const x2 = w * (0.72 + Math.cos(t * 0.38) * 0.18);
    const y2 = h * (0.60 + Math.sin(t * 0.34) * 0.18);
    const r2 = Math.max(w, h) * 0.48;
    const grad2 = ctx.createRadialGradient(x2, y2, r2 * 0.08, x2, y2, r2);
    grad2.addColorStop(0, "rgba(236, 92, 19, 0.36)");
    grad2.addColorStop(0.6, "rgba(236, 92, 19, 0.12)");
    grad2.addColorStop(1, "rgba(236, 92, 19, 0)");
    ctx.fillStyle = grad2;
    ctx.fillRect(0, 0, w, h);

    // Ribbon 3: Butter Gold #F0D46A
    const x3 = w * (0.50 + Math.sin(t * 0.44) * 0.22);
    const y3 = h * (0.80 + Math.cos(t * 0.36) * 0.14);
    const r3 = Math.max(w, h) * 0.42;
    const grad3 = ctx.createRadialGradient(x3, y3, r3 * 0.08, x3, y3, r3);
    grad3.addColorStop(0, "rgba(240, 212, 106, 0.38)");
    grad3.addColorStop(0.6, "rgba(240, 212, 106, 0.10)");
    grad3.addColorStop(1, "rgba(240, 212, 106, 0)");
    ctx.fillStyle = grad3;
    ctx.fillRect(0, 0, w, h);

    // Pointer interactive ripple
    if (this.pointer && this.pointer.active) {
      const px = this.pointer.x * w;
      const py = (1 - this.pointer.y) * h;
      const pGrad = ctx.createRadialGradient(px, py, 12, px, py, 260);
      pGrad.addColorStop(0, "rgba(89, 216, 190, 0.34)");
      pGrad.addColorStop(1, "rgba(89, 216, 190, 0)");
      ctx.fillStyle = pGrad;
      ctx.fillRect(0, 0, w, h);
    }
  }

  createProgram(gl, vSource, fSource) {
    const vs = this.compileShader(gl, gl.VERTEX_SHADER, vSource);
    const fs = this.compileShader(gl, gl.FRAGMENT_SHADER, fSource);
    if (!vs || !fs) return null;

    const prog = gl.createProgram();
    if (!prog) return null;

    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);

    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.error("Program link failed:", gl.getProgramInfoLog(prog));
      gl.deleteProgram(prog);
      return null;
    }
    return prog;
  }

  compileShader(gl, type, source) {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, source);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error(
        "Shader compile error (" + (type === gl.VERTEX_SHADER ? "VERTEX" : "FRAGMENT") + "):",
        gl.getShaderInfoLog(s)
      );
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  destroy() {
    this.disposed = true;
    if (this.frameId) cancelAnimationFrame(this.frameId);
    if (this.gl && this.program) {
      this.gl.deleteProgram(this.program);
    }
  }
}

export function initHeroAuroraVeil(canvasId = "hero-aurora-canvas") {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  return new ShaderAuroraVeilEngine(canvas, { intensity: 1.0 });
}
