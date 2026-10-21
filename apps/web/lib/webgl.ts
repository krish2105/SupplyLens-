// WebGL capability probe. Lives outside the 3D module so importing it does not pull three.js into a page bundle.
export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch { return false; }
}
