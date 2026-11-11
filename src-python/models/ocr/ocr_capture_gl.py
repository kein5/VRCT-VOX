"""Linux: read the OpenVR compositor's mirror texture through OpenGL.

The Windows reader (ocr_capture_d3d11.py) uses a D3D11 texture, which does not
exist here. IVRCompositor::GetMirrorTextureGL hands out an OpenGL texture and a
shared handle; the texture may only be read between
LockGLSharedTextureForAccess and UnlockGLSharedTextureForAccess.

Like the D3D11 reader, the texture is acquired once and reused, and everything
is created, read and released on the caller's thread. The OpenGL context is a
hidden GLFW window of its own, so it does not depend on the overlay's.

Checked against the fake compositor only; SteamVR on Linux has not been tried.
"""

from __future__ import annotations

import numpy as np


class GlMirror:
    """Acquire once, read repeatedly, release on exit. read() returns RGB, top row first."""

    def __init__(self, system, compositor, eye):
        import glfw
        from OpenGL import GL

        self.glfw, self.GL, self.compositor = glfw, GL, compositor
        self.window = self.texture = self.handle = None
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        glfw.window_hint(glfw.VISIBLE, False)
        self.window = glfw.create_window(16, 16, "VRCT OCR GL", None, None)
        if not self.window:
            raise RuntimeError("glfw.create_window() failed")
        try:
            glfw.make_context_current(self.window)
            self.texture, self.handle = compositor.getMirrorTextureGL(eye)
        except Exception:
            self.close()
            raise

    def read(self) -> np.ndarray:
        GL = self.GL
        self.glfw.make_context_current(self.window)
        texture = int(getattr(self.texture, "value", self.texture))
        self.compositor.lockGLSharedTextureForAccess(self.handle)
        try:
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            width = int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_WIDTH))
            height = int(GL.glGetTexLevelParameteriv(GL.GL_TEXTURE_2D, 0, GL.GL_TEXTURE_HEIGHT))
            if width <= 0 or height <= 0:
                raise RuntimeError("mirror texture has no size")
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            data = GL.glGetTexImage(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        finally:
            self.compositor.unlockGLSharedTextureForAccess(self.handle)
        raw = data.tobytes() if hasattr(data, "tobytes") else bytes(data)
        if len(raw) != width * height * 3:
            raise RuntimeError("mirror texture read returned an unexpected size")
        # OpenGL's first row is the bottom of the picture.
        return np.frombuffer(raw, np.uint8).reshape(height, width, 3)[::-1]

    def close(self) -> None:
        if self.window is None:
            return
        try:
            if self.texture is not None:
                self.glfw.make_context_current(self.window)
                self.compositor.releaseSharedGLTexture(self.texture, self.handle)
        finally:
            self.texture = self.handle = None
            window, self.window = self.window, None
            self.glfw.make_context_current(None)
            self.glfw.destroy_window(window)
