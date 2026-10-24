"""GLSL 330 programs of the AR renderer, kept as strings so packaging needs no data files.

Colours are BGR end to end (camera texture, accents, output) so no swizzle is needed anywhere.
"""

QUAD_VS = """
#version 330
in vec2 in_pos;
out vec2 uv;
void main() {
    uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

KIT_VS = """
#version 330
uniform mat4 u_mvp;
uniform mat4 u_model;
uniform int u_material;
uniform vec4 u_hit;      // xyz: local impact point, w: strength (0 = no live hit)
uniform float u_hit_age;
in vec3 in_pos;
in vec3 in_norm;
out vec3 v_world;
out vec3 v_norm;
out vec3 v_local;
out vec3 v_radial;
void main() {
    vec3 p = in_pos;
    if (u_material == 2 && u_hit.w > 0.0) {  // the drum head gives under the stick, then ripples
        float d = distance(p.xz, u_hit.xz);
        float edge = 1.0 - smoothstep(0.80, 0.97, length(p.xz));
        float dent = 0.035 * exp(-u_hit_age / 0.06) * exp(-d * d / 0.04);
        float ring = u_hit_age * 3.5;
        float wave = 0.012 * exp(-u_hit_age / 0.18) * sin((d - ring) * 20.0) * exp(-abs(d - ring) * 5.0);
        p.y -= u_hit.w * (dent + wave) * edge;
    }
    v_local = in_pos;
    v_world = (u_model * vec4(p, 1.0)).xyz;
    v_norm = mat3(u_model) * in_norm;
    v_radial = mat3(u_model) * vec3(in_pos.x, 0.0, in_pos.z);
    gl_Position = u_mvp * vec4(p, 1.0);
}
"""

KIT_FS = """
#version 330
uniform int u_material;
uniform vec3 u_accent;     // linear BGR
uniform float u_neon;      // neon / accent-light level (rest about 0.6, up to 3 on a hit)
uniform vec3 u_head_tint;  // linear BGR
uniform vec4 u_hit;
uniform float u_hit_age;
uniform float u_alpha;
uniform sampler2D u_cam;
in vec3 v_world;
in vec3 v_norm;
in vec3 v_local;
in vec3 v_radial;
layout(location = 0) out vec4 o_color;
layout(location = 1) out vec4 o_emit;

const float PI = 3.14159265;
const vec3 KEY = vec3(-0.55, 0.75, 0.45);

float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x),
                   mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
                   mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

// Reflections: the real room (the blurred, mirrored camera image) mixed with a dark studio gradient.
vec3 env(vec3 r, float rough) {
    vec2 q = clamp(vec2(0.5 + r.x * 0.5, 0.5 + r.y * 0.5), 0.0, 1.0);
    vec3 room = pow(textureLod(u_cam, vec2(1.0 - q.x, 1.0 - q.y), 3.0 + rough * 5.0).rgb, vec3(2.2));
    float sky = smoothstep(-0.2, 0.8, r.y);
    vec3 studio = mix(vec3(0.015), vec3(0.45), sky);
    studio += 3.0 * vec3(pow(max(0.0, dot(r, normalize(KEY))), mix(400.0, 20.0, rough)));
    return mix(room * 1.4, studio, 0.5);
}

float ggx(float nh, float a) {
    float a2 = a * a;
    float d = nh * nh * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d);
}

float vis(float nv, float nl, float a) {
    float k = a * 0.5;
    return 0.25 / ((nv * (1.0 - k) + k) * (nl * (1.0 - k) + k));
}

vec3 fresnel(vec3 f0, float c) {
    return f0 + (1.0 - f0) * pow(1.0 - c, 5.0);
}

vec3 light(vec3 n, vec3 v, vec3 l, vec3 lc, vec3 base, vec3 f0, float rough, float metal) {
    l = normalize(l);
    vec3 h = normalize(l + v);
    float nl = max(dot(n, l), 0.0);
    float nv = max(dot(n, v), 1e-3);
    float a = max(rough * rough, 0.002);
    vec3 F = fresnel(f0, max(dot(v, h), 0.0));
    vec3 spec = ggx(max(dot(n, h), 0.0), a) * vis(nv, nl, a) * F;
    vec3 diff = (1.0 - F) * (1.0 - metal) * base / PI;
    return (diff + spec) * lc * nl;
}

void main() {
    vec3 v = normalize(-v_world);
    vec3 n = normalize(v_norm);
    if (dot(n, v) < 0.0) n = -n;
    vec3 base;
    vec3 f0;
    float rough;
    float metal;
    float coat = 0.0;
    vec3 emit = vec3(0.0);
    float r = length(v_local.xz);
    if (u_material == 0) {         // lacquered shell with metallic flake and a clear coat
        base = u_accent * 0.07 + vec3(0.003);
        base += step(0.985, hash(floor(v_local * 260.0))) * u_accent * 0.5;
        f0 = vec3(0.05);
        rough = 0.22;
        metal = 0.4;
        coat = 1.0;
    } else if (u_material == 1) {  // chrome
        base = vec3(0.92, 0.91, 0.90);
        f0 = base;
        rough = 0.13;
        metal = 1.0;
    } else if (u_material == 2) {  // coated drum head
        float grain = noise(v_local * 90.0) * 0.08 + noise(v_local * 13.0) * 0.06;
        float wear = smoothstep(0.45, 0.0, distance(v_local.xz, vec2(0.08, 0.15))) * 0.10;
        base = u_head_tint * (0.92 - grain - wear);
        f0 = vec3(0.04);
        rough = 0.55;
        metal = 0.0;
        emit += u_accent * u_neon * 0.12 * smoothstep(0.6, 1.0, r);
        if (u_hit.w > 0.0) {
            float d = distance(v_local.xz, u_hit.xz);
            float flash = exp(-u_hit_age / 0.12);
            float ring = exp(-pow((d - u_hit_age * 3.5) * 9.0, 2.0)) * exp(-u_hit_age / 0.2);
            emit += u_accent * u_hit.w * (1.6 * flash * exp(-d * d / 0.05) + 1.4 * ring);
            emit += vec3(1.0) * u_hit.w * 0.7 * flash * exp(-d * d / 0.004);
        }
    } else if (u_material == 3) {  // brass cymbal: lathe grooves, tonal rings, anisotropic sheen
        float groove = sin(r * 520.0) * 0.5 + 0.5;
        float tone = 0.84 + 0.10 * sin(r * 47.0) + 0.08 * noise(v_local * 40.0);
        base = vec3(0.30, 0.66, 0.95) * tone * (r < 0.2 ? 1.1 : 1.0);
        n = normalize(n + (groove - 0.5) * 0.12 * normalize(v_radial + vec3(1e-5)));
        f0 = base;
        rough = 0.30 - 0.12 * groove;
        metal = 1.0;
        emit += u_accent * u_neon * 0.20 * smoothstep(0.6, 1.0, r);
        if (u_hit.w > 0.0) {
            emit += u_accent * u_hit.w * 1.4 * exp(-u_hit_age / 0.15) * (0.3 + smoothstep(0.2, 1.0, r));
        }
    } else if (u_material == 4) {  // neon strip
        o_color = vec4(pow(mix(u_accent, vec3(1.0), 0.6), vec3(1.0 / 2.2)) * u_alpha, u_alpha);
        o_emit = vec4(u_accent * (0.8 + 2.2 * u_neon) * u_alpha, u_alpha);
        return;
    } else {                       // felt / rubber
        base = vec3(0.05, 0.05, 0.06);
        f0 = vec3(0.03);
        rough = 0.8;
        metal = 0.0;
    }
    vec3 c = vec3(0.0);
    c += light(n, v, KEY, vec3(2.6, 2.5, 2.4), base, f0, rough, metal);
    c += light(n, v, vec3(0.7, 0.25, 0.6), vec3(0.55, 0.6, 0.7), base, f0, rough, metal);
    c += light(n, v, vec3(0.1, 0.35, -1.0), vec3(1.2), base, f0, rough, metal);
    c += light(n, v, vec3(0.0, -0.2, 1.0), u_accent * (0.15 + 0.5 * u_neon), base, f0, rough, metal);
    vec3 rr = reflect(-v, n);
    float nv = max(dot(n, v), 0.0);
    c += env(rr, rough) * fresnel(f0, nv) * (metal > 0.5 ? 1.0 : 0.6);
    c += base * (1.0 - metal) * 0.08;
    if (u_material == 3) {  // radial streaks of a lathed cymbal (Kajiya-Kay on the circumferential tangent)
        vec3 tng = normalize(cross(n, normalize(v_radial + vec3(1e-5))));
        vec3 h = normalize(normalize(KEY) + v);
        float th = dot(tng, h);
        c += base * 2.2 * pow(sqrt(max(0.0, 1.0 - th * th)), 90.0);
    }
    if (coat > 0.0) {
        c += env(rr, 0.03) * (0.04 + 0.96 * pow(1.0 - nv, 5.0)) * 0.9;
        c += vec3(3.0) * pow(max(dot(n, normalize(normalize(KEY) + v)), 0.0), 400.0);
    }
    c += emit;
    c = c / (1.0 + c * 0.25);
    o_color = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)) * u_alpha, u_alpha);
    o_emit = vec4(emit * u_alpha, u_alpha);
}
"""

# Screen-space glow geometry (tips, trails, stick bands, sparks), pixel coordinates, additive.
OVERLAY_VS = """
#version 330
uniform vec2 u_screen;
in vec2 in_pos;
in vec4 in_color;
in float in_emit;
out vec4 v_color;
out float v_emit;
void main() {
    v_color = in_color;
    v_emit = in_emit;
    gl_Position = vec4(in_pos.x / u_screen.x * 2.0 - 1.0, 1.0 - in_pos.y / u_screen.y * 2.0, 0.0, 1.0);
}
"""

OVERLAY_FS = """
#version 330
in vec4 v_color;
in float v_emit;
layout(location = 0) out vec4 o_color;
layout(location = 1) out vec4 o_emit;
void main() {
    o_color = vec4(v_color.rgb * v_color.a, 0.0);
    o_emit = vec4(v_color.rgb * v_color.a * v_emit, 0.0);
}
"""

# Dual-Kawase bloom.
DOWN_FS = """
#version 330
uniform sampler2D u_src;
uniform vec2 u_half;
in vec2 uv;
out vec4 o;
void main() {
    vec4 s = texture(u_src, uv) * 4.0;
    s += texture(u_src, uv - u_half);
    s += texture(u_src, uv + u_half);
    s += texture(u_src, uv + vec2(u_half.x, -u_half.y));
    s += texture(u_src, uv - vec2(u_half.x, -u_half.y));
    o = s / 8.0;
}
"""

UP_FS = """
#version 330
uniform sampler2D u_src;
uniform sampler2D u_add;
uniform vec2 u_half;
in vec2 uv;
out vec4 o;
void main() {
    vec2 h = u_half;
    vec4 s = texture(u_src, uv + vec2(-2.0 * h.x, 0.0));
    s += texture(u_src, uv + vec2(-h.x, h.y)) * 2.0;
    s += texture(u_src, uv + vec2(0.0, 2.0 * h.y));
    s += texture(u_src, uv + vec2(h.x, h.y)) * 2.0;
    s += texture(u_src, uv + vec2(2.0 * h.x, 0.0));
    s += texture(u_src, uv + vec2(h.x, -h.y)) * 2.0;
    s += texture(u_src, uv + vec2(0.0, -2.0 * h.y));
    s += texture(u_src, uv + vec2(-h.x, -h.y)) * 2.0;
    o = s / 12.0 + texture(u_add, uv);
}
"""

# Final image: the mirrored camera under the premultiplied kit layer, plus soft-saturated glow. Drawn
# upside down so row 0 of the readback is the top of the display. ``u_cam`` holds the unmirrored frame
# with row 0 at the top; where the kit layer and glow are empty the camera pixel passes unchanged.
COMPOSITE_FS = """
#version 330
uniform sampler2D u_cam;
uniform sampler2D u_color;
uniform sampler2D u_bloom;
uniform float u_bloom_k;
in vec2 uv;
out vec4 o;
void main() {
    vec2 q = vec2(uv.x, 1.0 - uv.y);
    vec3 cam = textureLod(u_cam, vec2(1.0 - uv.x, uv.y), 0.0).rgb;
    vec4 kit = texture(u_color, q);
    vec3 c = cam * (1.0 - kit.a) + kit.rgb;
    vec3 b = 1.0 - exp(-texture(u_bloom, q).rgb * u_bloom_k);
    o = vec4(c + b * (1.0 - 0.5 * c), 1.0);
}
"""
