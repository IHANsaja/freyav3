#version 330

// Fullscreen coverage from a single oversized triangle (3 verts, no index
// buffer, no quad seam down the diagonal).
in vec2 in_pos;

void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
