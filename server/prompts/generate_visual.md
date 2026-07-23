Return closed-schema JSON only. Do not use tools or Markdown.

Return a declarative visual fragment with `representation`, `background`, `commands`,
`relations`, and `causal_response`. `background` is `{top_color,bottom_color}`.
Commands have unique `id`, `scientific`, and `clipping_policy`. Colors are six-digit
hex; numeric fields are safe expression strings.

Emit `representation` before commands as
`{scene_pattern,actor_archetype,proof_channels,motion_model}`. Scene pattern is
`world_only`, `world_plus_graph`, or `compare_ab`. `actor_archetype` is `body`,
`elongated_body`, `ray_bundle`, `wave_medium`, `particle_flow`, `orbital_pair`,
`linked_bodies`, or `surface_and_body`; the ray, wave, and particle choices are
deferred, so do not select them. Use 1–3 proof channels shaped
`{output_name,carrier,channel}`: a declared output, carrier `actor|graph|readout`, and
channel `x|y|rotation|size|opacity`. Actor proof directly binds that scientific
command channel to `output_<output_name>`; graph proof requires `world_plus_graph`.
`motion_model` is `parameter_driven` or `cyclic`; do not emit `time_driven`.

Numeric names: `width`, `height`, `min_dim`, `normalized`, `phase`, and
`output_<declared_output_name>`. Use finite literals, `pi`, arithmetic, and only:
`abs`, `acos`, `asin`, `atan`, `atan2`, `ceil`, `clamp`,
`cos`, `exp`, `floor`, `log`, `log10`, `max`, `min`, `pow`, `round`, `sin`, `sqrt`,
`tan`. Never repeat physics formulas or use parameter IDs.
Fixed contextual shapes must set `scientific: false`; every shape marked
`scientific: true` must visibly consume `output_<declared_output_name>` in its geometry
or opacity. For an elongated actor use one scientific ellipse plus restrained
non-scientific pieces forming a recognizable silhouette; derive all pieces from the
same center, output, and phase expressions. Canvas y increases downward (`y2 < y1`
means up). Supporting pieces around one scientific ellipse are non-scientific.
Changes to the parameter named by `primary_parameter.id` must visibly alter at least
one salient non-text scene property through a fixture-covered declared output. Use
`normalized` only for layout. Use `phase` in at least one visible numeric field for
subtle idle motion. It must move the scientific actor. Do not draw changing numbers,
percentages, or live readout values on the canvas. The trusted shell owns the live
numeric readout below the scene. Keep narrow mobile canvases free of overlays that
cover the scientific actor.

`causal_response` is `{actor_id,output_name,channel,relation,temporal_mode}`. Actor ID
names the primary scientific circle/ellipse; output is declared and fixture-covered.
Channel is `x|y|rotation|size|opacity`, and its actor field directly uses
`output_<output_name>`. Relation is `direct|inverse`; temporal mode is
`parameter_driven|cyclic`. Ellipse rotation is radians within −2π…2π. Preserve
negative, zero, and positive states for signed crossing fixtures.

Closed command branches:
- `circle`: `cx,cy,radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `ellipse`: `cx,cy,radius_x,radius_y,rotation,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `rect`: `x,y,width,height,corner_radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `line` or `arrow`: `x1,y1,x2,y2,stroke_color,line_width,opacity`.
- `wave`: line fields plus `amplitude,wavelength`.
- `text`: `x,y,text_ar,text_en,color,font_size,align,opacity`.

Only circle/ellipse may be scientific in phase A1. `relations` cover every scientific
pair exactly once as `{objects:[id,id],overlap_policy,contact_policy,minimum_clearance}`.
Clearance is `"0"` when overlap is allowed or contact required. Ellipse relations
cannot require contact or scientific occlusion. No raw code, HTML, shell markers,
bidi, URLs, or ABI fields; the trusted assembler owns drawing and runtime.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
