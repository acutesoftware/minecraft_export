"""Small flat-colour lighting shader; does not require shadow-map support."""


def terrain_shader():
    from ursina import Shader
    return Shader(language=Shader.GLSL, vertex='''#version 150
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 vertex;
in vec3 normal;
in vec4 p3d_Color;
in vec2 p3d_MultiTexCoord0;
out vec2 texcoord;
out vec3 world_pos;
out vec3 world_normal;
out vec4 tint;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * vertex;
    world_pos = (p3d_ModelMatrix * vertex).xyz;
    world_normal = normalize(mat3(p3d_ModelMatrix) * normal);
    tint = p3d_Color;
    texcoord = p3d_MultiTexCoord0;
}
''', fragment='''#version 150
uniform vec3 sunlight_direction;
uniform vec3 sunlight_color;
uniform vec3 ambient_color;
uniform vec3 horizon_color;
uniform vec3 eye_position;
uniform vec2 fog_range;
uniform sampler2D p3d_Texture0;
in vec2 texcoord;
in vec3 world_pos;
in vec3 world_normal;
in vec4 tint;
out vec4 fragment_color;
void main() {
    float diffuse = max(0., dot(normalize(world_normal), sunlight_direction));
    vec4 surface = texture(p3d_Texture0,texcoord) * tint;
    if (surface.a < .1) discard;
    vec3 lit = surface.rgb * (ambient_color + sunlight_color * diffuse);
    float fog = smoothstep(fog_range.x, fog_range.y, length(world_pos-eye_position));
    fragment_color = vec4(mix(lit, horizon_color, fog), surface.a);
}
''')
