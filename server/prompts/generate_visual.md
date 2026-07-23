Return closed-schema JSON only. Do not use tools or Markdown.

Return a declarative visual fragment with `representation`, `background`, `commands`,
`relations`, and `causal_response`. `background` is `{top_color,bottom_color}`.
Commands have unique `id`, `scientific`, and `clipping_policy`. Colors are six-digit
hex; numeric fields are safe expression strings.

Emit `representation` before commands as
`{scene_pattern,actor_archetype,proof_channels,motion_model}`. Scene pattern is
`world_only`, `world_plus_graph`, or `compare_ab`. `actor_archetype` is `body`,
`elongated_body`, `ray_bundle`, `wave_medium`, `particle_flow`, `orbital_pair`,
`linked_bodies`, or `surface_and_body`; wave and particle choices remain deferred,
so do not select them. Select `ray_bundle` only when at least one scientific `ray`
command is present. Use 1–3 proof channels shaped
`{output_name,carrier,channel}`: a declared output, carrier `actor|graph|readout`, and
channel `x|y|rotation|size|opacity`. Actor proof directly binds that scientific
command channel to `output_<output_name>`; graph proof requires `world_plus_graph`.
`motion_model` is `parameter_driven`, `time_driven`, or `cyclic`. `time_driven`
requires one salient scientific field that combines `time` with a declared
`output_<output_name>`; decorative `phase` or raw `time` alone never qualifies.

Numeric names: `width`, `height`, `min_dim`, `normalized`, `phase`, `time`, and
`output_<declared_output_name>`. Use finite literals, `pi`, arithmetic, and only:
`abs`, `acos`, `asin`, `atan`, `atan2`, `ceil`, `clamp`,
`cos`, `exp`, `floor`, `log`, `log10`, `max`, `min`, `pow`, `round`, `sin`, `sqrt`,
`tan`. Never repeat physics formulas or use parameter IDs.
Fixed contextual shapes must set `scientific: false`; every command marked
`scientific: true` must visibly consume `output_<declared_output_name>` in salient
geometry or opacity. A trajectory is always scientific and derives its declared
output from compiled physics. Prefer one `body_group` for a cohesive multi-part
scientific actor; its parts use relative offsets and transform together around the
group center, forming a recognizable silhouette instead of a stack of generic
circles. Outside a body group, keep an actor's pieces cohesive by deriving them
from the same center, output, and phase expressions. When an ellipse is the
primary actor, normally use one scientific ellipse and mark its supporting
silhouette pieces `scientific: false`. Canvas y increases downward. Supporting
pieces outside a body group remain non-scientific.
Changes to the parameter named by `primary_parameter.id` must visibly alter at least
one salient non-text scene property through a fixture-covered declared output. Use
`normalized` only for layout. Use `phase` in at least one visible numeric field for
subtle idle motion. It must move the scientific actor. Do not draw changing numbers,
percentages, or live readout values on the canvas. The trusted shell owns the live
numeric readout below the scene. Keep narrow mobile canvases free of overlays that
cover the scientific actor.

`causal_response` is `{actor_id,output_name,channel,relation,temporal_mode}`. Actor ID
names the primary scientific command; output is declared and fixture-covered.
Channel is `x|y|rotation|size|opacity`, and its actor field directly uses
`output_<output_name>` (trajectory `y` derives the named output by construction).
Relation is `direct|inverse`; temporal mode is `parameter_driven|cyclic`. Angles and
rotations are radians within −2π…2π. Preserve negative, zero, and positive states for
signed crossing fixtures.

Closed command branches:
- `circle`: `cx,cy,radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `ellipse`: `cx,cy,radius_x,radius_y,rotation,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `rect`: `x,y,width,height,corner_radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `line` or `arrow`: `x1,y1,x2,y2,stroke_color,line_width,opacity`.
- `wave`: line fields plus `amplitude,wavelength`.
- `text`: `x,y,text_ar,text_en,color,font_size,align,opacity`.
- `body_group`: `cx,cy,rotation,opacity,parts`. Parts are closed relative shapes:
  - circle: `kind,dx,dy,radius,fill_color,stroke_color,line_width`;
  - ellipse: `kind,dx,dy,radius_x,radius_y,rotation,fill_color,stroke_color,line_width`;
  - rect: `kind,dx,dy,width,height,corner_radius,fill_color,stroke_color,line_width`;
  - line: `kind,dx1,dy1,dx2,dy2,stroke_color,line_width`.
- `vector_arrow`: `x1,y1,angle,length,head_size,stroke_color,line_width,opacity`.
  Bind length or angle to a declared output with an explicit visual scale.
- `ray`: `x1,y1,segments,stroke_color,line_width,opacity`; `segments` contains 1–4
  closed `{angle,length}` objects. Each angle is the absolute canvas direction of
  that segment. A scientific ray binds at least one segment angle or length.
- `trajectory`: `output_name,sweep,samples,stroke_color,line_width,opacity`, with
  `scientific:true`, sweep `primary_parameter|time`, and 8–64 samples. The assembler
  samples compiled physics across the primary range or one declared period. Never
  emit points, coordinates, formulas, or a model-generated range for a trajectory.

Circle, ellipse, body_group, vector_arrow, ray, and trajectory may be scientific.
Every top-level command still includes unique `id`, `scientific`, and
`clipping_policy`; trajectory requires `scientific:true`. `relations` cover every
scientific pair exactly once as
`{objects:[id,id],overlap_policy,contact_policy,minimum_clearance}`. Clearance is
`"0"` when overlap is allowed or contact required. Conservative envelope relations
for ellipse, body_group, vector_arrow, ray, or trajectory cannot require exact
contact or scientific occlusion. No raw code, HTML, shell markers, bidi, URLs, point
lists, or ABI fields; the trusted assembler owns drawing, sampling, and runtime.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
