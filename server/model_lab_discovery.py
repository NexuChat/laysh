from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from server.fragment_generation import validate_physics_fragment
from server.schemas import ClosedModel, validate_understanding

SourceMode = Literal["off", "public_references"]
SourceStatus = Literal["skipped", "ready", "unavailable"]
ReferenceProvider = Literal["phet", "openstax", "nasa", "noaa"]
ReferenceKind = Literal["interactive_simulation", "scientific_reference"]
RepresentationFamily = Literal[
    "rays",
    "waves",
    "force_body",
    "orbital_light",
    "fluid_body",
    "particles_flow",
    "world_graph",
    "compare_ab",
]

_BIDI_CONTROLS = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+", flags=re.UNICODE)
_ENGLISH_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "are",
        "can",
        "did",
        "do",
        "does",
        "form",
        "happen",
        "how",
        "is",
        "the",
        "what",
        "when",
        "where",
        "why",
    }
)
_ARABIC_SEARCH_STOPWORDS = frozenset(
    {
        "إلى",
        "الى",
        "عن",
        "على",
        "في",
        "كيف",
        "ليش",
        "ما",
        "ماذا",
        "من",
        "هل",
        "لماذا",
        "يحدث",
        "تحدث",
        "تظهر",
        "يظهر",
        "تتكون",
        "تنتقل",
    }
)
_ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "ar.wikipedia.org",
        "en.wikipedia.org",
        "www.wikidata.org",
    }
)
_ALLOWED_REFERENCE_HOSTS = frozenset(
    {
        "phet.colorado.edu",
        "openstax.org",
        "science.nasa.gov",
        "www.noaa.gov",
    }
)


def _clean_text(value: object, *, limit: int) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _BIDI_CONTROLS.sub("", text)
    text = _CONTROL_CHARACTERS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()[:limit]


def _safe_source_url(value: object) -> str:
    candidate = str(value or "")
    parsed = urllib.parse.urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("source URL is not allowlisted")
    return candidate


def _safe_reference_url(value: object) -> str:
    candidate = str(value or "")
    parsed = urllib.parse.urlparse(candidate)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_REFERENCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("reference URL is not allowlisted")
    return candidate


def search_query_for(
    question: str,
    locale: Literal["en", "ar"],
) -> str:
    """Derive a bounded topical search phrase without invoking another model."""

    cleaned = _clean_text(question, limit=600)
    tokens = _WORD.findall(cleaned)
    stopwords = (
        _ARABIC_SEARCH_STOPWORDS
        if locale == "ar"
        else _ENGLISH_SEARCH_STOPWORDS
    )
    selected = [
        token
        for token in tokens
        if token.lower() not in stopwords
    ][:8]
    if not selected:
        selected = tokens[:8]
    query = " ".join(selected)
    return query.lower() if locale == "en" else query


class ModelLabEvidenceSource(ClosedModel):
    source_id: str = Field(pattern=r"^(wikipedia|wikidata):[A-Za-z0-9_-]{1,80}$")
    provider: Literal["wikipedia", "wikidata"]
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=600)
    url: str = Field(min_length=1, max_length=500)
    language: Literal["en", "ar"]
    license: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = _clean_text(value, limit=180)
        if not cleaned:
            raise ValueError("source title must not be blank")
        return cleaned

    @field_validator("summary")
    @classmethod
    def clean_summary(cls, value: str) -> str:
        cleaned = _clean_text(value, limit=600)
        if not cleaned:
            raise ValueError("source summary must not be blank")
        return cleaned

    @field_validator("url")
    @classmethod
    def allowlisted_url(cls, value: str) -> str:
        return _safe_source_url(value)


class ModelLabEvidenceBundle(ClosedModel):
    mode: SourceMode
    locale: Literal["en", "ar"]
    status: SourceStatus
    sources: list[ModelLabEvidenceSource] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def status_matches_sources(self) -> ModelLabEvidenceBundle:
        if self.status == "ready" and not self.sources:
            raise ValueError("ready evidence requires at least one source")
        if self.status != "ready" and self.sources:
            raise ValueError("non-ready evidence must not expose sources")
        return self


class DiscoveryLearningCycle(ClosedModel):
    prediction: str = Field(min_length=1, max_length=240)
    observe: str = Field(min_length=1, max_length=240)
    explain: str = Field(min_length=1, max_length=240)
    transfer: str = Field(min_length=1, max_length=240)


class DiscoveryRepresentation(ClosedModel):
    family: RepresentationFamily
    renderer: Literal["canvas_2d"] = "canvas_2d"
    primary_output: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    causal_proof: str = Field(min_length=1, max_length=240)
    depth_required: bool = False
    labels_in_dom: bool = True
    four_state_trajectory: bool = True


class ModelLabDiscoveryReference(ClosedModel):
    reference_id: str = Field(pattern=r"^[a-z][a-z0-9_:-]{2,100}$")
    provider: ReferenceProvider
    kind: ReferenceKind
    title: str = Field(min_length=1, max_length=180)
    url: str = Field(min_length=1, max_length=500)
    language: Literal["en", "ar"]
    usage: Literal["linked_reference"] = "linked_reference"
    license_note: str = Field(min_length=1, max_length=180)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = _clean_text(value, limit=180)
        if not cleaned:
            raise ValueError("reference title must not be blank")
        return cleaned

    @field_validator("url")
    @classmethod
    def allowlisted_url(cls, value: str) -> str:
        return _safe_reference_url(value)


class ModelLabDiscoveryPlan(ClosedModel):
    contract_version: Literal["1.0"] = "1.0"
    locale: Literal["en", "ar"]
    learning_cycle: DiscoveryLearningCycle
    representation: DiscoveryRepresentation
    primary_parameter_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_ids: list[str] = Field(default_factory=list, max_length=6)
    related_references: list[ModelLabDiscoveryReference] = Field(
        default_factory=list,
        max_length=4,
    )


class DisabledEvidenceProvider:
    async def collect(
        self,
        question: str,
        locale: Literal["en", "ar"],
    ) -> ModelLabEvidenceBundle:
        del question
        return ModelLabEvidenceBundle(
            mode="off",
            locale=locale,
            status="skipped",
            sources=[],
        )


FetchJson = Callable[[str], dict[str, Any]]
Sleep = Callable[[float], Awaitable[None]]


def _fetch_json(url: str) -> dict[str, Any]:
    safe_url = _safe_source_url(url)
    request = urllib.request.Request(  # noqa: S310 - URL host and scheme are allowlisted
        safe_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Laysh-Model-Lab/1.1 (reference discovery)",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=2.5) as response:  # noqa: S310
        if response.status != 200:
            raise OSError("reference source returned a non-success response")
        body = response.read(256 * 1024 + 1)
    if len(body) > 256 * 1024:
        raise OSError("reference source response exceeded the bounded size")
    document = json.loads(body)
    if not isinstance(document, dict):
        raise OSError("reference source returned a malformed document")
    return document


class WikimediaEvidenceProvider:
    """Bounded, opt-in reference lookup for the isolated Model Lab.

    The learner pipeline never constructs this provider. The selected question is
    sent only when the Model Lab request explicitly chooses ``public_references``.
    """

    def __init__(
        self,
        *,
        fetch_json: FetchJson = _fetch_json,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._fetch_json = fetch_json
        self._sleep = sleep
        self._ready_cache: dict[str, ModelLabEvidenceBundle] = {}
        self._collect_lock = asyncio.Lock()

    async def collect(
        self,
        question: str,
        locale: Literal["en", "ar"],
    ) -> ModelLabEvidenceBundle:
        query = search_query_for(question, locale)
        if not query:
            return ModelLabEvidenceBundle(
                mode="public_references",
                locale=locale,
                status="unavailable",
                sources=[],
            )
        cache_key = hashlib.sha256(
            f"{locale}\0{query}".encode()
        ).hexdigest()
        async with self._collect_lock:
            cached = self._ready_cache.get(cache_key)
            if cached is not None:
                return cached.model_copy(deep=True)
            evidence = await self._collect_uncached(query, locale)
            if evidence.status == "ready":
                if len(self._ready_cache) >= 64:
                    self._ready_cache.pop(next(iter(self._ready_cache)))
                self._ready_cache[cache_key] = evidence.model_copy(deep=True)
            return evidence

    async def _fetch_with_rate_limit_retry(
        self,
        url: str,
    ) -> dict[str, Any]:
        for attempt in range(2):
            try:
                return await asyncio.to_thread(self._fetch_json, url)
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt == 1:
                    raise
                raw_delay = error.headers.get("Retry-After", "1")
                try:
                    delay = float(raw_delay)
                except (TypeError, ValueError):
                    delay = 1.0
                await self._sleep(max(0.0, min(delay, 2.0)))
        raise RuntimeError("unreachable_reference_retry_state")

    async def _safe_fetch(
        self,
        url: str,
    ) -> dict[str, Any] | BaseException:
        try:
            return await self._fetch_with_rate_limit_retry(url)
        except (OSError, RuntimeError, ValueError) as error:
            return error

    async def _collect_uncached(
        self,
        query: str,
        locale: Literal["en", "ar"],
    ) -> ModelLabEvidenceBundle:
        wikidata_url = self._wikidata_url(query, locale)
        local_wikipedia_url = self._wikipedia_url(query, locale)
        local_wikipedia = await self._safe_fetch(local_wikipedia_url)
        wikidata = await self._safe_fetch(wikidata_url)
        english_wikipedia: dict[str, Any] | BaseException
        if locale == "ar":
            english_titles = (
                self._english_titles(local_wikipedia)
                if isinstance(local_wikipedia, dict)
                else []
            )
            english_url = (
                self._wikipedia_titles_url(english_titles)
                if english_titles
                else self._wikipedia_url(query, "en")
            )
            english_wikipedia = await self._safe_fetch(english_url)
        else:
            english_wikipedia = local_wikipedia
        sources: list[ModelLabEvidenceSource] = []
        if isinstance(english_wikipedia, dict):
            sources.extend(
                self._parse_wikipedia(
                    english_wikipedia,
                    "en",
                    preferred_title=(
                        english_titles[0]
                        if locale == "ar" and english_titles
                        else query
                    ),
                )[: (2 if locale == "ar" else 3)]
            )
        if locale == "ar" and isinstance(local_wikipedia, dict):
            sources.extend(
                self._parse_wikipedia(
                    local_wikipedia,
                    "ar",
                    preferred_title=query,
                )[:2]
            )
        if isinstance(wikidata, dict):
            limit = 2 if locale == "ar" else 3
            sources.extend(
                self._parse_wikidata(
                    wikidata,
                    locale,
                    preferred_label=query,
                )[:limit]
            )
        sources = list(
            {
                (source.provider, source.url): source
                for source in sources
            }.values()
        )
        return ModelLabEvidenceBundle(
            mode="public_references",
            locale=locale,
            status="ready" if sources else "unavailable",
            sources=sources[:6],
        )

    @staticmethod
    def _wikipedia_url(question: str, locale: Literal["en", "ar"]) -> str:
        parameters = urllib.parse.urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": question,
                "gsrlimit": 3,
                "prop": "extracts|info|langlinks",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "lllang": "en",
                "lllimit": 1,
                "format": "json",
                "formatversion": 2,
            }
        )
        return f"https://{locale}.wikipedia.org/w/api.php?{parameters}"

    @staticmethod
    def _wikipedia_titles_url(titles: Sequence[str]) -> str:
        parameters = urllib.parse.urlencode(
            {
                "action": "query",
                "titles": "|".join(titles[:3]),
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "format": "json",
                "formatversion": 2,
            }
        )
        return f"https://en.wikipedia.org/w/api.php?{parameters}"

    @staticmethod
    def _english_titles(document: dict[str, Any]) -> list[str]:
        query = document.get("query")
        pages = query.get("pages") if isinstance(query, dict) else None
        if not isinstance(pages, list):
            return []
        titles: list[str] = []
        for page in pages[:3]:
            langlinks = page.get("langlinks") if isinstance(page, dict) else None
            if not isinstance(langlinks, list):
                continue
            for link in langlinks[:1]:
                title = (
                    _clean_text(link.get("title"), limit=180)
                    if isinstance(link, dict) and link.get("lang") == "en"
                    else ""
                )
                if title and title not in titles:
                    titles.append(title)
        return titles

    @staticmethod
    def _wikidata_url(question: str, locale: Literal["en", "ar"]) -> str:
        parameters = urllib.parse.urlencode(
            {
                "action": "wbsearchentities",
                "search": question,
                "language": locale,
                "uselang": locale,
                "limit": 3,
                "format": "json",
            }
        )
        return f"https://www.wikidata.org/w/api.php?{parameters}"

    @staticmethod
    def _parse_wikipedia(
        document: dict[str, Any],
        locale: Literal["en", "ar"],
        *,
        preferred_title: str | None = None,
    ) -> list[ModelLabEvidenceSource]:
        query = document.get("query")
        pages = query.get("pages") if isinstance(query, dict) else None
        if not isinstance(pages, list):
            return []
        sources: list[ModelLabEvidenceSource] = []
        for page in pages[:3]:
            if not isinstance(page, dict):
                continue
            page_id = page.get("pageid")
            title = _clean_text(page.get("title"), limit=180)
            summary = _clean_text(page.get("extract"), limit=600)
            url = page.get("fullurl")
            if not isinstance(page_id, int) or not title or not summary:
                continue
            if not isinstance(url, str):
                slug = urllib.parse.quote(title.replace(" ", "_"), safe="")
                url = f"https://{locale}.wikipedia.org/wiki/{slug}"
            try:
                sources.append(
                    ModelLabEvidenceSource(
                        source_id=f"wikipedia:{locale}_{page_id}",
                        provider="wikipedia",
                        title=title,
                        summary=summary,
                        url=url,
                        language=locale,
                        license="CC BY-SA; see source page",
                    )
                )
            except ValueError:
                continue
        normalized_preferred = _clean_text(
            preferred_title,
            limit=180,
        ).casefold()
        exact = [
            source
            for source in sources
            if source.title.casefold() == normalized_preferred
        ]
        if exact:
            return exact
        return sources

    @staticmethod
    def _parse_wikidata(
        document: dict[str, Any],
        locale: Literal["en", "ar"],
        *,
        preferred_label: str | None = None,
    ) -> list[ModelLabEvidenceSource]:
        results = document.get("search")
        if not isinstance(results, list):
            return []
        sources: list[ModelLabEvidenceSource] = []
        for item in results[:3]:
            if not isinstance(item, dict):
                continue
            entity_id = item.get("id")
            title = _clean_text(item.get("label"), limit=180)
            summary = _clean_text(item.get("description"), limit=600)
            if (
                not isinstance(entity_id, str)
                or not re.fullmatch(r"Q[1-9][0-9]{0,19}", entity_id)
                or not title
                or not summary
            ):
                continue
            try:
                sources.append(
                    ModelLabEvidenceSource(
                        source_id=f"wikidata:{entity_id}",
                        provider="wikidata",
                        title=title,
                        summary=summary,
                        url=f"https://www.wikidata.org/entity/{entity_id}",
                        language=locale,
                        license="CC0",
                    )
                )
            except ValueError:
                continue
        normalized_preferred = _clean_text(
            preferred_label,
            limit=180,
        ).casefold()
        exact = [
            source
            for source in sources
            if source.title.casefold() == normalized_preferred
        ]
        if exact:
            return exact
        return sources


def representation_family_for(
    *,
    domain: str,
    action: str | None,
    output_names: Sequence[str],
) -> RepresentationFamily:
    """Route by causal and scientific semantics, never by a curated lesson name."""

    normalized_domain = domain.lower()
    output_tokens = " ".join(output_names).lower()
    if action in {"phases", "orbits"} or any(
        token in normalized_domain
        for token in ("astronomy", "orbital", "celestial")
    ):
        return "orbital_light"
    if any(token in normalized_domain for token in ("optics", "light", "refraction")):
        return "rays"
    if action == "propagates" or any(
        token in normalized_domain
        for token in ("acoustic", "sound", "wave", "seismic")
    ):
        return "waves"
    if action == "floats_sinks" or any(
        token in normalized_domain
        for token in ("fluid", "density", "hydro", "displacement", "submerged")
    ):
        return "fluid_body"
    if action == "flows" or any(
        token in normalized_domain
        for token in (
            "electric",
            "current",
            "charge",
            "particle",
            "diffusion",
            "chemical",
        )
    ):
        return "particles_flow"
    if action == "oscillates" or any(
        token in normalized_domain
        for token in ("mechanic", "force", "motion", "kinematic")
    ):
        return "force_body"
    if any(token in output_tokens for token in ("difference", "ratio", "compare")):
        return "compare_ab"
    return "world_graph"


_PHET_BY_FAMILY: dict[
    RepresentationFamily,
    tuple[str, str, str],
] = {
    "rays": ("bending-light", "Bending Light", "انحناء الضوء"),
    "waves": ("waves-intro", "Waves Intro", "مقدمة عن الموجات"),
    "force_body": (
        "forces-and-motion-basics",
        "Forces and Motion: Basics",
        "القوى والحركة: الأساسيات",
    ),
    "orbital_light": (
        "gravity-and-orbits",
        "Gravity and Orbits",
        "الجاذبية والمدارات",
    ),
    "fluid_body": ("buoyancy", "Buoyancy", "الطفو"),
    "particles_flow": (
        "circuit-construction-kit-dc",
        "Circuit Construction Kit: DC",
        "بناء الدائرة الكهربائية: تيار مستمر",
    ),
    "world_graph": (
        "states-of-matter-basics",
        "States of Matter: Basics",
        "حالات المادة: الأساسيات",
    ),
}


def related_references_for(
    *,
    family: RepresentationFamily,
    domain: str,
    locale: Literal["en", "ar"],
) -> list[ModelLabDiscoveryReference]:
    """Return links selected by broad science semantics, never a lesson identity.

    These are outbound references only. Laysh does not copy, execute, or present
    their content as locally verified evidence.
    """

    references: list[ModelLabDiscoveryReference] = []
    phet = _PHET_BY_FAMILY.get(family)
    if phet is not None:
        slug, english_title, arabic_title = phet
        phet_locale = "ar_SA" if locale == "ar" else "en"
        references.append(
            ModelLabDiscoveryReference(
                reference_id=f"phet:{family}",
                provider="phet",
                kind="interactive_simulation",
                title=arabic_title if locale == "ar" else english_title,
                url=f"https://phet.colorado.edu/{phet_locale}/simulations/{slug}",
                language=locale,
                license_note="Linked reference; PhET terms and attribution apply.",
            )
        )

    normalized_domain = domain.lower()
    if any(
        token in normalized_domain
        for token in ("astronomy", "orbital", "celestial", "space")
    ):
        references.append(
            ModelLabDiscoveryReference(
                reference_id="nasa:universe",
                provider="nasa",
                kind="scientific_reference",
                title="NASA Science: Universe",
                url="https://science.nasa.gov/universe/",
                language="en",
                license_note="Linked U.S. government science reference.",
            )
        )
    elif any(
        token in normalized_domain
        for token in (
            "atmosphere",
            "climate",
            "weather",
            "ocean",
            "meteorology",
        )
    ):
        references.append(
            ModelLabDiscoveryReference(
                reference_id="noaa:education",
                provider="noaa",
                kind="scientific_reference",
                title="NOAA Education Resource Collections",
                url="https://www.noaa.gov/education/resource-collections",
                language="en",
                license_note="Linked U.S. government science reference.",
            )
        )
    else:
        references.append(
            ModelLabDiscoveryReference(
                reference_id="openstax:physics",
                provider="openstax",
                kind="scientific_reference",
                title="OpenStax Physics",
                url="https://openstax.org/details/books/physics",
                language="en",
                license_note="Linked open textbook; source page states its license.",
            )
        )
    return references


def build_discovery_plan(
    understanding: dict[str, Any],
    physics_document: dict[str, Any],
    *,
    source_ids: Sequence[str],
) -> ModelLabDiscoveryPlan:
    understanding = validate_understanding(understanding)
    physics_document = validate_physics_fragment(
        physics_document,
        understanding,
    )
    locale: Literal["en", "ar"] = understanding["lang"]
    primary = understanding["primary_parameter"]
    if primary is None:
        raise ValueError("discovery plan requires a primary parameter")
    prediction = understanding.get("prediction")
    prediction_prompt = (
        prediction.get("prompt")
        if isinstance(prediction, dict)
        else None
    )
    primary_output = physics_document["output_names"][0]
    if locale == "ar":
        observe = (
            f"غيّر {primary['label']} من الحد الأدنى إلى الأعلى، "
            "وراقب ما يتغير في الممثل العلمي."
        )
        fallback_prediction = f"توقّع ما الذي سيتغير عند تعديل {primary['label']}."
        fallback_explain = "فسّر التغير الذي شاهدته واربطه بالسبب العلمي."
        fallback_transfer = "طبّق العلاقة نفسها على حالة جديدة."
        causal_proof = (
            f"يجب أن يغيّر التحكم {primary['label']} الممثل العلمي بصريًا "
            f"من خلال الناتج {primary_output}."
        )
    else:
        observe = (
            f"Move {primary['label']} from its minimum to maximum and watch "
            "what changes in the scientific actor."
        )
        fallback_prediction = f"Predict what will change when {primary['label']} changes."
        fallback_explain = "Explain the observed change and connect it to the cause."
        fallback_transfer = "Apply the same relationship to a new case."
        causal_proof = (
            f"The {primary['label']} control must visibly change the scientific "
            f"actor through the {primary_output} output."
        )
    sanitized_source_ids = [
        source_id
        for source_id in source_ids
        if re.fullmatch(r"(?:wikipedia|wikidata):[A-Za-z0-9_-]{1,80}", source_id)
    ][:6]
    representation_family = representation_family_for(
        domain=understanding["domain"],
        action=understanding["module_spec"].get("action"),
        output_names=physics_document["output_names"],
    )
    return ModelLabDiscoveryPlan(
        locale=locale,
        learning_cycle=DiscoveryLearningCycle(
            prediction=prediction_prompt or fallback_prediction,
            observe=observe,
            explain=understanding.get("explanation_prompt") or fallback_explain,
            transfer=understanding.get("transfer_prompt") or fallback_transfer,
        ),
        representation=DiscoveryRepresentation(
            family=representation_family,
            primary_output=primary_output,
            causal_proof=causal_proof,
        ),
        primary_parameter_id=primary["id"],
        source_ids=sanitized_source_ids,
        related_references=related_references_for(
            family=representation_family,
            domain=understanding["domain"],
            locale=locale,
        ),
    )
