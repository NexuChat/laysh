# تشخيص 2026-07-27 — فشل توليد المحاكاة + تشريح "التجارب" (Model Lab)

> حالة الوثيقة: تشخيص مكتمل، **لم يُطبَّق أي إصلاح بعد**.
> قيود محترمة: لا `git push`، ولا أي كتابة على remote حق Laysh، ولا أي git write إطلاقًا.
> كل ما في هذه الوثيقة نتج عن قراءة وفحص محليّ فقط.

---

## 1. الخلاصة التنفيذية

> **الاكتشاف الأكبر جاء متأخرًا**: التوليد على الموقع كان **ميتًا تمامًا**، لا بطيئًا ولا
> ضعيفًا. أربعة ألغام كامنة (§12) كانت تنتظر أول إعادة تشغيل. الصفحة والمعرض كانا
> يردّان 200 لأنهما لا يستدعيان موديلًا، فبدا الموقع سليمًا. راجع §12 قبل أي شيء آخر.

| # | النتيجة | الخطورة |
|---|---|---|
| 0 | **٤ ألغام كامنة**: `laysh-data` محذوف · جلسة Codex مُبطَلة · `codex-pro` symlink · `ProtectHome` يمنع أي CODEX_HOME بديل | 🔴🔴 الموقع كان معطّلًا |
| 1 | الخدمة كانت تشغّل `9e785bb`، والريبو فيه 1000+ سطر إصلاحات غير منشورة | ✅ نُشرت |
| 2 | محاولة "لماذا يتغير شكل القمر؟" فشلت لأن المُصلِح **انحدر** (8 → 25 خطأ) | 🔴 |
| 3 | `candidate_count=1` (يقبل 2) ⇒ لا مرشّح بديل عند الانحدار | 🟠 |
| 4 | `model_lab_discovery.py` **مشترك مع الخط العام** رغم اسمه — وفيه انحدار | ✅ أُصلح |
| 5 | حلقة 404 التي رصدتها = تبويب متصفح قديم، **الكود المنشور مُصلَح أصلًا** | 🟢 تصحيح |
| 6 | مظروف التعبير مقيّد: `time_driven` و3 archetypes **مؤجَّلة لـ phase A2** | 🟠 بنيوي (§13) |

---

## 2. الطوبولوجيا — أين يعيش الموقع الحيّ فعلًا

```
laysh.mlki.app  →  Cloudflare (188.114.97.3)
      ↓
cloudflared-laysh.service          (systemd --user, active)
      ↓
http://127.0.0.1:8765
      ↓
laysh.service → PID 20594 → cwd = /home/dev/laysh-local-preview   ← الحيّ
```

الـ unit الأصلي يشير إلى `%h/laysh`، لكن **3 drop-ins** تتراكم والأخير يفوز:

| drop-in | WorkingDirectory | الحالة |
|---|---|---|
| `deploy-isolation.conf` | `%h/laysh-live` | مُلغى |
| `zz-current-checkout.conf` | `/home/dev/laysh` | مُلغى |
| `zzz-local-runtime-hotfix.conf` | `/home/dev/laysh-local-preview` | ✅ **الفائز** |

### فجوة النشر

```
الحيّ (laysh-local-preview)  ==  commit 9e785bb بالحرف   (نُشر 2026-07-27 00:22)
الريبو (laysh, post-buildweek) ==  9e785bb + تعديلات غير مودعة (آخرها 03:18)
```

التعديلات غير المودعة (`git diff --stat`):

```
server/pipeline.py                         | 640 ++++++++++------
server/fragment_generation.py              | 137 +++-
server/model_lab_discovery.py              |  49 +-
server/codex_backend.py                    |   4 +-
server/scene_geometry.py                   |   4 +-
server/prompts/generate_visual.md          |   7 +-
server/prompts/understand.md               |   3 +-
server/schemas/visual_fragment.schema.json |  24 +-
server/schemas/understand.schema.json      |   2 +-
tests/test_public_hybrid_generation.py     | 321 +++++++++  (جديد)
tests/test_representation_block.py         |  62 +-
tests/test_model_lab.py                    |  37 +
out/evidence/contracts-frozen.json         |   8 +-
scripts/check_artifact.mjs                 |   2 +-
14 files changed, 1000 insertions(+), 300 deletions(-)
```

⚠️ **المجلد الحيّ ليس git repo** — لا `.git`، و`.venv` مجرد symlink إلى `/home/dev/laysh/.venv`.
أي تعديل مباشر هناك يمشي على الموقع العام **بلا تتبّع ولا rollback**.

---

## 3. تتبّع المحاولة الفاشلة — `job_814413a42e9d9fdb`

السؤال: **"لماذا يتغير شكل القمر؟"** · المدة: ~3 دقائق

| الوقت | المرحلة | النتيجة |
|---|---|---|
| 17:08:46 | `POST /api/ask` | ✅ 202 Accepted، الـ SSE فتح 200 |
| 17:09:03 | تصنيف الفهم `gpt-5.6-luna` | ❌ `classification_validation_failed` → سقط لـ `terra` ✅ |
| 17:09:55 | المسار البصري `trusted_scene_plan` | ❌ `ContractError` / `representation_archetype_command_mismatch` |
| 17:10:22 | تحقّق `heal_count=0` | ❌ `causal_relation_mismatch` + **8×** `scene_contract_invalid_state` |
| 17:11:47 | تحقّق `heal_count=1` | ❌ `causal_evidence_invalid` + **25×** `scene_contract_invalid_relation` |
| 17:11:47 | `heal convergence aborted … reason=regression` | 🛑 رُفض العرض |

**الجواب النصي نجح** — لهذا ظهر شرح القمر و θ. الساقط هو المحاكاة فقط.
البوابة التزمت بوعد المنتج: لا تُعرض محاكاة غير متحقَّقة، ولا تُخزَّن.

---

## 4. جذور السبب — ثلاث طبقات

### الطبقة ١: الـ archetype لا يطابق الأشكال المرسومة

`server/codex_backend.py:105`:
> "Match actor_archetype to the emitted scientific circle and ellipse composition,
> **including enough scientific actors for paired archetypes**."

الموديل أعلن archetype مزدوجًا (أرض + قمر ⇒ `orbital_pair`) ثم لم يُصدر عددًا كافيًا من
الـ scientific actors له. العقد يعرف الخلل ويشرحه — والموديل لم يلتزم.

### الطبقة ٢: المُصلِح يكسر ما صحّ — الأخطر

| | قبل الإصلاح | بعد الإصلاح |
|---|---|---|
| `causal_response` | `causal_relation_mismatch` | `causal_evidence_invalid` |
| `scene_geometry` | **8×** `scene_contract_invalid_state` | **25×** `scene_contract_invalid_relation` |

- الأخطاء الثمانية في `state` كانت في **كل** الـ samples ⇒ خلل نظامي لا عشوائي
  (`scene_geometry.py:131-152`: `state.id` غير نصّ غير فارغ، أو `timeMs` غير منتهٍ/سالب).
- الإصلاح صلّح `state`، ثم **هدم relations** (`scene_geometry.py:304-315`: أزواج غير
  موجودة أو مكرّرة، أو `minimumClearance` مخالف لسياسته).

حرّاس الانحدار `_heal_convergence_decision` (`pipeline.py:156-166`) أمسكوها بشكل صحيح
وأوقفوا كل شيء (`reason=regression`) — الحارس سليم، المُصلِح هو المعطوب.

**الإصلاح موجود أصلًا في الريبو غير منشور** — `fragment_repair_plan()` في `pipeline.py`،
ويُوثّق الخلل نفسه حرفيًا:

```python
FRAGMENT_RETRY_ROLE_BY_GATE = {
    "scene_geometry": "visual",
    "causal_response": "visual",
    ...
}
"""Map deterministic failures onto the fragments that own them, or fail closed.
Returning None means *no fragment owns this failure* ... so handing them to a
model rewrite can only destroy deterministically-correct work."""
```

أي: إصلاح **مُنطاق على الـ fragment المسؤول** بدل إعادة كتابة الموديول كاملًا.

### الطبقة ٣: لا مرشّح بديل

> ⚠️ **تصحيح** لقراءة أولى خاطئة: قرأت `public_heal_attempt_limit = 1` من افتراضي
> `settings.py:34` وعرضته كقيمة حيّة. القيمة الحيّة الفعلية **2**، مضبوطة في
> `zzz-local-runtime-hotfix.conf:20`. أي أن حدّ الإصلاح **مرفوع أصلًا للحد الأقصى**،
> والإيقاف جاء من حارس الانحدار وحده لا من استنفاد المحاولات.

القيم الحيّة المؤكَّدة من بيئة العملية (PID 20594):

```
LAYSH_PUBLIC_HEAL_ATTEMPT_LIMIT = 2   ← الحد الأقصى المسموح، مضبوط
LAYSH_PUBLIC_CANDIDATE_COUNT    = 1   ← اللافتة الوحيدة الباقية (يقبل 2)
LAYSH_PUBLIC_GENERATION_STRATEGY = hybrid
```

فمرشّح واحد ⇒ عند انحدار الإصلاح لا يوجد `qa_verified_candidate` للرجوع إليه
⇒ `_fallback()` مباشرة. رفعه إلى 2 يضاعف نداءات الموديل لكل طلب عام؛
سياق الخنق: `LAYSH_MAX_PARALLEL_MODEL_CALLS=2` و`MAX_PARALLEL_BROWSER_GATES=1`.

---

## 5. تصحيح: حلقة الـ 404 ليست خللًا في الكود الحالي

رصدت `GET /api/jobs/job_3a9fdbc39461c93a/events → 404` كل 10 ثوانٍ لقرابة الساعة،
وقلت إن الواجهة "لا تستسلم". **هذا غير صحيح للكود المنشور.** `web/app.js` يحتوي الإصلاح:

```js
const POLL_DEADLINE_MS = SERVER_JOB_BUDGET_MS + 60_000;
const JOB_EVENTS_NOT_FOUND_LIMIT = 3;
...
if (response.status === 404) {
  state.notFoundCount += 1;
  if (state.notFoundCount >= JOB_EVENTS_NOT_FOUND_LIMIT) { showFailure("job_not_found"); return; }
```

وهو جزء من `9e785bb` ("stop the client polling a dead job forever").
⇒ الحلقة المرصودة = **تبويب متصفح قديم يحمل JS قديمًا في الذاكرة**، لا خلل قائم.
العلاج: إغلاق/تحديث ذلك التبويب. لا عمل كود مطلوب.

---

## 6. حالة الاختبارات (على شجرة الريبو غير المودعة)

```
908 passed · 2 failed · 1 skipped   (9:39)
```

الفاشلان:

```
tests/test_model_lab_discovery.py::test_discovery_plan_includes_localized_related_references[en]
tests/test_model_lab_discovery.py::test_discovery_plan_includes_localized_related_references[ar]
StopIteration  ← لا يوجد reference بمزوّد "phet"
```

الاختبارات الخاصة بالعمل الجديد كلها خضراء:
`test_public_hybrid_generation.py` + `test_representation_block.py` ⇒ **33 passed**.

---

## 7. انحدار `model_lab_discovery` — ويمسّ الخط العام

### السبب الدقيق — تغييران غير مودعين يتصادمان

**التغيير أ** — في `representation_family_for()`: هُوِّست كل الـ actions إلى dict يُفحَص **أولًا**:

```python
action_family = {"phases": "orbital_light", "propagates": "waves", ...}
if action in action_family:
    return action_family[action]      # ← يسبق فحص النطاق
```

الترتيب الأصلي كان يتشابك: النطاق والـ action معًا، بترتيب العائلات:

| # | العائلة | الشرط الأصلي |
|---|---|---|
| 1 | `orbital_light` | action ∈ {phases, orbits} **أو** domain ∈ (astronomy, orbital, celestial) |
| 2 | `rays` | domain ∈ (optics, light, refraction) ← **نطاق فقط** |
| 3 | `waves` | action == propagates **أو** domain ∈ (acoustic, sound, wave, seismic) |
| 4 | `fluid_body` | action == floats_sinks **أو** domain ∈ (fluid, density, …) |
| 5 | `particles_flow` | action == flows **أو** domain ∈ (electric, current, …) |
| 6 | `force_body` | action == oscillates **أو** domain ∈ (mechanic, force, …) |

`rays` (خطوة 2، نطاق فقط) كان **يسبق** `waves` (خطوة 3، صاحبة action=propagates).
لذا `domain=optics, action=propagates` ⇒ **`rays`** — وهو الصحيح علميًا (ضوء/انكسار/قوس قزح).
بعد التهويس ⇒ `waves` خطأً، لأن الـ action لم يُعطِ النطاق فرصة.

**التغيير ب** — في `related_references_for()`: أُضيف حارس مطابقة نطاق (وهو **سليم ومطلوب**):

```python
# A generic or mismatched family has no topic-specific interactive reference.
# Do not attach a plausible-looking link from another domain just to populate it.
phet = _PHET_BY_FAMILY.get(family) if any(token in normalized_domain
        for token in reference_domain_tokens[family]) else None
```

**التفاعل**: التغيير أ صنّف سؤال optics كـ `waves`؛ ثم التغيير ب رأى أن `optics` لا يطابق
رموز `waves` (acoustic/sound/wave/seismic) ⇒ أسقط مرجع PhET ⇒ `StopIteration`.

الحارس (ب) بريء وأدّى وظيفته. **الخلل في (أ): أولوية action فوق domain.**
الإصلاح الصحيح = إعادة أسبقية النطاق على الـ action (لا تعديل الاختبار).

### لماذا هذا خطير أكثر مما يبدو

```python
server/pipeline.py:23:  from server.model_lab_discovery import build_discovery_plan
```

`model_lab_discovery.py` **مستورَد في الخط العام**، رغم اسمه. فهذا الانحدار
يُسقط مراجع PhET ودورة التعلّم عن **محاكاة الموقع العام**، لا عن التجارب وحدها.

---

## 8. تشريح "التجارب" / Model Lab — ماذا يحتاج وماذا يفعل

### 8.1 البصمة

| الملف | الأسطر | الملكية |
|---|---|---|
| `server/model_lab.py` | 2041 | 🔵 خاص بالتجارب |
| `server/model_lab_discovery.py` | 904 | 🔴 **مشترك مع الخط العام** |
| `tests/test_model_lab*.py` (4 ملفات) | 2064 | 🔵 خاص |
| `web/model-lab.html` + `/static/model-lab.js` + `.css` | — | 🔵 خاص |
| ارتباطات في `server/app.py` | 15+ موضعًا | 🔵 خاص |

### 8.2 مفتاح الإيقاف موجود أصلًا

```python
server/settings.py:60   model_lab_enabled: bool = False        # الافتراضي: مُطفأ
server/settings.py:250  os.getenv("LAYSH_MODEL_LAB_ENABLED", "0") == "1"
```

`require_model_lab()` (`app.py:208`) يحجب كل مسار عند الإطفاء.
**القيمة الحيّة الآن: `LAYSH_MODEL_LAB_ENABLED=1`** — أي أن الافتراضي مُطفأ وأحدهم شغّلها صراحة.

### 8.3 ماذا يحتاج (المدخلات)

```
question   ≤ 600 حرفًا
locale     ar | en
source_mode   off | public_references
visual_mode   trusted_scene_plan | direct_canvas | hybrid_race
stages     ← لكل مرحلة موديل: {model, effort, fast}
```

- الموديلات المسموحة: `gpt-5.6-luna` · `gpt-5.6-terra` · `gpt-5.6-sol`
- الـ effort: `low` · `medium` · `high` · `xhigh` · `max` · `ultra`
  (ويُتحقَّق أن الـ effort مدعوم للموديل: `effort_must_match_model`)
- المراحل التي تأخذ موديلًا (6): `understand` · `physics` · `visual` · `repair_1` · `repair_2` · `qa`

### 8.4 ماذا يفعل — خط الأنابيب (11 مرحلة)

```
evidence → understand → physics → plan → visual → verify → browser
                                                     → repair_1 → repair_2 → qa → finalize
```

`kind` لكل مرحلة: `model` (يستدعي موديلًا) · `deterministic` (حتمية بلا موديل) · `source`.

**الميزة الجوهرية — إعادة تشغيل مرحلة تُبطل كل ما بعدها** (`_invalidate_pipeline_from`):

| أعِد من | يُبطَل |
|---|---|
| `evidence` | evidence, understanding, answer, physics, discovery, visual, module, verification, qa, artifact |
| `understand` | understanding, answer, physics, discovery, visual, module, verification, … |
| `physics` | physics, discovery, visual, module, verification, … |
| `plan` | discovery, visual, module, verification, … |
| `visual` | visual, module, verification, … |
| `verify` | verification فقط |
| `browser` | يُرجِع الفحص إلى النتائج الحتمية فقط ويعيد `passed=False` |

فيُصبح الجدول الزمني (`timeline`، حتى 120 حدثًا) سجلًّا لأثر تغيير موديل مرحلة واحدة
على كل ما يليها — وهذه هي قيمة الأداة الحقيقية.

### 8.5 وضع المقارنة A/B

`POST /api/model-lab/compare` — **مرشّحان بالضبط** (`min_length=2, max_length=2`)،
لكل مرشّح `{physics, visual}` بموديل/جهد مستقلين، ويعيد لكل واحد:
`status`, أزمنة كل مرحلة, `check_count`, `failed_gates`, `failure_codes`,
و`artifact_tier` ∈ {`verified`, `unverified_preview`}.

### 8.6 المعزولية — مؤكَّدة بالكود

بحثت عن أي كتابة إلى المكتبة العامة داخل `model_lab.py`:
`save_document|library|gallery|persist|store_document` ⇒ **صفر نتائج**.
يطابق ما تدّعيه الواجهة: *"Isolated lab · never added to the library"*.

ولا يعيد بناء البوابات — يستورد نفس أدوات الخط العام:

```
server.fragment_generation   ← نفس توليد الـ fragments
server.verify                ← نفس البوابات الحتمية (verify_candidate)
server.browser_verify        ← نفس فحص المتصفح
server.codex_backend/runtime  ← نفس تشغيل الموديلات
```

⇒ Model Lab = **واجهة موازية على نفس أحشاء الخط**، بتحكّم لكل مرحلة. ليس خطًّا ثانيًا.

### 8.7 حدود الاستهلاك (من بيئة العملية الحيّة)

```
LAYSH_MODEL_LAB_MAX_CONCURRENT_RUNS      = 1
LAYSH_MODEL_LAB_IP_COMPARISONS_PER_HOUR  = 20
LAYSH_MODEL_LAB_GLOBAL_COMPARISONS_PER_DAY = 100
```

---

## 9. تحليل نطاق الحذف (إن أردنا إزالة "التجارب")

⚠️ تنبيه تسمية: **"التجارب" في الواجهة تعني شيئين مختلفين**:

| العنصر | الموضع | ما هو |
|---|---|---|
| `"failure.gallery": "اذهب إلى التجارب"` | `web/translations.js:134` (EN: *"Go to experiences"*) | زر **المكتبة/المعرض** العام — `/api/gallery` |
| Model Lab · *"Pipeline Workbench"* | `web/model-lab.html` | **مختبر خط الأنابيب** الداخلي |

الزر الذي ظهر لك عند الفشل هو **المعرض**، لا المختبر.

| الهدف | آمن للحذف؟ |
|---|---|
| `server/model_lab.py` + الاختبارات الأربعة + `web/model-lab.*` + ارتباطات `app.py` | ✅ نعم — لا يمسّ التوليد العام |
| `server/model_lab_discovery.py` | ❌ **لا** — `pipeline.py:23` يستورده؛ حذفه يُعطب الموقع العام |
| المعرض/المكتبة (`/api/gallery`) | ❌ ليس Model Lab إطلاقًا |

**الأرخص والأكمل عودةً**: `LAYSH_MODEL_LAB_ENABLED=0` — سطر واحد، مفتاح موجود ومختبَر،
صفر حذف، ورجوع فوري. مقابل انتزاع ~5000 سطر من مشروع مجمّد في مجلد بلا git.

---

## 10. ما نُفِّذ وما بقي

### ✅ نُفِّذ (2026-07-27، بموافقة المالك)

**1. إصلاح انحدار `representation_family_for`** — `server/model_lab_discovery.py`

استُبدل الـ dict المُهوَّس بجدول مسارات مرتّب `_FAMILY_ROUTES` يوزن النطاق والـ action
معًا عائلةً عائلة بترتيب الإعلان، فيستعيد أسبقية النطاق على الـ action:

```python
_FAMILY_ROUTES = (
    ("orbital_light", frozenset({"phases", "orbits"}), ("astronomy", "orbital", "celestial")),
    ("rays",          frozenset(),                     ("optics", "light", "refraction")),
    ("waves",         frozenset({"propagates"}),       ("acoustic", "sound", "wave", "seismic")),
    ...
)
for family, actions, domain_tokens in _FAMILY_ROUTES:
    if action in actions or any(token in normalized_domain for token in domain_tokens):
        return family
```

حارس المطابقة في `related_references_for` **لم يُلمس** — هو سليم ومقصود.
النتيجة: `tests/test_model_lab_discovery.py` ⇒ **26 passed** (كان 2 ساقطين).

**2. إطفاء التجارب بالمفتاح** — `zzz-local-runtime-hotfix.conf:28`

`LAYSH_MODEL_LAB_ENABLED: 1 → 0` + نسخة احتياطية `*.bak-20260727`
(يتبع عرف الملف نفسه). `systemctl --user daemon-reload` نُفِّذ، والوحدة المدمَجة
تُظهر `=0`. **لم يُحذف أي سطر كود** — لأن `model_lab_discovery.py` مشترك مع الخط العام.
⏳ يسري عند إعادة التشغيل.

### ⏳ بقي

| # | البند | ملاحظة |
|---|---|---|
| 1 | إعادة تشغيل `laysh.service` | يُسري إطفاء التجارب |
| 2 | نشر شجرة الريبو (1000+ سطر) إلى المجلد الحيّ | **القرار الكبير** — هو الإصلاح الحقيقي للمُصلِح المنحدر؛ الحيّ = `9e785bb` وقد فشل عليه فعلًا |
| 3 | `LAYSH_PUBLIC_CANDIDATE_COUNT: 1 → 2` | يضاعف نداءات الموديل لكل طلب عام؛ إطفاء التجارب يحرّر جزءًا من الميزانية |
| 4 | إغلاق تبويب الـ 404 الزومبي | لا عمل كود — الكود المنشور مُصلَح |

---

## 15. التجربة الحاسمة — المظروف يعمل داخله ويستحيل خارجه

أربع أسئلة جديدة تمامًا على الشجرة المنشورة:

| السؤال | الصنف | ما يحتاجه | النتيجة |
|---|---|---|---|
| لماذا يتغير شكل القمر؟ ×2 | فلكي | زمن + زوج مداري | ❌ `regression` |
| كيف يحدث كسوف الشمس؟ | فلكي | زمن + **تراكب** + **3 أجسام** | ❌ `regression` + 7 بوابات |
| كيف تؤثر الكتلة في التسارع؟ | ميكانيكي | جسم · مقبض · بلا تراكب | ✅ **`complete`** |

الناجح: `sim_ba732a5da3a44d17` · tier B · **69 فحصًا** · إصلاحان · 225s ·
تنزيل 200 (253 KB، canvas + rAF + `arc()`, `a = F/m`) · ودخل `out/cache/live`.

> **الحكم**: المعمار **ليس فاشلًا** — يُنتج علمًا متحقَّقًا اليوم. الفشل محصور في
> صنف واحد يحتاج ثلاث قدرات مسمّاة في الكود بالاسم (`phase A2 primitives`):
> `time_driven` · التراكب/الحجب عمليًا · أكثر من جسمين.
>
> ⚠️ **تصحيح**: كتبت أن «لا سؤال فلكي واحد يستطيع النظام رسمه» — صحيح للفلكيات
> ويبقى. لكنني تركت انطباعًا أعمّ بأن المعمار يحتاج إعادة بناء؛ البيانات تنفيه.
> النقلة المعمارية (تحقّق من الأرقام لا من الصورة) تبقى الاتجاه الصحيح **لتوسيع
> التغطية**، لا لإنقاذ النظام — وهذا فرق جوهري في الكلفة والمخاطرة.

### الخطأ التصميمي بدقة

النظام يثبت صحة العلم بتقييد **الرسم**، فيخلط سؤالين: «هل الفيزياء صحيحة؟» (أرقام)
و«هل الصورة صحيحة؟» (بكسل). ولهذا صار التراكب مخالفةً — **والكسوف تراكبٌ بتعريفه**.

النمط الاحترافي (وهو ما تفعله PhET): افصل النموذج عن العرض، وتحقّق من **النموذج**:
تحليل أبعاد · مقارنة بحلّ مغلق · خصائص (رتابة/تناظر/حفظ) · حدود · استقرار عددي.
لاحظ أن `non_finite_output` في الكسوف **فحص صحيح في الطبقة الخطأ**.

التقنية الحالية: **Canvas 2D خام** (`getContext("2d")` + `rAF` + `arc/fill/stroke`)،
ملف HTML واحد ~253 KB بلا شبكة. والقيود ليست قيود Canvas — Canvas يرسم الكسوف في
عشرين سطرًا — بل **مفردات المُجمِّع الموثوق** الذي يترجم أوامر وصفية إلى نداءات
Canvas. مُترجِمات A2 لم تُكتب بعد. و**SVG** بديل أفضل للعرض: للأجسام هوية، فتؤكّد
البنية في الـ DOM بدل هَش البكسل، وتكسب الوصولية وRTL.

ملاحظة: `direct_canvas` و`hybrid_race` **مبنيان بالفعل** كأنماط بصرية — يستحق فحصًا
هل يُوثَق بهما للفلكيات بلا انتظار A2.

### ما يُحتفظ به

رفض عرض علم غير متحقَّق (فضيلة نادرة — انقلها لطبقة النموذج ولا تُلغِها) · الحتمية ·
فحوص المتصفح الحيّة (`canvas_pixels_unchanged` سؤال إدراكي مشروع). والخوف من تشغيل
شيفرة يكتبها موديل مشروع — لكن جوابه **العزل** (iframe + CSP + منع الشبكة)، لا
تقليص المفردات.

---

## 14. نتيجة ما بعد النشر — الانحدار **لم** يُصلَح

أول جولة تصل التحقق بعد النشر: `job_9b971a53d2ab5734` (2026-07-27 18:14).

```
18:14:22  POST مقبول                                        0s
18:14:35  understand: luna فشل (classification_validation)  13s   ← مُهدرة
18:15:15  understand terra + generate → رفض بصري            40s
18:15:52  التحقق #1 — 7 أخطاء                               37s
18:17:06  الإصلاح + التحقق #2 → انحدار → إيقاف              74s   ← 45%
          الزمن الكلي على الساعة = 164s
```

نداءات الموديل (مجموعها **185s** > 164s على الساعة ⇒ **دليل التوازي**، `MAX_PARALLEL_MODEL_CALLS=2`):

| المرحلة | الموديل | الزمن |
|---|---|---|
| understand | luna | فشل (~13s) |
| understand | terra | 25.8s |
| generate | luna | 6.2s |
| generate | terra | 21.2s |
| generate | terra | 57.9s |
| **heal** | terra | **73.9s** ← الأغلى، وأنتج أسوأ |

### مقارنة قبل/بعد — الحكم الصادق

| | 17:08 قبل النشر | 18:14 بعد النشر |
|---|---|---|
| قبل الإصلاح | `invalid_state` ×8 | `invalid_state` ×6 |
| بعد الإصلاح | `invalid_relation` ×**25** | `invalid_relation` ×**18** |
| البوابة السببية | `relation_mismatch` → `evidence_invalid` | **نفسها بالحرف** |
| النهاية | `reason=regression` | **`reason=regression`** |
| الزمن | 181s | **164s (−9%)** |

> ⚠️ **تصحيح**: قرأت `heal → completed` في سجلّ المراحل واستنتجت أن "النشر أوقف
> الانحدار". **خطأ**: `completed` تعني أن **نداء الموديل** نجح، لا أن الإصلاح أفلح.
> السجل يقول `heal convergence aborted … reason=regression` — نفس الانحدار بالحرف.

**الحكم**: النشر ربح **9% سرعة وصفر تحسّن في النتيجة**. `fragment_repair_plan` كان في
`9e785bb` أصلًا؛ الشجرة وسّعته لكنها لم تمنع هذا الانحدار.

**والأهم أن الانحدار حتميّ لا عشوائي (2/2)** بنفس البوابتين على نفس السؤال:
المُصلِح يصلّح `state` ثم ينقض عقد `relations`. أي أنه لا يقدر على تعديل جزء دون هدم
جزء آخر — العقد مشدود أكثر من مساحة مناورته.

`answer_only` + `fallback.reason_code = "verification_exhausted"`: استُنفدت المحاولتان،
فسُلِّم النص وامتُنع عن عرض المحاكاة أو تخزينها. البوابة تفي بوعدها.

### الرافعتان بالترتيب حسب القياس

1. **الفشل السريع** عند التصنيف (سؤال مداري ⇒ `time_driven` مؤجَّل) ⇒ 164s → ~40s
2. **تخطّي الإصلاح** لأصناف الفشل المعروف انحدارها ⇒ توفير 74s (45%)

لو أُلغي الإصلاح اليوم لانتهت الرحلة عند 90s **بنفس النتيجة** — أي 45% توفير بلا خسارة.

> ملاحظة أداتية: `answer_only` حالة نهائية لم أدرجها في شرط الاستقصاء
> (`complete|rejected|failed`)، فدار المستقصي 600s بلا مطابقة. أي مراقب للوظائف
> يجب أن يعامل `answer_only` كحالة نهائية.

---

## 12. الألغام الأربعة الكامنة — أخطر ما في هذا التقرير

الخدمة كانت تعمل منذ `Jul 27 00:22` بلا إعادة تشغيل. أول إعادة تشغيل (لتفعيل إطفاء
التجارب) فجّرت سلسلة أعطال **كلها كانت موجودة قبل أي تعديل منّي**. لولا هذه الجلسة
لانفجرت عند أول تحديث أو انقطاع كهرباء أو `Restart=always` — بلا أحد يشاهد.

### اللغم ١ — `/home/dev/laysh-data` محذوف ⇒ الخدمة لا تقلع

```
Failed to set up mount namespacing: /home/dev/laysh-data: No such file or directory
status=226/NAMESPACE     ← فشل 18 مرة متتالية، الموقع ساقط
```

`deploy-isolation.conf:10` فيه `ReadWritePaths=%h/laysh-data`، وsystemd يشترط وجود
المسار ليبني الـ bind-mount. المجلد اختفى (يرجَّح مع تنظيف القرص 2026-07-27).
**العلاج**: `mkdir -p /home/dev/laysh-data/live-cache` ⇒ أقلعت من أول محاولة.
ملاحظة: أُعيد إنشاؤه **فارغًا**؛ أي كاش توليد عام سابق ضاع مع التنظيف.

### اللغم ٢ — جلسة `~/.codex` مُبطَلة ⇒ كل توليد يموت في ٥ ثوانٍ

```json
{"message": "Your session has ended. Please log in again.",
 "code": "refresh_token_invalidated"}
```

النتيجة في الـ API: `stage=understand · outcome=failed · failure_code=nonzero_exit`
خلال ~5 ثوانٍ. محاولة المالك في 17:08 نجحت لأن الـ access token المؤقّت كان لا يزال
صالحًا؛ انتهى قبل 18:10 وفشل تجديده.

### اللغم ٣ — اعتمادان، ثلاثة مسارات

```
~/.codex/auth.json          ← ملف حقيقي   (الحساب الأول)
~/.codex-pro/auth.json      →  symlink  →  ~/.codex/auth.json      ← نفس الاعتماد
~/.codex-mdoosh/auth.json   ← ملف حقيقي مستقل (الحساب الثاني)
```

> ⚠️ **تصحيح**: كتبت أولًا أن "الـ failover وهميّ". **مبالغة.** حسابا maestro
> (`codex-pro` + `codex-pro-mdoosh`) **متمايزان فعلًا**، والـ failover بينهما سليم.
> الـ symlink ليس عطلًا بل **كنية**: الحساب الأول يسكن الـ home الافتراضي و`codex-pro`
> اسم ثانٍ له. رأيت الملفين يموتان معًا فحسبت التصميم معطوبًا، والحقيقة أن جلسة
> الحساب الأول أُبطلت فحسب.

**الدرس الباقي وهو حقيقي**: لأن `~/.codex` و`~/.codex-pro` اعتماد واحد، لا تتوقّع نجاة
`codex-pro` إذا مات `~/.codex` — وهذا ما حدث بالضبط. الناجي كان `~/.codex-mdoosh` لأنه
اعتماد مستقل (Jul 24، `config.toml` كامل + الوكلاء الستة، وردّ `OK` حيًّا)، وهو ما أنقذ الموقع.

**2026-07-27 18:18 — المالك نفّذ `CODEX_HOME=~/.codex codex login` بنجاح**؛ الاعتماد
الأساسي حيّ مجددًا ومُختبَر (`OK`). يبقى قرار إرجاع `CODEX_HOME` إليه (وهو أصلًا داخل
`ReadWritePaths`) مع إبقاء سطر `.codex-mdoosh` كمخرج طوارئ.

### اللغم ٤ — `ProtectHome` يبطل أي CODEX_HOME بديل

تحويل `CODEX_HOME` إلى الحساب السليم **لم يكفِ** — بقي `nonzero_exit`:

```
ProtectHome=read-only
ReadWritePaths=%h/.codex      ← الوحيد المسموح بالكتابة فيه
```

كامل `$HOME` للقراءة فقط داخل sandbox الخدمة إلا ما يُذكر صراحة. وCodex يكتب جلسات
وسجلات وsqlite تحت `CODEX_HOME`. لهذا كان نفس الأمر ينجح من الطرفية ويفشل داخل الخدمة.
**العلاج**: `ReadWritePaths=%h/.codex-mdoosh`.

### لماذا لم يكشفها شيء

الموقع كان يردّ `200` والمعرض يخدم دروسه — لأن الصفحة والدروس الـ golden **لا تستدعي
موديلًا إطلاقًا**. التوليد وحده كان ميتًا، و`/healthz` يعرض الإعداد لا صلاحية الاعتماد.

> **درس**: `/healthz` يجب أن يفحص صلاحية اعتماد Codex، لا أن يطبع أسماء الموديلات فقط.
> فحص جاهزية الاعتماد كان سيكشف اللغمين ٢ و٤ فورًا.

### التصحيح الذي يلزم تسجيله

نسبتُ فشل الـ 5 ثوانٍ أولًا إلى النشر ووصفته بـ"انحدار جديد". **كان خطأ**: النشر بريء،
والعطل اعتماد منتهٍ بين 17:08 و18:10.

---

## 13. لماذا لا ينجح كل سؤال — حدود المظروف (تحليل بطلب المالك)

فرضية المالك: *"شروط التحقق والإصلاح مقيّدة جدًا؛ لا يمكن توليد محاكاة لكل سؤال، فكل
تجربة قد تحتاج ما لا تحتاجه غيرها."* — **مُثبتة بالكود**.

| القدرة | ما يعلنه الـ schema | ما يُقبل فعلًا |
|---|---|---|
| `actor_archetype` | 8 خيارات | **5** — `ray_bundle`/`wave_medium`/`particle_flow` مرفوضة: *"until the phase A2 command primitives are available"* |
| `motion_model` | `parameter_driven`·`time_driven`·`cyclic` | **2** — `time_driven` *"not available yet"* |
| هندسة علمية وقت التشغيل | — | `{circle, particle_flow, wave}` (`scene_geometry.py:9`) |

المشكلة ليست الضيق، بل **الضيق غير المتّسق**: الـ schema يدعو الموديل لاختيار قدرات
يرفضها المُصدِر بعدها. يختار، ثم يُعاقَب على قبول الدعوة.

**وينطبق على سؤال القمر مباشرة**: أطوار القمر جوهرها `orbital_pair` يتحرك بالزمن،
و`time_driven` مؤجَّل ⇒ الموديل مُجبَر على تحويل ظاهرة زمنية إلى بارامتر. ولهذا جاء
الجواب: *"تمثل θ زاوية موضعه في مداره"*.

### التوجيه مُقنَّن لا ضعيف

```python
tests/test_codex_backend_live.py:309:   assert len(prompt) <= 4_800
```
و`9e785bb` يوثّق ضغطه من 5024 إلى **4798** حرفًا — **فسحة حرفين**. كل قاعدة فنية جديدة
يجب أن تطرد أخرى.

### الدليل القاطع — الـ golden القمري نفسه

`out/evidence/goldens/moon_phases-*.json`:

| المحاولة | النتيجة |
|---|---|
| 1 | مرفوضة — `primary_parameter_reference_mismatch` · *"العقد العلمي أرخى من أن يُرقّى"* |
| 2 | مرفوضة — `learner_copy_placeholder` · *"الحقول العربية رموز سِتّ عشرية"* |
| 3 | **مقبولة** — بعد مراجعة بشرية بـ 12+ معيارًا |

زائد `scripts/refresh_pinned_moon_geometry.py` — هندسة **مثبَّتة بسكربت مخصّص**.
أي أن المحاكاة القمرية الوحيدة الناجحة كلّفت ثلاث محاولات وإنسانًا. توقُّع توليدها
من الطلب الأول بلا إشراف غير واقعي بنيويًا.

### أرخص رافعة تالية: الفشل السريع

لو صُنِّف السؤال عند مرحلة الفهم كخارج المظروف (يحتاج `time_driven`)، لقيل ذلك في
**ثوانٍ** بدل حرق 181 ثانية للوصول إلى رفض محتوم.

### خيط لم يُتحقَّق منه

`fragment_generation` يدعم `ellipse` ويوجّه الموديل إليه صراحةً، بينما
`scene_geometry.py:9` لا يذكره. **لم أتحقق** أن الطبقتين تصفان نفس فضاء الأجسام،
وفشل 17:08 كان `invalid_state`/`invalid_relation` لا `unsupported_scientific_geometry`
⇒ خيط يستحق فحصًا واحدًا، لا استنتاجًا.

---

## 11. أوامر التحقّق المستخدمة

```bash
# الطوبولوجيا
ls -l /proc/20594/cwd                      # → /home/dev/laysh-local-preview
systemctl --user cat laysh.service         # → 3 drop-ins، الأخير يفوز
systemctl --user list-units | grep -i tunnel

# فجوة النشر
git -C /home/dev/laysh show 9e785bb:server/pipeline.py \
  | diff - /home/dev/laysh-local-preview/server/pipeline.py   # → متطابق
git -C /home/dev/laysh diff --stat

# التتبّع
journalctl --user -u laysh.service --since "60 min ago" \
  | grep -iE "reject|verif|heal|error"

# الاختبارات
cd /home/dev/laysh && .venv/bin/python -m pytest tests/ -q
```
