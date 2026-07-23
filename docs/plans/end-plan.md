============================================================
MASTER EXECUTION DIRECTIVE
Laysh — Verified Generative Scientific Discovery Engine
============================================================

المستودع:

~/laysh

الوثيقة المعتمدة التي يجب مراجعتها وتحديثها:

docs/build-spec/g7-continuation/SCIENTIFIC-DISCOVERY-VALUE-PLAN.md

ابحث أيضًا داخل المستودع عن الوثيقة أو المعمارية المشار إليها باسم:

MODEL-DRIVEN-SIMS-V2

واعتبر أحدث متطلبات مالك المشروع في هذا الأمر هي المرجع الأعلى عند وجود تعارض مع وثائق أقدم.

هذه مهمة تنفيذية وليست جلسة اقتراحات.

المطلوب:

1. افحص المشروع كاملًا.
2. افهم الموجود فعليًا قبل اتخاذ القرارات.
3. حدّث الوثيقة المعتمدة لتصبح Runbook إنتاجيًا متكاملًا.
4. أصلح العيوب الحرجة الحالية.
5. نفّذ الأساسات الهندسية ذات الأولوية التي تسمح بالتوليد الديناميكي الموثوق.
6. لا تدّعِ اكتمال أي جزء لم يجتز اختبارات قبول قابلة للتشغيل.
7. لا تحاول بناء كل العلوم في Patch عشوائي واحد.
8. نفّذ النظام كمنصة قابلة للتوسع، مع مسارات صادقة للأسئلة التي لا يمكن محاكاتها.
9. لا تكتفِ بكتابة خطة مستقبلية إذا كانت الأساسات المطلوبة قابلة للتنفيذ الآن داخل المستودع.
10. لا تخفّض معايير الدقة من أجل إنهاء المهمة بسرعة.

============================================================
0. قواعد العمل داخل المستودع
============================================================

ابدأ بالترتيب التالي:

1. شغّل git status وافحص التغييرات الحالية.
2. لا تستخدم:
   - git reset --hard
   - git clean
   - checkout يلغي تغييرات المستخدم
   - حذف ملفات لا تملكها المهمة
3. لا تعدّل إعداد Default Model أو إعدادات MCP.
4. الخطأ التالي ليس جزءًا من هذه المهمة:

invalid transport in mcp_servers.openaiDeveloperDocs

إذا تعطل MCP الخاص بوثائق OpenAI:

- لا توقف المهمة.
- لا تغيّر ملف الإعداد الخاص به.
- استخدم الحقائق والمراجع الموثقة في نهاية هذا الأمر.
- سجّل فقط ما يحتاج تحققًا لاحقًا إذا لم تستطع الوصول إلى الوثائق.

5. لا تستنتج API model slug من اسم ظاهر في واجهة TUI مثل:

gpt-5.6-sol ultra

استخدم Model ID وإعدادات reasoning المعتمدة داخل تكامل المشروع، ولا تغيّرها إلا إذا كانت المهمة تتطلب تكامل API فعليًا وبعد التحقق من صحة الحقول.

6. إذا كانت هناك وكلاء أو عمليات أخرى تعمل:

- لا تسمح لوكيلين بالكتابة في الملف نفسه بالتزامن.
- أنشئ File Ownership Map مؤقتة.
- استخدم Worktree أو فروعًا منفصلة للمهام المستقلة إذا كانت بنية المشروع تسمح.
- اجعل وكيل دمج واحدًا مسؤولًا عن الملفات المشتركة.
- يمكن تشغيل مراجعات Read-Only بالتوازي.
- لا تشغّل Multi-Agent Theater يكرر التحليل ويستهلك الرصيد.
- لا تعدّل web/app.js أو server/app.py أو web/index.html بالتزامن مع وكيل آخر يملكها.
- ادمج تغييرات التعريب واللغة بصورة تسلسلية لا تصادمية.

7. افحص قبل التعديل:

- بنية المشروع.
- الوثائق.
- Schemas.
- API routes.
- قاعدة البيانات.
- نظام النتائج.
- المحاكيات.
- الاختبارات.
- أدوات البناء.
- نظام اللغات.
- الأمن.
- إمكانية الوصول.
- أي كاش أو Queue أو Worker قائم.

8. ميّز داخل التحليل بين:

- Existing
- Partial
- Missing
- Conflicting
- Proposed
- Deprecated

9. لا تخترع مكونات غير موجودة.
10. لا تقل إن النظام Production-Ready إلا إذا أثبتت ذلك الاختبارات ومعايير القبول.

============================================================
1. ترتيب الأولويات الملزم
============================================================

عند التعارض، اتخذ القرار وفق الترتيب التالي:

1. صحة العلم ومنع التضليل.
2. الأمان والخصوصية.
3. تطابق الحساب والرسم والحركة.
4. تقديم نتيجة مفيدة للمستخدم.
5. إعادة الاستخدام ومنع التوليد المكرر.
6. موثوقية التشغيل.
7. سرعة النتيجة.
8. تقليل التكلفة.
9. إمكانية الوصول واللغات.
10. الجمال البصري.
11. إبراز قدرات GPT-5.6.

لا يجوز إبراز قوة GPT-5.6 على حساب صحة العلم أو الخصوصية أو صدق المنتج.

============================================================
2. العقد الأساسي للمنتج
============================================================

المستخدم يكتب فقط بلغة طبيعية واحدًا من الآتي:

- سؤالًا من نوع "ليش؟".
- سؤالًا من نوع "كيف؟".
- طلب تجربة.
- وصف ظاهرة.
- ملاحظة من الحياة اليومية.
- سيناريو "ماذا يحدث لو؟".
- مفهومًا يريد رؤيته وفهمه.
- سؤالًا بالعربية أو الإنجليزية أو العربية العامية المفهومة.

أمثلة:

"ليش السفينة المصنوعة من الحديد تطفو؟"

"اعمل لي تجربة توضح تأثير المقاومة على التيار."

"ماذا يحدث لو أصبحت جاذبية الأرض نصف قوتها؟"

"ليش القمر يتغير شكله؟"

"Why does metal feel colder than wood?"

لا يُطلب من المستخدم أن يحدد:

- القانون.
- المعادلات.
- النموذج العلمي.
- المتغيرات.
- الوحدات.
- Solver.
- Renderer.
- عناصر التحكم.
- الاختبارات.
- المصادر.
- تخطيط الشاشة.
- طريقة الشرح.

يتولى Laysh الباقي.

التدفق النهائي:

User Curiosity
→ Sanitize Ephemerally
→ Understand Scientific Intent
→ Resolve Existing Result
→ Retrieve Evidence
→ Select or Compose Scientific Model
→ Build Lesson Specification
→ Build Simulation Specification
→ Compile Through Trusted Runtime
→ Validate
→ Repair with Bounded Counterexamples
→ Publish or Fall Back Safely
→ Save Sanitized Verified Result
→ Reuse in Future Questions

الوعد الصحيح للمنتج:

"كل سؤال يحصل على أفضل نتيجة علمية مفيدة يمكن إثباتها، ولا تظهر محاكاة للمستخدم إلا إذا اجتازت التحقق."

ممنوع استخدام وعد مثل:

"نولّد محاكاة صحيحة لأي سؤال مهما كان."

============================================================
3. ليست المنصة ستة أمثلة
============================================================

المحاكيات الست:

- أطوار القمر
- الطفو
- البندول
- الدائرة الكهربائية
- طبقة الصوت
- تعاقب الليل والنهار

ليست نطاق المنتج النهائي.

تعامل معها على أنها:

- Golden Reference Simulations
- Regression Fixtures
- نماذج مرجعية لعائلات علمية
- أمثلة لتصميم SimulationSpec
- اختبارات لمعمارية Model-Driven Sims
- بذور لـModel Registry
- معيار لجودة الرسم والشرح وإمكانية الوصول

يجب أن يستطيع الحكام طرح أسئلة غير محفوظة حرفيًا.

السؤال الجديد يجب أن يسلك أحد المسارات:

R0 — Exact Reuse
نتيجة مطابقة موثقة موجودة.

R1 — Language or Wording Reuse
نفس التجربة بصياغة أو لغة مختلفة.

R2 — Parameter Adaptation
نفس النموذج مع Preset أو قيم مختلفة.

R3 — Trusted Composition
تركيب تجربة من Primitives وعائلات نماذج موثقة.

R4 — New Specification over Trusted Model
سؤال جديد يحتاج SimulationSpec جديدًا فوق Solver موثوق.

R5 — Novel Scientific Model
نموذج علمي جديد فعلًا، يخضع لأشد مسار تحقق ولا ينشر تلقائيًا إذا لم يتوفر Oracle مستقل كافٍ.

R6 — Verified Answer Only
إجابة موثقة عندما لا تضيف المحاكاة قيمة أو لا يمكن إثباتها.

R7 — Safe Fallback
سؤال غامض أو ضار أو خارج النطاق أو غير قابل للتحقق.

الحكام يجب أن يحصلوا دائمًا على نتيجة مفيدة، لكن ليس بالضرورة على محاكاة مزيفة.

============================================================
4. تصحيح الأدلة والادعاءات داخل الوثائق
============================================================

صحح أي نص داخل المستودع يستخدم الأدلة التالية بصورة غير دقيقة.

أولًا: SimBench

المعلومة الصحيحة:

- الإصدار الأول من SimBench في 2024 سجّل أعلى Pass@1 قدره 12.8% في إعداد محدد لتوليد Digital Twins باستخدام PyChrono.
- هذه النتيجة دليل تاريخي على صعوبة توليد كود محاكاة حر.
- ليست نتيجة لـGPT-5.6.
- ليست حدًا عامًا لكل أنواع المحاكاة.
- لا يجوز كتابة "أقوى النماذج الحالية لا تتجاوز 13%" دون تحديد الإصدار والسياق.
- الإصدار الحالي من الورقة نُقح في 2026 ووسع نطاق النماذج.

استخدم الاستنتاج الصحيح فقط:

"توليد كود محاكاة حر من LLM ثم الاعتماد على نجاحه من أول محاولة مسار غير موثوق، ولذلك يحتاج Laysh إلى مواصفات مقيدة، ومحركات موثقة، وبوابات تحقق قابلة للتنفيذ."

ثانيًا: From Prompts to Properties

المعلومة المدعومة:

- 30–32% من الحلول المدروسة التزمت جزئيًا فقط بخصائص الصحة.
- 18–23% فشلت في الخصائص.
- استخراج الخصائص نفسه قد يفوّت 9–13% من القيود.

الاستنتاج الصحيح:

- الاختبارات التقليدية وحدها قد تبالغ في تقدير صحة المخرجات.
- Property-Based Testing مهم.
- لكن الخصائص التي يولدها LLM ليست Oracle كاملًا.
- يجب أن تمتلك Model Registry خصائص مستقلة ومراجعة، لا أن يكتب النموذج الكود والاختبار من الافتراض نفسه ثم يصادق على نفسه.

ثالثًا: PropTest

الاستنتاج الصحيح:

- اختبارات الخصائص يمكن أن تحسن البرمجة البصرية وتكشف أخطاء منطقية لا تظهر كأخطاء Syntax أو Runtime.
- الدراسة تتعلق ببرمجة بصرية لمهام Vision-Language، وليست إثباتًا مباشرًا لصحة محاكيات الفيزياء.
- استخدمها كدعم للمنهج، لا كادعاء أن Laysh مضمون الصحة.

رابعًا: OpenAI API

صحح الادعاء السابق الذي يقول إن CFG غير متاح.

المتاح رسميًا:

- Structured Outputs عبر JSON Schema صارم.
- Strict schemas لأدوات Function Calling.
- Custom Tools يمكن تقييد مدخلاتها بقواعد CFG بصيغ Lark أو Regex في التكاملات المدعومة.
- Programmatic Tool Calling في GPT-5.6 للعمليات المقيدة كثيفة الأدوات.
- Tool Search لتأجيل تحميل الأدوات غير المطلوبة.
- Explicit Prompt Caching في GPT-5.6.
- Persisted Reasoning في التكاملات المدعومة.
- reasoning.effort حتى max في GPT-5.6.
- reasoning.mode = pro للمهام التي تستحق تكلفة وزمنًا أعلى.

لكن اتخذ القرارات التالية:

1. SimulationSpec الأساسي يكون JSON Schema صارمًا.
2. المعادلات لا تكون JavaScript حرًا.
3. مثّل المعادلات كـTyped Expression AST داخل JSON.
4. استخدم CFG فقط إذا احتجت Patch DSL أو صيغة نصية صغيرة لا يناسبها JSON.
5. tool_choice: "required" يعني أن النموذج يجب أن يستدعي أداة؛ لا يعني أن النص سيلتزم تلقائيًا بـJSON Schema.
6. استخدم Structured Outputs أو Strict Function Schema لضمان البنية.
7. لا تستخدم tool_choice: "required" عالميًا؛ استخدمه فقط عندما تكون الأداة إلزامية في تلك المرحلة.
8. verbosity يتحكم في شكل وطول الإخراج، وليس دليلًا على صحة العلم.

خامسًا: Prompt Caching

المعلومات الصحيحة:

- GPT-5.6 يدعم Explicit Cache Breakpoints.
- يمكن كتابة ما يصل إلى أربع نقاط Cache جديدة في الطلب وفق الوضع.
- TTL المدعوم حاليًا للآلية الجديدة هو 30 دقيقة كحد أدنى.
- Cache Writes في GPT-5.6 تُحاسب بسعر 1.25× من الإدخال غير المخزن.
- Cache Reads مخفضة.
- الكاش لا يضمن نفس الناتج ولا يحول الاستجابة إلى استجابة ثابتة.

القرار:

لا تشغّل Prompt Caching لمجرد أنه متاح.

فعّله فقط عندما:

Expected Reuse Savings > Cache Write Cost

وسجّل:

- cache_write_tokens
- cached_tokens
- hit rate
- miss rate
- reuse window
- cost saved
- cost wasted by unused cache writes

============================================================
5. العطل المؤكد في محاكاة القمر
============================================================

راجع التطبيق الفعلي قبل التعديل، لكن تعامل مع التحليل التالي كعيب مثبت ما لم تكن الشيفرة قد تغيرت:

cx = 0.30w

orbitRx = max(54, min(0.205w, 0.28h))

sunX = max(27, cx - orbitRx - 0.072w)

sunY = cy

sunR = max(20, min(46, 0.050w))

moonR = max(7, min(17, 0.018w))

عند:

w = 700

ومع ارتفاع يسمح بأن يكون:

orbitRx = 143.5

فإن:

cx = 210

leftmostMoonCenterX = 210 - 143.5 = 66.5

unclampedSunX = 210 - 143.5 - 50.4 = 16.1

sunX after clamp = 27

sunR = 35

moonR = 12.6

sun horizontal interval = [-8, 62]

moon horizontal interval at leftmost orbit point = [53.9, 79.1]

overlap = 62 - 53.9 = 8.1px

النتيجة:

- التداخل حتمي في هذه الحالة.
- الشمس نفسها تخرج جزئيًا خارج اللوحة.
- Math.max يحمي مركز الشمس جزئيًا لكنه ينتهك العلاقة الهندسية مع المدار.
- المشكلة ليست Prompt.
- المشكلة تصميم Layout يعتمد على Clamps مستقلة بلا Post-Validation.

لا تصلح العطل بتحريك الشمس رقمًا ثابتًا فقط.

نفّذ Layout Contract حقيقيًا.

Hard Constraints:

1. كل جسم يجب أن يقع داخل Safe Viewport Bounds ما لم يصرّح المشهد بقص مقصود.
2. الجسمان اللذان يملكان overlapPolicy = "forbid" يجب ألا يتقاطعا.
3. الجسمان اللذان يملكان overlapPolicy = "scientific_occlusion" يمكن أن يتداخلا فقط في الحالات التي يصرح بها النموذج.
4. contactPolicy = "required" يسمح بالتلامس عندما يكون التلامس جزءًا من النموذج.
5. المشابك Clamps لا تعتبر ناجحة حتى تعاد مراجعة جميع القيود بعدها.
6. لا يجوز حماية حافة الشاشة بكسر علاقة علمية أو مكانية أخرى بصمت.

صيغة عدم تداخل دائرتين:

(dx² + dy²) >= (r1 + r2 + clearance)²

يجب أن يكون clearance Token من Design System، وليس Magic Number متناثرًا.

Layout Strategy:

1. جرّب Wide Scene Template.
2. إذا لم تتحقق القيود، جرّب Compact Scene Template.
3. إذا لم تتحقق، استخدم Stacked أو Split Scene.
4. قلّل العناصر الزخرفية أولًا.
5. لا تقلّل حجم العنصر العلمي تحت الحد المقروء.
6. لا تنشر مشهدًا غير قابل للحل.
7. إذا تعذر التخطيط، استخدم Visual Fallback صادقًا بدل Geometry خاطئة.

اختبارات القمر:

- اختبر زوايا المدار الحرجة.
- اختبر المسار كاملًا أو احسب أدنى مسافة تحليليًا إن أمكن.
- اختبر أربعة Golden Viewports على الأقل.
- إضافة إلى ذلك استخدم Property-Based Viewport Generation عبر نطاق مستهدف من العروض والارتفاعات.
- اختبر العربية والإنجليزية.
- اختبر RTL وLTR.
- اختبر Zoom.
- اختبر Reduced Motion.
- اختبر Resize أثناء التشغيل.
- اختبر Device Pixel Ratio المختلف إذا كان يؤثر في Canvas.
- لا تعتمد على Screenshot يدوي واحد.

لا تجعل القاعدة العامة:

"لا يتداخل أي جسمين مطلقًا."

لأن بعض الدروس، مثل الكسوف أو التلامس أو التصادم، تحتاج تداخلًا أو حجبًا مقصودًا.

القاعدة الصحيحة:

"لا يحدث تداخل غير مصرح به في Visual Contract."

============================================================
6. عطل القراءة الميتة
============================================================

ابحث عن استخدامات مثل:

toFixed(2)

خصوصًا في القالب المشترك أو Readout Formatter.

المشكلة:

- يمكن أن تتغير القيمة العلمية بينما يبقى النص المعروض ثابتًا.
- هذا يجعل أداة التحكم تبدو بلا أثر.
- وقد تنجح الحسابات بينما تفشل التجربة التعليمية.

لا تصلح المشكلة بتغيير:

toFixed(2)

إلى:

toFixed(3)

فقط.

أنشئ Measurement Formatting System موحدًا.

يجب أن يعتمد على:

- الوحدة.
- حجم الخطوة.
- مدى المتغير.
- الحساسية.
- الدقة العلمية المناسبة.
- Significant Digits.
- Notation عادية أو علمية.
- اللغة.
- اتجاه العرض.
- إمكانية الوصول.

استخدم Intl.NumberFormat أو طبقة مناسبة لبنية المشروع بدل تنسيقات متناثرة.

أضف MeasurementFormatSpec يحتوي مفاهيميًا على:

- unit
- minimumResolution
- significantDigits
- maxDecimals
- scientificNotationThreshold
- locale
- accessibleLabel
- displayTolerance

اختبارات القراءة:

1. إذا تغير Observable بمقدار يتجاوز displayTolerance، يجب أن تتغير القراءة.
2. القيمة المعروضة عند تحليلها يجب أن تقع ضمن خطأ التقريب المسموح.
3. القراءة المرئية وARIA description يجب أن تتفقا.
4. لا تعرض دقة زائفة أكثر من دقة النموذج.
5. لا تجعل Endpoint Test هو الاختبار الوحيد.
6. اختبر خطوة قريبة، ومنتصف المدى، والطرفين، والحالات الحرجة.
7. إذا كانت العلاقة دورية وقد تتساوى النهايتان، استخدم نقاطًا داخلية.
8. إذا كان المتغير يجب ألا يؤثر في Observable معين، سجّل ذلك كـInvariant بدل اعتباره عطلًا.

============================================================
7. استبدال التعليمات بثوابت قابلة للتنفيذ
============================================================

المبدأ الأساسي:

Prompts improve the average.
Executable contracts protect the minimum.

ابنِ النظام على أربعة عقود قابلة للتنفيذ:

A. Scientific Contract

يحتوي على:

- الوحدات.
- الأبعاد.
- المتغيرات.
- الحدود.
- المعادلات.
- الافتراضات.
- الحالات المعروفة.
- Invariants.
- Expected Relations.
- Metamorphic Relations.
- Numerical Tolerances.

B. Visual Contract

يحتوي على:

- Scientific State Bindings.
- Viewport bounds.
- overlapPolicy.
- contactPolicy.
- occlusionPolicy.
- z-order.
- label anchors.
- camera rules.
- graph bindings.
- responsive modes.
- RTL/LTR behavior.
- Reduced Motion behavior.

C. Evidence Contract

يحتوي على:

- الادعاءات الأساسية.
- المصدر لكل ادعاء.
- إصدار المصدر.
- تاريخ الاسترجاع.
- نطاق الادعاء.
- التعارضات.
- الافتراضات.
- هل المصدر تعليمي أو مرجعي أو بيانات متغيرة.

D. Lesson Contract

يحتوي على:

- answer.
- prediction.
- controlled variables.
- observation.
- explanation.
- transfer task.
- age band.
- language.
- misconceptions.
- pedagogical limits.

لا ينشر Artifact إذا فشل عقد إلزامي.

============================================================
8. المعمارية المعتمدة: Model-Driven Sims V2
============================================================

لا يكون المسار:

User Question
→ GPT
→ Free-form HTML/CSS/JavaScript
→ Browser

المسار المعتمد:

User Question
→ ScientificIntent
→ Result Resolver
→ Evidence Bundle
→ LessonSpec
→ SimulationSpec
→ Trusted Model Registry
→ Trusted Compiler
→ Trusted Solver
→ Semantic Scene Graph
→ Professional Renderer
→ Verification Pipeline
→ Result Artifact
→ Results Registry

GPT-5.6 هو:

Scientific Reasoning and Orchestration Layer

وليس:

Scientific Truth Authority

============================================================
9. ScientificIntent
============================================================

استخدم GPT-5.6 عبر Structured Output صارم لتحويل السؤال إلى ScientificIntent مستقل عن اللغة.

يحتوي على الأقل على:

- schemaVersion
- normalizedPublicQuestion
- locale
- domain
- subdomain
- conceptId
- phenomenon
- causalIntent
- entities
- independentVariables
- dependentVariables
- observables
- requestedScenario
- learningObjective
- ageBand
- likelyMisconceptions
- assumptionsNeeded
- simulationSuitability
- safetyClass
- freshnessRequirement
- candidateModelFamilies
- ambiguityClass
- clarificationNeeded

لا تخزن السؤال الخام ضمن ScientificIntent.

إذا كان السؤال غامضًا:

- لا تطرح سؤال توضيح إلا إذا كان الغموض يمنع نتيجة صحيحة.
- إن أمكن اختيار تفسير معقول، اذكر الافتراض بصورة واضحة.
- لا تغيّر معنى السؤال سرًا.

============================================================
10. حماية الخصوصية مع دعم إعادة الاستخدام
============================================================

السؤال الخام:

- يعالج مؤقتًا فقط.
- لا يسجل في Logs.
- لا يرسل إلى Telemetry غير ضرورية.
- لا يحفظ في Results DB.
- لا يظهر في Error Reports.
- لا يستخدم كعنوان عام قبل التنظيف.
- لا يرتبط بهوية المستخدم.

قبل التخزين:

1. اكتشف البيانات الشخصية.
2. أزلها أو عممها.
3. أنشئ canonicalPublicQuestion.
4. أنشئ ScientificIntent.
5. أنشئ Exact Fingerprint باستخدام HMAC بمفتاح خادم فوق نص منقح، لا SHA خامًا لسؤال شخصي منخفض الاحتمالات.
6. أنشئ Embedding من ScientificIntent المنقح، لا من النص الشخصي الخام.
7. احذف النص الخام من الذاكرة عندما ينتهي Job بقدر ما تسمح به المنصة.
8. اختبر أن Logs وExceptions لا تحتويه.

يمكن حفظ:

- canonicalPublicQuestion.
- sanitized aliases.
- ScientificIntent.
- experimentSignature.
- model and artifact metadata.
- locale variants.
- results and receipts.

لا يمكن حفظ:

- سؤال خام شخصي.
- هوية السائل.
- تاريخ تعلم دائم.
- ملف سلوكي.
- Chain of Thought.

============================================================
11. Results Resolution قبل أي توليد مرتفع التكلفة
============================================================

نفّذ Pipeline بالترتيب:

1. Sanitized Exact HMAC Match.
2. Sanitized Alias Match.
3. Canonical ScientificIntent Match.
4. Hybrid Retrieval:
   - lexical search
   - semantic search
5. Model Family Compatibility.
6. Variable Compatibility.
7. Assumption Compatibility.
8. Learning Objective Compatibility.
9. Safety and Freshness Compatibility.
10. Version Compatibility.

التشابه الدلالي يسترجع Candidates فقط.

لا يُعتبر دليلًا كافيًا لإعادة الاستخدام.

مثال يجب دمجه:

- ليش الخشب يطفو؟
- لماذا لا تغرق قطعة الخشب؟
- Why does wood float?

مثال يجب عدم دمجه تلقائيًا:

- لماذا يطفو الخشب؟
- لماذا تطفو سفينة فولاذية؟

السؤالان مرتبطان بعائلة الطفو، لكن درس السفينة يحتاج:

- الكثافة المتوسطة.
- شكل الهيكل.
- الإزاحة.
- حجم الهواء.
- فرقًا بين كثافة المادة وكثافة الجسم الكلية.

============================================================
12. Canonical Experiment Signature
============================================================

أنشئ Canonical JSON بترتيب حقول حتمي، ثم Hash لمفاهيم مثل:

- conceptId
- phenomenon
- causalIntent
- modelFamily
- controlledVariables
- observedVariables
- units
- assumptions
- boundaryConditions
- learningObjective
- scientificSourceVersion
- modelVersion
- solverVersion
- simulationSpecVersion

استخدم experimentSignature في:

- deduplication.
- singleflight.
- distributed locking.
- content-addressed storage.
- cache keys.
- versioning.
- invalidation.
- revalidation.

إذا وصل طلبان متكافئان بالتزامن:

- لا تبدأ عمليتي توليد.
- أنشئ Job واحدًا.
- اجعل الطلبين يشتركان في النتيجة.
- لا تنشئ Result rows مكررة.
- لا تدفع تكلفة النموذج مرتين.

============================================================
13. SimulationSpec بدل الكود الحر
============================================================

GPT-5.6 لا يولد JavaScript حرًا في المسار الطبيعي.

يولد SimulationSpec مطابقًا لـJSON Schema صارم.

المواصفة تحتوي على الأقل على:

- schemaVersion
- conceptId
- modelFamily
- modelVersion
- solverReference
- entities
- parameters
- stateVariables
- controlledVariables
- observedVariables
- units
- expressionAst
- constants
- constraints
- initialConditions
- boundaryConditions
- supportedRanges
- assumptions
- invariants
- expectedRelations
- knownCases
- metamorphicRelations
- numericalTolerance
- sceneSpec
- stateBindings
- lessonSpec
- evidenceRefs
- safetyClass
- accessibilitySpec
- validationPlan

تمثيل المعادلات:

- استخدم Typed Expression AST.
- اسمح فقط بعمليات Allowlisted.
- لا تستخدم eval.
- لا تستخدم Function constructor.
- لا تسمح باستيراد كود ديناميكي.
- لا تسمح للنموذج بإدخال أسماء Functions غير مسجلة.
- تحقق من الوحدات على عقد AST.
- تحقق من Domain لكل دالة.

مثال أنواع Nodes:

- constant
- variable
- add
- subtract
- multiply
- divide
- power
- sin
- cos
- sqrt
- min
- max
- clamp
- piecewise

كل Node يجب أن يملك:

- type
- operands
- outputDimension
- sourceReference عند الحاجة

============================================================
14. Model Registry
============================================================

أنشئ سجلًا لعائلات النماذج العلمية.

كل Model Family يملك:

- id
- version
- domain
- scientific scope
- solver
- supported variables
- units
- supported ranges
- assumptions
- invariants
- expected relations
- known cases
- property generators
- visual primitives
- permitted scene patterns
- safety class
- evidence versions
- validation suite
- deprecation status

ابدأ بتحويل المحاكيات الست إلى عائلات أو Golden Fixtures، لكن لا تجعل السجل محصورًا بها.

أمثلة عائلات محتملة:

- buoyancy
- simple_pendulum
- basic_dc_circuit
- sound_pitch_frequency
- moon_phase_geometry
- earth_rotation_day_night
- linear_motion
- force_balance
- heat_transfer
- basic_wave
- reflection_refraction
- orbit_geometry

لا تضف عائلة جديدة لمجرد أن الاسم مختلف.

أضفها فقط إذا تغير النموذج العلمي فعلًا.

============================================================
15. التحكم في عدد المتغيرات
============================================================

تجربة الطالب الأساسية تسمح بمتغير أو متغيرين قابلين للتغيير.

السبب:

- تقليل الحمل المعرفي.
- وضوح العلاقة السببية.
- سهولة الهاتف.
- سهولة التحقق.
- سهولة المقارنة.

يمكن للنموذج الداخلي امتلاك متغيرات أكثر، لكن واجهة الطالب تعرض المتغيرين الأكثر فائدة تعليميًا.

اختيار المتغيرات يتم وفق:

- learning objective
- causal relevance
- observable effect
- safety
- visual clarity
- sensitivity
- range stability

لا تعرض Variable لا يؤثر في أي Observable ذي معنى.

============================================================
16. Effect Contracts بدل قاعدة "كل معامل يغير البكسلات"
============================================================

القاعدة القديمة واسعة وغير صحيحة.

بعض المتغيرات:

- يجب أن تغيّر نتيجة عددية.
- بعضها يجب أن يغيّر حركة.
- بعضها يجب أن يغيّر رسمًا.
- بعضها متوقع ألا يؤثر في Observable معين، مثل كتلة البندول في نموذج الزاوية الصغيرة.

لكل Controlled Variable أضف EffectContract:

- affectsObservables
- expectedRelation
- minimumScientificDelta
- visualEffectRequired
- minimumVisualDelta
- invariantObservables
- validRange

أنواع expectedRelation:

- increasing
- decreasing
- inverse
- proportional
- threshold
- periodic
- bounded
- nonMonotonic
- invariant
- qualitativeOnly

اختبار Sensitivity:

1. غيّر المتغير داخل المجال.
2. تحقق من تغير Observable المعلن فوق Tolerance.
3. إذا visualEffectRequired = true، تحقق من تغير Semantic Visual State أو البكسلات فوق حد مضبوط.
4. لا تعتمد على Pixel Diff فقط.
5. تحقق أولًا من State Binding.
6. استخدم Pixel/Visual Regression كطبقة إضافية.

============================================================
17. Semantic Scene Graph
============================================================

لا تجعل GPT يحدد كل بكسل.

أنشئ Scene Graph دلاليًا من Primitives موثقة.

أمثلة:

- ScientificBody
- FluidSurface
- VectorArrow
- Trajectory
- OrbitPath
- Waveform
- CircuitNode
- CircuitEdge
- LightRay
- AngleArc
- MeasurementGauge
- NumericReadout
- SynchronizedGraph
- Annotation
- ComparisonPanel
- MicroscopicPanel
- MacroscopicPanel
- Observer
- Source

كل عنصر علمي Claim-Bearing يجب أن يمتلك State Binding.

أمثلة:

pendulum.angle <- state.theta

moon.position <- state.orbitalPosition

forceArrow.length <- scale(state.forceMagnitude)

currentMeter.value <- state.current

wave.path <- state.samples

waterline <- state.submergedHeight

الرسم النهائي:

ScientificState(t) = Solver(Model, Parameters, t)

VisualFrame(t) = Renderer(
    ScientificState(t),
    SceneSpec,
    DesignTokens,
    Locale,
    AccessibilityProfile
)

يمكن وجود زخرفة، لكن:

- لا تمثل قيمة علمية.
- لا توحي بعلاقة غير موجودة.
- لا تتحرك بطريقة تناقض النموذج.
- تصنف بوضوح كـdecorative.

============================================================
18. Professional Scientific Visual System
============================================================

أنشئ أو وحّد Laysh Scientific Design System.

يحتوي على:

- typography tokens
- Arabic typography
- English typography
- spacing scale
- scientific color roles
- contrast rules
- graph tokens
- vector arrow tokens
- measurement tokens
- camera presets
- line-width scale
- annotation rules
- surface and material presets
- mobile breakpoints
- motion rules
- reduced-motion alternatives
- RTL/LTR layout rules

لا تجعل GPT يختار قيمًا عشوائية لكل درس.

GPT يختار فقط مفاهيم مثل:

- scenePattern
- scientific emphasis
- camera intent
- required measurements
- annotation density

ويطبق Renderer التصميم الموثق.

Scene Patterns المقترحة:

- Causal Sandbox
- World + Graph
- Compare A/B
- Force Explorer
- Field Explorer
- Cycle / Orbit
- Circuit Workbench
- Wave Laboratory
- Microscopic / Macroscopic
- Before / During / After

استخدم 2D افتراضيًا عندما يحقق الهدف.

استخدم 3D فقط عندما:

- يضيف فهمًا لا يمكن تحقيقه بوضوح في 2D.
- يعمل على الهاتف.
- لا يضر بإمكانية الوصول.
- يملك اختبارات صحيحة.
- لا يضاعف التكلفة بلا فائدة.

يمكن اختيار:

- SVG للرسوم الدلالية والنصوص.
- Canvas للحركة عالية التحديث.
- WebGL/Three.js للمشاهد ثلاثية الأبعاد الضرورية.
- Hybrid renderer عند الحاجة.

لا تفرض تقنية قبل فحص الموجود في المستودع.

============================================================
19. Auto-Layout Constraint Solver
============================================================

لا تعتمد على نسب ومشابك مستقلة فقط.

نفّذ Layout Engine له:

Hard Constraints:

- viewport safety
- non-overlap policies
- contact policies
- clipping rules
- minimum readable size
- control hit area
- label/control separation
- graph/scene separation
- required object visibility

Soft Constraints:

- balance
- visual hierarchy
- symmetry
- preferred spacing
- preferred camera
- annotation density

إذا كان المستودع JavaScript/TypeScript، قيّم استخدام Constraint Solver مناسب أو نفّذ Solver صغيرًا محدد النطاق.

لا تضف Dependency كبيرة دون مبرر.

Layout Modes:

- wide
- compact
- stacked
- split
- reduced-detail

خوارزمية:

1. احسب Semantic Bounds.
2. طبّق Hard Constraints.
3. حسّن Soft Constraints.
4. اختبر الحالات القصوى للحركة.
5. اختبر جميع Viewport Modes.
6. إذا فشل، انتقل إلى Layout Mode آخر.
7. لا تستخدم Clamp ثم تفترض النجاح.
8. نفّذ Post-Constraint Validation.

Label Collision Resolver:

- اكتشف Bounding Box intersections.
- استخدم Alternative Anchors.
- استخدم Leader Lines عند الحاجة.
- أخفِ الشرح الثانوي على الهاتف.
- لا تخفِ Observable أساسيًا.
- لا تحرك المحاور العلمية بسبب RTL بطريقة تقلب معنى الفيزياء.

Camera Auto-Fit:

- احسب bounds عبر الحالات الحرجة.
- احتفظ بهامش.
- لا تجعل الجسم يخرج عند تغيير المتغير.
- لا تسبب Camera Motion دوارًا أو حركة زائدة.
- وفر Reduced Motion mode ثابتًا.

============================================================
20. Visual Quality Loop
============================================================

أنشئ Key Frames للحالات:

- initial
- middle
- minimum valid
- maximum valid
- scientifically critical states

شغّل Visual Linter حتميًا لفحص:

- clipping
- unintended overlap
- label collisions
- text density
- contrast
- viewport overflow
- off-canvas objects
- graph/scene mismatch
- tiny objects
- obscured controls
- RTL/LTR errors
- scientific axis inversion
- mobile layout
- reduced-motion fallback

لا تستدعِ GPT-5.6 لمراجعة كل مشهد.

استخدم GPT-5.6 Vision Review فقط عندما:

- المشهد جديد فعليًا.
- Visual Linter يفشل ولا يستطيع Auto-Layout إصلاحه.
- توجد مشكلة في hierarchy أو readability لا يمكن التعبير عنها بقاعدة حتمية.
- مرحلة التطوير تجمع Evals، وليس لكل تشغيل مستخدم.

أرسل إلى النموذج فقط:

- Key Screenshot.
- SceneSpec المختصر.
- تقرير Visual Linter.
- Design rubric.
- العمليات المسموح بها.

واطلب ScenePatch محدودًا، لا إعادة بناء الدرس.

لا تجعل تقييم GPT البصري بوابة الصحة العلمية.

============================================================
21. Counterexample-Guided Verified Synthesis
============================================================

اعتمد خوارزمية إصلاح موجهة بالأمثلة المضادة.

التدفق:

Candidate SimulationSpec
→ Deterministic Validators
→ Minimal Counterexample
→ Structured Failure Report
→ Constrained Patch by GPT-5.6
→ Revalidate
→ Publish or Safe Fallback

مثال Failure Report:

- failedContract
- variableValues
- expectedProperty
- actualResult
- numericalDifference
- tolerance
- relevantSpecPath
- allowedPatchPaths
- forbiddenChanges

استخدم Shrinking في Property-Based Testing لإيجاد أبسط حالة تفشل.

ممنوع:

- إعادة إرسال المستودع كاملًا عند كل فشل.
- مطالبة النموذج بإعادة كتابة المحاكاة كلها.
- تغيير الافتراضات سرًا لتمرير الاختبار.
- حذف الاختبار الفاشل دون إثبات أنه خاطئ.
- حلقات إصلاح غير محدودة.

الحد الافتراضي:

- محاولة إنشاء أساسية واحدة.
- محاولة إصلاح واحدة لمسار Adapt/Compose.
- محاولتا إصلاح كحد أقصى لمسار Novel Specification.
- أي حد نهائي يجب أن يكون Configurable ومقاسًا بالـEvals.

بعد الفشل:

- Answer Only أو Related Verified Result.
- لا Artifact مكسور.
- لا ادعاء VERIFIED.
- خزّن Negative Result داخليًا لمنع إعادة المحاولة المكلفة بنفس الشروط، مع Version وExpiry مناسبين.

============================================================
22. Scientific Verification Pipeline
============================================================

نفّذ الاختبارات من الأرخص إلى الأعلى تكلفة.

Gate 1 — Schema

- strict schema validation
- required fields
- no unknown fields where prohibited
- version compatibility
- valid references

Gate 2 — Static Safety

- no raw JavaScript execution
- no eval
- no Function constructor
- no unapproved imports
- allowed AST operations only
- resource limits

Gate 3 — Units and Dimensions

- dimensional consistency
- unit conversions
- constants
- operand dimensions
- output dimensions

Gate 4 — Equation and Domain

- division by zero
- invalid square root
- invalid log domains
- NaN
- Infinity
- unstable ranges
- discontinuities
- solver compatibility

Gate 5 — Known Cases

- analytical solutions
- reference values
- manually verified fixtures
- Golden model outputs

Gate 6 — Invariants

أمثلة:

- فترة البندول البسيط لا تعتمد على الكتلة ضمن فرضياته.
- قانون أوم في النموذج الأومي.
- حفظ الشحنة عند انطباقه.
- توازن الوزن والطفو في حالة الاتزان.
- علاقات أطوار القمر الهندسية.
- ثبات القيم التي يجب أن تبقى ثابتة.

Gate 7 — Property-Based Testing

- random valid inputs
- edge cases
- shrink failing input
- typed generators
- no invalid domain generation

Gate 8 — Metamorphic Testing

أمثلة:

- مضاعفة طول البندول تزيد الفترة بعامل يقارب sqrt(2) ضمن فرضية الزاوية الصغيرة.
- عند ثبات الجهد، زيادة المقاومة لا تزيد التيار في النموذج الأومي.
- زيادة كثافة السائل تقلل الجزء المغمور لجسم طافٍ ثابت الكتلة والحجم.
- تغيير اللغة لا يغير القيم العلمية.
- تغيير حجم الشاشة لا يغير الحساب.

Gate 9 — Cross-Oracle

عندما يمكن:

- analytical solver مقابل numerical solver
- independent implementation
- trusted reference table
- source data

Gate 10 — Visual-State Coupling

- كل Observable مرئي يطابق State.
- الرسم والقراءة متطابقان.
- الحركة ليست Timeline منفصلًا.
- تغيير المتغير يحدث الأثر المعلن.
- لا يوجد Dead Control.
- لا يوجد Decorative Motion يدعي نتيجة علمية.

Gate 11 — Browser Runtime

- target browsers
- phone
- desktop
- resize
- pause/resume
- restart
- download
- standalone artifact
- no critical console errors
- no memory leak واضح
- no runaway frame loop

Gate 12 — Accessibility

- keyboard
- focus order
- labels
- screen-reader description
- zoom 200%
- reduced motion
- contrast
- non-color cues
- descriptive alternative for dynamic result

Gate 13 — Security

- CSP
- sandbox
- network denied by default
- CPU/time limits
- memory limits
- loop protection
- dependency allowlist
- artifact integrity
- no secrets
- no user-data persistence

Gate 14 — Pedagogy

- answer appropriate for 13+
- prediction optional and does not leak answer unnecessarily
- observation describes what changed
- explanation links cause to result
- transfer task differs from original example
- analogy labeled as analogy
- assumptions visible
- uncertainty calibrated

Gate 15 — Publication

لا ينتقل Artifact إلى VERIFIED أو PUBLIC إلا بعد نجاح كل البوابات الإلزامية لمساره.

============================================================
23. درجات الثقة والنشر
============================================================

Tier A — Existing Verified Artifact

- إعادة استخدام فورية.
- لا توليد علمي.
- لا إعادة تحقق إلا إذا أصبح Stale.

Tier B — Verified Model + New Preset

- Range and property tests فقط حسب الحاجة.
- لا إعادة بناء Solver.

Tier C — Composition of Verified Primitives

- Full composition validation.
- يمكن النشر آليًا إذا كل العقود حتمية ونجحت.

Tier D — New SimulationSpec over Verified Solver

- Full validation.
- bounded repair.
- يمكن النشر إذا يوجد Oracle كافٍ.

Tier E — Truly Novel Scientific Model

- لا تنشر محاكاة عامة تلقائيًا إذا لا يوجد Independent Oracle.
- قدم Answer Only.
- ضع النموذج في Quarantine.
- يمكن ترقيته بعد مراجعة أو إضافة عقود مستقلة.

لا تستخدم Confidence رقمية زائفة بلا Calibration.

============================================================
24. Scientific RAG
============================================================

لا تعتمد على ذاكرة النموذج فقط.

أنشئ Source Registry يملك:

- sourceId
- publisher
- title
- sourceType
- domain
- version
- publicationDate
- retrievalDate
- authorityClass
- ageSuitability
- license
- supportedClaims
- supersededBy
- status

التدفق:

ScientificIntent
→ Retrieve Approved Evidence
→ Rank by Authority and Relevance
→ Build Compact Evidence Bundle
→ GPT-5.6 Planning
→ Claim-to-Source Mapping

لا ترسل مكتبة المصادر كاملة.

أرسل فقط المقاطع المطلوبة.

إذا اختلفت المصادر:

- لا تخفِ التعارض.
- اختر النموذج التعليمي المناسب.
- وضح الافتراض.
- لا تعلن يقينًا غير موجود.

إذا كانت المعلومة متغيرة زمنيًا:

- استخدم Source Date.
- لا تحفظها كحقيقة أبدية.
- أضف Freshness Policy.
- أعد التحقق عند انتهاء الصلاحية.

============================================================
25. Results Registry
============================================================

كل نتيجة ناجحة تصبح أصلًا قابلًا لإعادة الاستخدام.

أنواع النتائج:

- VERIFIED_SIMULATION
- VERIFIED_INTERACTIVE_MODEL
- VERIFIED_ANSWER_ONLY
- VERIFIED_REFERENCE_LESSON
- QUARANTINED_MODEL
- INTERNAL_FAILED_BUILD
- STALE
- DEPRECATED
- INVALIDATED
- SUPERSEDED

حقول مفاهيمية:

- resultId
- publicSlug
- canonicalPublicQuestion
- scientificIntentId
- conceptId
- domain
- modelFamily
- experimentSignature
- resultType
- localeVariants
- answer
- lessonSpec
- simulationSpec
- sceneSpec
- artifactHash
- downloadArtifactHash
- evidenceRefs
- assumptions
- limitations
- verificationStatus
- validationReceiptId
- sourceVersions
- modelVersion
- solverVersion
- compilerVersion
- rendererVersion
- schemaVersion
- validatorVersion
- createdAt
- updatedAt
- lastValidatedAt
- staleAt
- reuseCount
- generationPath
- parentResultId
- modelCalls
- inputTokens
- outputTokens
- cacheReadTokens
- cacheWriteTokens
- estimatedCost
- failureClass

عند سؤال مكافئ:

- لا تنشئ Artifact جديدًا.
- أضف Alias أو Locale Variant.
- زد reuseCount.
- أعد نفس Simulation Core.
- لا تعِد الاختبارات العلمية بسبب تغيير اللغة فقط.

قسم النتائج يجب أن يدعم:

- search
- semantic discovery
- domain filters
- language filters
- verification status
- stable result URL
- play
- share
- standalone download
- validation receipt
- assumptions
- limitations
- source list
- last validation date
- related experiments

لا تعرض INTERNAL_FAILED_BUILD للعامة.

============================================================
26. Versioning and Invalidation
============================================================

Artifact موثق ليس صحيحًا للأبد بلا إصدار.

اربط كل Result بإصدارات:

- source
- scientific model
- solver
- SimulationSpec schema
- compiler
- renderer
- validators
- design system
- policy

إذا تغير Dependency جوهري:

- علّم النتيجة STALE.
- أعد التحقق مرة واحدة.
- لا تعِد التوليد لكل مستخدم.
- أنشئ Version جديدًا.
- احتفظ بسجل التدقيق.
- لا تكتب فوق الإصدار السابق بصمت.

============================================================
27. استغلال GPT-5.6 في المهام الصحيحة
============================================================

استخدم GPT-5.6 في:

- فهم الأسئلة العامية والثنائية اللغة.
- استخراج ScientificIntent.
- اكتشاف المقصود خلف الصياغة.
- اختيار Model Family.
- تحليل الفرق بين سؤالين متشابهين.
- تصميم LessonSpec.
- إنتاج SimulationSpec.
- اقتراح Scientific Contracts للنموذج الجديد.
- تفسير Counterexample.
- إنتاج Patch محدود.
- بناء شرح مناسب لعمر 13+.
- توضيح الافتراضات والحدود.
- مراجعة مشهد بصري جديد عند فشل اللينتر الحتمي.
- تنظيم Tools في Workflow معقد عند الحاجة.

لا تستخدم GPT-5.6 في:

- Hash.
- Cache lookup.
- Schema validation.
- Unit conversion المعروف.
- Solver execution.
- Browser testing.
- Exact deduplication.
- Artifact serving.
- Slug creation.
- Content-addressed storage.
- إعادة نتيجة موجودة.
- تنسيق رقمي حتمي.
- كل Frame من المحاكاة.

============================================================
28. Model Routing
============================================================

ضع Model Router قابلًا للتهيئة، ولا تنثر أسماء النماذج في الشيفرة.

المسارات المقترحة:

Exact Reuse:
- صفر استدعاءات توليدية.

Language Variant:
- استرجاع ترجمة موجودة.
- عند عدم وجودها استخدم نموذجًا اقتصاديًا من عائلة GPT-5.6 إذا أثبتت Evals كفايته.

Intent Classification:
- استخدم أقل مستوى يحقق جودة مقاسة.
- لا تستخدم pro/max افتراضيًا.

Trusted Composition:
- GPT-5.6 Sol مع reasoning متوسط أو مرتفع وفق التعقيد.

Novel Specification:
- GPT-5.6 Sol مع reasoning مرتفع.
- استخدم xhigh أو max فقط إذا أظهرت Evals مكسبًا يستحق التكلفة.

High-Risk Novel Model:
- يمكن استخدام reasoning.mode = pro إذا كان متاحًا في التكامل وكانت الجودة أهم من الزمن والتكلفة.
- لا تستخدمه تلقائيًا لكل سؤال.

Repair:
- نفس Job context.
- أرسل Failure Report فقط.
- Patch محدود.

Final Explanation:
- verbosity منخفض أو متوسط.
- لا ترسل سياق المحاكاة كاملًا إذا كان LessonSpec كافيًا.

كل Route يجب أن يسجل:

- whyModelWasCalled
- model
- reasoning settings
- input tokens
- output tokens
- duration
- result usefulness

============================================================
29. Structured Outputs وCustom Grammar
============================================================

استخدم:

- JSON Schema strict لـScientificIntent.
- JSON Schema strict لـLessonSpec.
- JSON Schema strict لـSimulationSpec.
- JSON Schema strict لـScenePatch.
- Strict Tool Schemas للأدوات.

استخدم Custom CFG فقط عند وجود حاجة حقيقية مثل:

- Patch DSL صغير.
- تعبير نصي مقيّد.
- صيغة لا يناسبها JSON.

لا تستخدم CFG بدل JSON Schema دون فائدة.

يفضل تمثيل المعادلات AST داخل JSON لأنه:

- أسهل للتحقق.
- أسهل لفحص الوحدات.
- أكثر أمانًا.
- أسهل للإصدار.
- أسهل لإنتاج Hash حتمي.
- لا يحتاج Parser حرًا واسعًا.

============================================================
30. Programmatic Tool Calling
============================================================

إذا كان التكامل يدعمه، استخدم Programmatic Tool Calling في Workflows المحدودة مثل:

- استرجاع Candidates.
- تصفيتها.
- تحميل Model Family.
- تشغيل unit checks.
- تشغيل known cases.
- تشغيل property tests.
- جمع Counterexamples.
- تلخيص تقرير صغير.

الفائدة المطلوبة:

- إبقاء المخرجات الوسيطة الكبيرة خارج دورة النموذج.
- تقليل الأدوار.
- تقليل Tokens.
- تنفيذ شروط وحلقات محدودة داخل Runtime معزول.

لا تستخدمه إذا:

- التكامل الحالي لا يدعمه.
- Workflow بسيط.
- سيضيف طبقة تعقيد بلا مكسب.
- يحتاج قرارًا علميًا جديدًا بعد كل أداة.

نفّذ Feature Detection وFallback تقليديًا.

============================================================
31. Tool Search
============================================================

لا ترسل أدوات كل المجالات مع كل سؤال.

مثال:

سؤال طفو:
- fluid tools
- density tools
- unit tools
- buoyancy model tools

سؤال دائرة:
- circuit tools
- electrical units
- graph tools

سؤال فلك:
- orbital geometry
- lighting geometry
- scene layout

استخدم Tool Search أو Registry Loading مؤجلًا إذا كان التكامل يدعمه.

سجّل Tokens التي وفرها.

============================================================
32. Prompt Caching الصحيح
============================================================

قسّم Prompt Prefix إلى طبقات مستقرة:

Breakpoint A:
- product safety policy
- privacy policy
- output contract

Breakpoint B:
- ScientificIntent schema
- common tool definitions

Breakpoint C:
- domain-specific model registry summary

Breakpoint D:
- SimulationSpec and validation rules عند الحاجة

العناصر المتغيرة تأتي بعد آخر Breakpoint:

- user input
- retrieved evidence
- candidate models
- failure report

استخدم Versioned prompt_cache_key، مثل مفهوم:

laysh:{workflow}:{policyVersion}:{schemaVersion}:{domainShard}

لا تضع سؤال المستخدم في المفتاح.

لا تستخدم نفس المفتاح لترافيك غير متشابه.

فعّل الكاش فقط عندما يتوقع أن تقرأ البادئة مرات تكفي لتعويض Write Cost.

أضف Break-Even Evaluator.

إذا:

subsequentExpectedReads <= thresholdNeededToRecoverWriteCost

فلا تكتب Cache صريحًا.

قِس ولا تفترض.

============================================================
33. Persisted Reasoning
============================================================

إذا كان مدعومًا:

- استخدم Responses API.
- استخدم previous_response_id أو reasoning context داخل Generation Job نفسه.
- استفد منه بين:
  - planning
  - tool calls
  - repair

لا تستخدم reasoning state كذاكرة مستخدم دائمة.

لا تحتفظ به بعد انتهاء الحاجة.

لا تسجّل Chain of Thought.

لا تعرضه.

إذا لم يكن مدعومًا، استخدم Compact Job State منظمًا.

============================================================
34. تقليل زمن النتيجة
============================================================

صمّم تجربة Progressive Result.

عند Cache Hit:

- أعد النتيجة مباشرة.
- لا تبدأ Job توليد.

عند New Build:

1. اعرض حالة مفهومة.
2. استخرج جوابًا موثقًا ومختصرًا.
3. لا تنتظر المحاكاة لإظهار أول فائدة إذا كان الجواب قد اجتاز Evidence Gate.
4. ابنِ المحاكاة كـJob قابل للمتابعة.
5. انشرها عند VERIFIED فقط.
6. إذا فشلت، أبقِ جواب Answer Only.

حالات واجهة مفهومة:

- نفهم السؤال.
- نبحث في المختبر.
- وجدنا تجربة موثقة.
- نجهز تجربة جديدة.
- نتحقق من العلم.
- التجربة جاهزة.
- أعددنا لك شرحًا موثقًا بدل تجربة غير مثبتة.

لا تعرض:

- أسماء الوكلاء.
- Tokens.
- تفاصيل Chain of Thought.
- Stack traces.
- ادعاء "Verified" قبل نجاح البوابات.

تحسينات الأداء:

- precompile verified model families
- cache compiled artifacts
- content-addressed storage
- warm browser validation workers بحدود معقولة
- lazy-load renderer modules
- Web Worker للحسابات عند الملاءمة
- CDN أو static asset caching
- asynchronous revalidation
- offline batching للترجمات أو إعادة التحقق غير العاجلة عند توفره
- avoid full repository context
- compact evidence bundle
- bounded tool outputs
- singleflight
- negative cache

لا تضع أرقام SLA اعتباطية قبل قياس Baseline.

============================================================
35. Cost Budget لكل مسار
============================================================

R0 Exact Reuse:
- Model generation calls = 0

R1 Existing Artifact, New Locale:
- 0 إذا Locale موجودة
- استدعاء اقتصادي واحد فقط عند الحاجة

R2 New Preset:
- 0 غالبًا
- deterministic range validation

R3 Trusted Composition:
- Planner/Spec call واحد
- Repair call واحدة كحد افتراضي

R4 New Spec over Verified Solver:
- Planner/Spec call واحد
- حتى محاولتي Repair مضبوطة

R5 Novel Model:
- high-quality planning
- strict budget
- no public simulation without independent validation

Visual Review:
- 0 في المسار الطبيعي
- استدعاء واحد فقط عند فشل حتمي غير قابل للإصلاح أو Novel Scene

لكل Job:

- maxModelCalls
- maxInputTokens
- maxOutputTokens
- maxRepairAttempts
- maxToolRuntime
- timeout
- maxEstimatedCost
- cancellation policy
- fallback policy

لا تعِد المحاولة بنفس السياق والمدخلات بعد فشل متطابق.

============================================================
36. Multi-Agent Policy
============================================================

داخل Runtime المنتج:

لا تستخدم عدة Agents لمجرد النقاش.

يمكن فصل الأدوار منطقيًا:

- Scientific Intent Planner
- Lesson Designer
- Simulation Spec Generator
- Repair Role
- Optional Independent Reviewer

لكن افتراضيًا يمكن لـGPT-5.6 Orchestrator واحد استخدام أدوات متعددة.

استدعِ Independent Reviewer فقط إذا:

- نموذج جديد.
- تعارض مصادر.
- فشل سابق.
- انخفاض ثقة.
- مجال عالي المخاطر.
- لا يوجد Oracle قوي.
- تغيير معادلات جوهري.

داخل CLI والتطوير:

- Subagents read-only للمراجعة ممكنة.
- كتابة متوازية فقط في ملفات مستقلة.
- One writer per shared file.
- لا تشغل ثلاثة وكلاء يراجعون الشيء نفسه ثم تجمع كلامهم.

============================================================
37. اللغة الافتراضية والتعارض مع Arabic-First
============================================================

متطلب المالك الحالي:

- الإنجليزية هي اللغة الافتراضية للـJudge/Demo build.
- العربية تظل First-Class وليست ترجمة ثانوية.
- المنتج يدعم العربية والإنجليزية بالكامل.

لا تضع اللغة الافتراضية في ثلاثة ملفات مختلفة.

أنشئ Locale Resolver واحدًا.

ترتيب تحديد اللغة:

1. Explicit URL or route locale.
2. Explicit user choice داخل الجلسة.
3. Deployment configuration.
4. Browser preference إذا تقرر استخدامه.
5. Safe fallback.

للنسخة الحالية:

DEFAULT_LOCALE = en

لكن اجعلها Configuration وليست Hardcode متناثرًا.

اضبط:

- document.lang
- document.dir
- text resources
- number formatting
- accessibility labels
- API locale
- generated lesson locale

من مصدر واحد.

العربية:

- RTL للواجهة.
- لا تعكس محاور الفيزياء أو اتجاه الزمن أو الإحداثيات بسبب RTL.
- لا تعكس الرسم البياني تلقائيًا.
- اختبر النص الطويل.
- اختبر الأرقام والوحدات.
- اختبر المزج بين العربية والرموز العلمية.

راجع المواضع التي ذُكرت سابقًا:

- web/index.html
- web/app.js
- server/app.py

لكن تحقق من أرقام الأسطر الحالية ولا تعتمد على أرقام قديمة.

لا تدخل في تعارض مع وكيل التعريب الجاري.

============================================================
38. الأمان والعزل
============================================================

المسار الطبيعي لا ينفذ كودًا يولده المستخدم أو النموذج.

إذا كان هناك Novel Free-Code Tier تجريبي:

- يكون Disabled افتراضيًا.
- Quarantine only.
- AST/static scanning.
- no network.
- no filesystem.
- no secrets.
- no cookies.
- no clipboard.
- no parent DOM.
- strict CSP.
- isolated Worker أو iframe.
- resource quota.
- execution timeout.
- infinite-loop protection.
- dependency allowlist.
- artifact integrity hash.
- لا ينشر للعامة دون مراجعة كاملة.

الأفضل:

SimulationSpec
→ Trusted Compiler
→ Trusted Runtime

وليس Free JavaScript.

============================================================
39. تجربة المستخدم
============================================================

المخرج النهائي يتكون حسب نوع النتيجة من:

- عنوان.
- جواب مختصر.
- توقع اختياري.
- متغير أو متغيرين.
- تجربة أو نموذج تفاعلي.
- ملاحظة.
- تفسير.
- تطبيق جديد.
- افتراضات.
- حدود.
- مصادر.
- Validation Receipt.
- مشاركة.
- تنزيل.
- رابط ثابت.

يجب التمييز بصريًا بين:

- Scientific Simulation
- Interactive Explanatory Model
- Answer Only

لا تسمِ رسمًا توضيحيًا "محاكاة" إذا لم يكن ناتجًا من نموذج علمي.

============================================================
40. Validation Receipt
============================================================

كل نتيجة عامة تملك Receipt قابلًا للقراءة.

يحتوي على:

- result type
- verification status
- scientific model
- model version
- source versions
- tests executed
- tests passed
- warnings
- assumptions
- limitations
- supported parameter ranges
- last validated
- artifact hash
- validator versions

لا تعرض تفاصيل أمنية حساسة.

لا تستخدم عبارة:

"صحيح 100%"

استخدم وصفًا مثل:

"اجتاز الاختبارات المحددة ضمن الافتراضات والحدود المعروضة."

============================================================
41. Data Model
============================================================

راجع قاعدة البيانات الحالية، ثم حافظ مفاهيميًا على الكيانات التالية:

- ScientificIntent
- QuestionAlias
- ScientificConcept
- Source
- SourceVersion
- ModelFamily
- ModelVersion
- ScientificContract
- SimulationSpec
- SceneSpec
- SimulationPreset
- Result
- ResultVersion
- ResultArtifact
- LocaleVariant
- ValidationRun
- ValidationCheck
- ValidationReceipt
- GenerationJob
- GenerationAttempt
- ReuseDecision
- CostRecord
- SafetyDecision
- DependencyVersion
- NegativeBuildCache

أضف:

- unique experimentSignature
- unique artifactHash
- idempotency constraints
- indexes for exact and semantic retrieval
- foreign keys
- status transitions
- retention policy
- invalidation policy
- no raw-question field
- version fields
- audit fields without PII

لا تفرض أسماء الجداول حرفيًا إذا كان المشروع يملك Convention أفضل.

============================================================
42. API Contracts
============================================================

تكيف مع بنية المشروع، لكن غطّ المسؤوليات التالية:

POST /api/discover

- يستقبل السؤال مؤقتًا.
- لا يحفظه خامًا.
- يدعم idempotency.
- يعيد:
  - immediate result إذا Reuse
  - trace/job id إذا Build

GET /api/discover/{traceId}

- حالة Job.
- لا يعيد بيانات داخلية حساسة.

GET /api/results

- search and filters.

GET /api/results/{resultId}

- result payload.

GET /api/results/{resultId}/receipt

- verification receipt.

GET /api/results/{resultId}/download

- standalone artifact.

POST /api/internal/results/resolve

- reuse resolver.

POST /api/internal/simulations/compile

- trusted compilation.

POST /api/internal/validations/run

- validation pipeline.

POST /api/internal/results/{resultId}/revalidate

- dependency-driven revalidation.

POST /api/internal/results/{resultId}/invalidate

- controlled invalidation.

لكل API وثّق:

- request schema
- response schema
- auth
- idempotency
- rate limit
- privacy behavior
- status transitions
- timeout
- cache behavior
- error codes
- retry policy

============================================================
43. Observability
============================================================

أنشئ Trace من الإدخال حتى النتيجة.

سجّل دون السؤال الخام:

- traceId
- sanitized fingerprint
- scientificIntentId
- reuse path
- cache state
- model route
- tool calls
- validation gates
- counterexamples
- repair count
- artifact id
- result id
- timing by stage
- cost
- fallback reason

Dashboards أو Metrics:

- useful outcome rate
- exact reuse rate
- semantic reuse rate
- false reuse rate
- duplicate generation rate
- new build rate
- answer-only rate
- verification pass rate
- repair success rate
- scientific error escape rate
- unverified publication rate
- cost per reused result
- cost per new verified result
- cache write/read efficiency
- time to first useful answer
- time to verified simulation
- browser pass rate
- accessibility pass rate
- visual contract failure rate
- raw-question retention violations

Release-blocking metrics:

- Unverified Simulation Publication > 0
- Scientific Error Escape في Golden tests
- Raw Question Persistence Violation
- Duplicate Artifact Creation for same signature
- Broken Golden Simulation
- Failed Critical Accessibility Gate

لا تضع أهدافًا رقمية غير مبنية على Baseline.

============================================================
44. Judge Evaluation Suite
============================================================

ابنِ مجموعة Hidden/Unseen لا يعتمد عليها التوليد.

الفئات:

1. أسئلة عربية فصحى.
2. أسئلة بصيغة "ليش".
3. لهجات مفهومة.
4. أخطاء إملائية معقولة.
5. أسئلة إنجليزية.
6. خلط عربي وإنجليزي.
7. إعادة صياغة للسؤال نفسه.
8. ترجمة السؤال نفسه.
9. أسئلة متشابهة لفظيًا مختلفة علميًا.
10. أسئلة قابلة لإعادة الاستخدام.
11. أسئلة تحتاج Preset جديدًا.
12. أسئلة تحتاج Composition.
13. أسئلة لا تصلح لمحاكاة.
14. أسئلة مبنية على افتراض خاطئ.
15. أسئلة غامضة.
16. أسئلة خارج النطاق.
17. أسئلة خطرة.
18. Prompt injection.
19. طلبات تحاول إجبار النظام على إعلان VERIFIED.
20. عدة طلبات متكافئة متزامنة.
21. Viewport changes.
22. RTL/LTR.
23. Zoom.
24. Reduced motion.
25. Downloaded standalone artifact.

Deduplication Test Group:

- ليش الخشب يطفو؟
- لماذا لا تغرق قطعة الخشب؟
- Why does wood float?

يجب أن تعيد نفس الجوهر العلمي.

False-Reuse Group:

- لماذا يطفو الخشب؟
- لماذا تطفو السفينة الفولاذية؟

يجب ألا تعتبرهما Artifact واحدًا دون تكييف علمي مناسب.

Pendulum Group:

- هل كتلة البندول تغير زمنه؟
- لماذا البندول الثقيل ليس أبطأ؟
- What affects a pendulum’s period?

يجب أن يستخدم Model Family نفسه مع اختلاف Lesson Objective.

Concurrency Test:

أرسل الصيغ المتكافئة بالتزامن.

المطلوب:

- Generation Job واحد.
- Artifact واحد.
- عدة Responses مرتبطة به.
- لا تكلفة مكررة.

============================================================
45. خطة التنفيذ المرحلية
============================================================

لا تنفذ المشروع ككتلة واحدة غير قابلة للمراجعة.

Phase 0 — Repository Audit

المخرجات:

- current architecture
- file map
- gap analysis
- conflicts
- risk register
- traceability matrix
- implementation decision record

Exit Criteria:

- لا توجد افتراضات غير مدعومة عن الوضع الحالي.
- المتطلبات مرتبطة بملفات أو مكونات.

Phase 1 — Critical Correctness Fixes

نفّذ:

- إصلاح Layout القمر بالقيود.
- اختبارات overlap/clipping.
- Measurement Formatter.
- Dead readout tests.
- Locale Resolver المركزي.
- DEFAULT_LOCALE configurable = en للنسخة الحالية.
- عدم تعارض ملفات التعريب.

Exit Criteria:

- العطلان لهما Regression Tests.
- لا يوجد Hardcode لغوي متضارب.
- Golden tests تمر.

Phase 2 — Intent and Results Foundation

نفّذ:

- ScientificIntent schema.
- sanitized processing.
- no raw-question persistence.
- Results Registry.
- exact HMAC reuse.
- idempotency.
- result pages أو APIs حسب الموجود.

Exit Criteria:

- إعادة السؤال نفسه لا تستدعي توليدًا.
- لا سؤال خام في DB أو Logs.

Phase 3 — Semantic Resolver

نفّذ:

- aliases.
- hybrid retrieval.
- candidate compatibility.
- experimentSignature.
- false-reuse tests.
- singleflight/distributed lock.
- negative cache.

Exit Criteria:

- paraphrases reuse correctly.
- false reuse benchmark passes.
- concurrent duplicate generation prevented.

Phase 4 — SimulationSpec and Model Registry

نفّذ:

- strict schemas.
- typed expression AST.
- ScientificContract.
- VisualContract.
- Model Registry.
- convert six reference simulations to Golden model-driven fixtures.
- trusted compiler skeleton.

Exit Criteria:

- لا يوجد مساران مستقلان للحساب والرسم.
- كل Golden sim derives visuals from scientific state.

Phase 5 — Verification Pipeline

نفّذ:

- units.
- dimensions.
- known cases.
- invariants.
- property-based tests.
- metamorphic tests.
- visual contracts.
- browser/accessibility/security tests.
- receipts.

Exit Criteria:

- لا Artifact يصل إلى VERIFIED دون pipeline.
- failure produces Counterexample.

Phase 6 — GPT-5.6 Orchestration

نفّذ:

- Structured Output calls.
- model routing.
- evidence bundle.
- Tool contracts.
- bounded repair.
- optional programmatic tools.
- optional tool search.
- prompt cache evaluation.
- cost ledger.

Exit Criteria:

- model calls measurable and bounded.
- GPT cannot bypass validators.
- malformed output rejected safely.

Phase 7 — Dynamic New Questions

نفّذ:

- Reuse.
- Adapt.
- Compose.
- New Spec.
- Answer Only.
- Safe Fallback.
- saving verified results.

Exit Criteria:

- unseen questions receive useful outcomes.
- supported model families can produce new verified experiences.
- unsupported questions do not create fake simulations.

Phase 8 — Production Hardening

نفّذ:

- observability.
- rate limiting.
- worker reliability.
- retries.
- rollback.
- invalidation.
- revalidation.
- backups.
- abuse handling.
- cost dashboards.

Phase 9 — Judge Readiness

نفّذ:

- hidden benchmark.
- bilingual.
- unseen.
- adversarial.
- concurrency.
- cost.
- visual.
- mobile.
- accessibility.
- demo with no hard-coded question dependency.

============================================================
46. المطلوب تنفيذه في هذه الجولة
============================================================

نفّذ على الأقل ما يلي، ما لم يثبت الفحص أنه منفذ بصورة صحيحة مسبقًا:

1. مراجعة المستودع كاملًا.
2. تحديث SCIENTIFIC-DISCOVERY-VALUE-PLAN.md بكل القرارات المتوافقة مع الواقع.
3. توثيق تصحيح الأدلة البحثية والرسمية.
4. إصلاح عطل القمر.
5. إضافة اختبارات تمنع:
   - unintended overlap
   - clipping
   - clamp relation violation
6. إصلاح نظام القراءة الميتة.
7. إنشاء Formatter موحد واختباراته.
8. توحيد Locale Resolver.
9. جعل English هو Configured Default للنسخة الحالية دون إضعاف العربية.
10. البحث عن أي حساب مزدوج بين Model وRenderer وإزالته أو تسجيله كخطر P0.
11. إنشاء أو تثبيت schemas الأساسية إذا لم توجد:
    - ScientificIntent
    - SimulationSpec
    - ScientificContract
    - VisualContract
12. إنشاء أول Vertical Slice حقيقي يمر من:
    Question
    → Intent
    → Reuse Resolver
    → Model
    → Render
    → Validate
    → Result Save
13. اختر Vertical Slice من أقوى عائلة موجودة فعليًا، لا تبنِ Demo وهميًا منفصلًا.
14. أضف Regression Tests للمحاكيات الست.
15. أضف Traceability Matrix.
16. شغّل الاختبارات الموجودة والجديدة.
17. راجع Git Diff.
18. لا تغيّر ملفات خارج النطاق بلا سبب موثق.

إذا كان تنفيذ كل المراحل في تشغيل واحد غير واقعي:

- لا تختصر الجودة.
- أكمل Foundation وVertical Slice.
- اترك المستودع في حالة قابلة للتشغيل.
- حدّث Runbook بخطوات تالية دقيقة مرتبطة بمعايير قبول.
- لا تستخدم TODO عام مثل "أضف الذكاء لاحقًا".
- لا تدّعِ اكتمال النظام العام.

============================================================
47. معايير القبول النهائية
============================================================

لا تعتبر المهمة مكتملة إلا إذا تحققت المعايير الملائمة للنطاق المنفذ:

1. المستخدم يكتب سؤالًا أو طلب تجربة فقط.
2. النظام يستخرج ScientificIntent منظمًا.
3. لا يُطلب من المستخدم اختيار القانون أو المعادلات.
4. البحث عن Result موجود يحدث قبل التوليد.
5. السؤال نفسه لا يولّد نتيجة مرتين.
6. الترجمة أو إعادة الصياغة لا تعيد بناء المحاكاة.
7. اختلاف علمي جوهري لا يعاد استخدامه خطأ.
8. طلبان متزامنان لا ينشئان Artifactين.
9. السؤال الخام لا يظهر في DB.
10. السؤال الخام لا يظهر في Logs.
11. كل Result عام منقح وغير شخصي.
12. كل محاكاة عامة لها Validation Receipt.
13. كل Claim-Bearing Visual مرتبط بـScientific State.
14. لا يوجد حساب منفصل للعرض وآخر للنتيجة.
15. متغيرات التحكم تملك EffectContracts.
16. Invariants لا تُفسر كعطل.
17. القراءة لا تبقى ميتة عند تغير ذي معنى.
18. الشمس والقمر لا يتداخلان في مشهد يحظر التداخل.
19. Layout لا يخرج العناصر خارج الشاشة.
20. Clamps لا تكسر العلاقات بصمت.
21. Viewport property tests تمر.
22. المحاكيات الست تمر كـGolden Regressions.
23. RTL/LTR يعملان.
24. English default يأتي من Config.
25. العربية First-Class.
26. لوحة المفاتيح تعمل.
27. Zoom 200% يعمل.
28. Reduced Motion يعمل.
29. الهاتف يعمل.
30. فشل المحاكاة لا يمنع جوابًا مفيدًا.
31. لا تظهر محاكاة غير موثقة.
32. Cache Hit لا يستدعي توليدًا جديدًا.
33. Model call يملك سببًا وBudget.
34. Repair محدود وموجه بـCounterexample.
35. لا توجد Loop إصلاح غير محدودة.
36. النتيجة الجديدة VERIFIED تحفظ في Results Registry.
37. النسخة المستقلة تعمل دون اتصال خارجي غير مصرح.
38. كل Dependency جوهري قابل للإبطال وإعادة التحقق.
39. الحكام يستطيعون إدخال سؤال غير Hard-Coded.
40. النظام يميز بين Simulation وInteractive Model وAnswer Only.

============================================================
48. Definition of Done
============================================================

Done لا تعني:

- الصفحة تبدو جميلة.
- الاختبار اليدوي نجح مرة.
- النموذج قال إن الناتج صحيح.
- الكود Compile.
- لا يوجد Console Error.
- ستة أمثلة تعمل.

Done تعني:

- المتطلبات مرتبطة بتنفيذ واختبارات.
- العقود قابلة للتنفيذ.
- العيوب الحرجة مغلقة.
- Regression Tests موجودة.
- لا توجد محاكاة غير موثقة منشورة.
- الخصوصية مثبتة باختبار.
- التوليد المكرر ممنوع.
- التكلفة قابلة للقياس.
- Result قابل لإعادة الاستخدام.
- الوثيقة تطابق حقيقة المستودع.
- المخاطر المتبقية معلنة بوضوح.

============================================================
49. شكل الرد النهائي من وكيل CLI
============================================================

بعد التنفيذ، أعطني فقط:

1. Repository Audit Summary.
2. الملفات التي قرأتها.
3. الملفات التي عدّلتها.
4. أهم القرارات المعمارية.
5. كيف صُحّح:
   - عطل القمر.
   - القراءة الميتة.
   - اللغة الافتراضية.
   - التوليد المكرر.
   - استنزاف الرصيد.
   - حفظ النتائج.
   - عدم حفظ السؤال الخام.
   - المحاكاة غير الموثوقة.
6. مخطط التدفق المنفذ.
7. الاختبارات التي أضفتها.
8. الأوامر التي شغّلتها.
9. النتائج الفعلية للاختبارات.
10. ملخص Git Diff.
11. معايير القبول التي نجحت.
12. معايير القبول التي لم تنفذ بعد.
13. المخاطر الحقيقية المتبقية.
14. الخطوة التنفيذية التالية الدقيقة.

لا تكتب تقريرًا تسويقيًا.

لا تقل "كل شيء كامل" ما لم تمر معايير القبول.

============================================================
50. المراجع التي تم التحقق منها
============================================================

OpenAI official documentation:

https://developers.openai.com/api/docs/guides/latest-model

https://developers.openai.com/api/docs/guides/structured-outputs

https://developers.openai.com/api/docs/guides/function-calling

https://developers.openai.com/api/docs/guides/prompt-caching

https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling

https://developers.openai.com/api/docs/guides/tools-tool-search

https://developers.openai.com/api/docs/guides/reasoning

Research:

SimBench current record:
https://arxiv.org/abs/2408.11987

SimBench v1 historical result:
https://arxiv.org/html/2408.11987v1

From Prompts to Properties:
https://vtechworks.lib.vt.edu/items/702015c7-5db2-4dfc-a098-a8333c50faf6

PropTest:
https://aclanthology.org/2024.findings-emnlp.483.pdf

استخدم هذه المراجع لتصحيح الادعاءات فقط.

لا تجعل أي ورقة بديلًا عن اختبارات المشروع الفعلية.

ابدأ الآن:
افحص المستودع، صحح الوثيقة، أغلق عيوب P0، نفّذ الأساسات والـVertical Slice، ثم شغّل الاختبارات وقدم التقرير المحدد أعلاه.
