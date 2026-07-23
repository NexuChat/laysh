Return closed-schema JSON only. Do not use tools or Markdown.

Produce a declarative visual fragment, never JavaScript. Return `background`,
`commands`, `relations`, and `causal_response`. `background` is
`{top_color,bottom_color}` using six-digit hex colors. Every command has a unique
`id`, `scientific`, and `clipping_policy`.
Colors are six-digit hex values and every numeric field is a safe expression string.

Allowed numeric names are `width`, `height`, `min_dim`, `normalized`, `phase`, and
`output_<declared_output_name>`. You may use finite numeric literals, `pi`, arithmetic,
and only these math calls: `abs`, `acos`, `asin`, `atan`, `atan2`, `ceil`, `clamp`,
`cos`, `exp`, `floor`, `log`, `log10`, `max`, `min`, `pow`, `round`, `sin`, `sqrt`,
`tan`. Do not repeat physics formulas or use declared parameter IDs directly. At least
one numeric field of every scientific circle or ellipse must use a declared `output_*`
value. Fixed contextual shapes must set `scientific: false`; every shape marked
`scientific: true` must visibly consume `output_<declared_output_name>` in its geometry
or opacity. Use a rotated ellipse whenever the primary scientific actor is naturally
elongated; combine it with restrained lines, arrows, or rectangles to create a
recognizable silhouette instead of substituting a stack of generic circles. Keep
all pieces of one actor cohesive by deriving them from the same center, output, and
phase expressions. Canvas y increases downward: an upward arrow has `y2 < y1`, and
a downward arrow has `y2 > y1`. When an ellipse is the primary actor, normally use
one scientific ellipse and mark its supporting silhouette pieces `scientific: false`.
Changes to the parameter named by `primary_parameter.id` must visibly alter at least
one salient non-text scene property through a fixture-covered declared output. Use
`normalized` only for secondary layout; it never proves physical causality. Use
`phase` in at least one visible numeric field for subtle idle
motion. The idle motion must change the scientific actor, not only an invisible frame
counter. Do not draw changing numbers, percentages, or live readout values on the
canvas. The trusted shell owns the live numeric readout below the scene. Keep narrow
mobile canvases free of overlays that cover the scientific actor.

`causal_response` is
`{actor_id,output_name,channel,relation,temporal_mode}`. `actor_id` must name the
primary `scientific: true` circle or ellipse. `output_name` must be declared by the
fixed module spec and covered by its fixtures. `channel` is exactly one of
`x`, `y`, `rotation`, `size`, or `opacity`; its corresponding actor field must
directly use `output_<output_name>` (not only `normalized`). `relation` is `direct`
or `inverse`, describing how that visual value follows the output. `temporal_mode`
is `parameter_driven` or `cyclic`. Ellipse rotations are radians; keep them within
−2π…2π. When a signed fixture-backed output crosses zero, preserve distinct
negative, zero, and positive actor states.

Closed command branches:
- `circle`: `cx,cy,radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `ellipse`: `cx,cy,radius_x,radius_y,rotation,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `rect`: `x,y,width,height,corner_radius,fill_color,fill_alt_color,stroke_color,line_width,opacity`.
- `line` or `arrow`: `x1,y1,x2,y2,stroke_color,line_width,opacity`.
- `wave`: line fields plus `amplitude,wavelength`.
- `text`: `x,y,text_ar,text_en,color,font_size,align,opacity`.

Only circles and ellipses may set `scientific: true` in v1. `relations` declare exactly
every pair of scientific IDs with `{objects:[id,id],overlap_policy,contact_policy,
minimum_clearance}`. Use `minimum_clearance: "0"` when overlap is not `forbid` or when
contact is `required`; otherwise it may be a safe numeric expression. Because ellipse
geometry uses a conservative safety envelope, do not declare required contact or
scientific occlusion for a relation involving an ellipse. Do not add raw
code, HTML, shell markers, bidi controls, URLs, or runtime/ABI fields. The trusted
assembler owns all drawing, geometry evidence, model state, tests, lifecycle, and ABI.

UNDERSTANDING_JSON:
@@INPUT_JSON@@
