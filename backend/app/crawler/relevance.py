import re

from app.crawler.domain import RelevanceDecision
from app.experience import is_junior_only_role

ROLE_KEYWORDS = (
    "backend",
    "back-end",
    "server",
    "software engineer",
    "product engineer",
    "product-minded engineer",
    "product minded engineer",
    "founding engineer",
    "full stack",
    "full-stack",
    "fullstack",
    "platform engineer",
    "devops",
    "sre",
    "cloud engineer",
    "data engineer",
    "ai engineer",
    "ai agent",
    "llm",
    "applied ai",
    "automation engineer",
    "solutions engineer",
    "forward deployed",
    "백엔드",
    "서버",
    "소프트웨어 엔지니어",
    "프로덕트 엔지니어",
    "풀스택",
    "플랫폼 엔지니어",
    "데브옵스",
    "데이터 엔지니어",
    "ai 엔지니어",
    "ai 개발자",
    "ai개발자",
    "ax 개발자",
    "ml engineer",
    "ml 엔지니어",
    "머신러닝 엔지니어",
    "python 개발자",
    "python 개발",
    "파이썬 개발자",
    "파이썬 개발",
    "django 개발자",
    "node.js 개발자",
    "typescript 개발자",
    "developer",
    "engineer",
    "개발자",
    "엔지니어",
)

TECH_SIGNALS = (
    "python",
    "django",
    "fastapi",
    "flask",
    "typescript",
    "node.js",
    "nodejs",
    "nestjs",
    "nest.js",
    "express.js",
    "fastify",
    "llm",
    "ai agent",
    "langchain",
    "langgraph",
    "rest api",
    "postgresql",
    "kafka",
    "aws",
    "java",
    "spring",
    "golang",
    "kotlin",
    "pytorch",
    "tensorflow",
    "grpc",
)

# Java/Spring 공고를 무조건 버리지는 않는다. Python/Node/TypeScript/AI가 함께
# 명시된 혼합 스택 공고는 지원 가능성이 있으므로 유지하고, 해당 신호가 전혀
# 없는 Java 중심 공고만 수집 단계에서 제외한다.
PREFERRED_STACK_SIGNALS = (
    "python",
    "django",
    "fastapi",
    "flask",
    "typescript",
    "node.js",
    "nodejs",
    "nestjs",
    "nest.js",
    "express",
    "fastify",
    "llm",
    "ai agent",
    "langchain",
    "langgraph",
    "pytorch",
    "tensorflow",
    "golang",
)

JAVA_STACK_PATTERNS = (
    r"\bjava\b",
    r"\bspring(?:\s+boot|\s+framework)?\b",
)

# Standalone ``go`` is a common English verb, so treat it as the programming
# language only when the surrounding text carries a language or backend signal.
GO_LANGUAGE_PATTERN = re.compile(
    r"(?<![a-z0-9_])golang(?![a-z0-9_])"
    r"|(?<![a-z0-9_])go(?![a-z0-9_])\s*(?:language|언어|기반|개발|백엔드|서버|api|"
    r"software|service|서비스|microservice|마이크로서비스|grpc|graphql|gin|echo|fiber)"
    r"|(?:backend|server|api|software|service|microservice|백엔드|서버|서비스)"
    r"\s+(?:written\s+in\s+|in\s+)?go(?![a-z0-9_])"
    r"|(?<![a-z0-9_])go(?![a-z0-9_])\s*[,/&|+]\s*"
    r"(?:python|java|typescript|node(?:\.js|js)|rust|kotlin)",
    re.IGNORECASE,
)

PURE_EXCLUDES = (
    "frontend",
    "front-end",
    "프론트엔드",
    "ios developer",
    "android developer",
    "android",
    "안드로이드",
    "qa engineer",
    "qa 엔지니어",
    "qa엔지니어",
    "테스트 엔지니어",
    "품질보증",
    "product designer",
    "data analyst",
    "bi analyst",
    "데이터 분석가",
    "hardware",
    "하드웨어",
    "마케터",
    "디자이너",
    "교육 강사",
    "강사 모집",
    "테크니컬 라이터",
    "rtl design",
    "rtl 설계",
    "verification engineer",
    "ip verification",
    "회로 설계",
    "반도체 회로",
    "signal & power integrity",
    "power integrity validation",
)

NON_DEVELOPER_DESCRIPTION_EXCLUDES = (
    "소프트웨어 엔지니어 포지션이 아닙니다",
    "소프트웨어 개발 포지션이 아닙니다",
    "개발 직무가 아닙니다",
)

MANAGEMENT_EXCLUDES = (
    "project manager",
    "product manager",
    "service planner",
    "프로젝트 매니저",
    "프로덕트 매니저",
    "서비스 기획",
    "서비스기획",
    "기획자",
)

OVERRIDE_INCLUDES = (
    "backend",
    "back-end",
    "server",
    "full stack",
    "full-stack",
    "fullstack",
    "product engineer",
    "product-minded engineer",
    "product minded engineer",
    "founding engineer",
    "ai engineer",
    "백엔드",
    "서버",
    "풀스택",
    "프로덕트 엔지니어",
)

TECHNICAL_PRODUCT_TITLE_PATTERNS = (
    r"\bproduct owner\b",
    r"\btechnical product manager\b",
    r"\btechnical po\b",
    r"\btechnical pm\b",
    r"(?<![a-z0-9])po(?![a-z0-9])",
    r"프로덕트 오너",
    r"테크니컬 po",
    r"기술 po",
)

HANDS_ON_PRODUCT_SIGNALS = (
    "개발 전문성",
    "직접 개발",
    "직접 구현",
    "풀스택 담당",
    "풀스택 개발",
    "개발부터 배포",
    "코드를 작성",
    "프로토타입 구현",
    "프로토타입 개발",
    "software engineering",
    "engineering background",
    "hands-on development",
    "hands on development",
    "full-stack ownership",
    "full stack ownership",
)

HANDS_ON_NEGATION_SUFFIXES = (
    "하지 않",
    "하지는 않",
    "할 필요 없",
    "하지 않아도",
    "경험이 없어도",
)

TECH_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?<![a-z0-9_])python(?![a-z0-9_])", "Python"),
    (
        r"(?<![a-z0-9_])django(?![a-z0-9_])|django rest framework|"
        r"(?<![a-z0-9_])drf(?![a-z0-9_])",
        "Django",
    ),
    (r"(?<![a-z0-9_])fastapi(?![a-z0-9_])", "FastAPI"),
    (r"(?<![a-z0-9_])flask(?![a-z0-9_])", "Flask"),
    (r"(?<![a-z0-9_])javascript(?![a-z0-9_])", "JavaScript"),
    (r"(?<![a-z0-9_])typescript(?![a-z0-9_])", "TypeScript"),
    (r"(?<![a-z0-9_])node(?:\.js|js)(?![a-z0-9_])", "Node.js"),
    (r"(?<![a-z0-9_])nest(?:js|\.js)(?![a-z0-9_])", "NestJS"),
    (r"\breact(?:\.js)?\b", "React"),
    (r"\bnext(?:\.js|js)?\b", "Next.js"),
    (r"(?<![a-z0-9_])postgres(?:ql)?(?![a-z0-9_])", "PostgreSQL"),
    (r"\bmysql\b", "MySQL"),
    (r"\bredis\b", "Redis"),
    (r"\bkafka\b", "Kafka"),
    (r"\baws\b", "AWS"),
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\bllm\b|large language model", "LLM"),
    (r"ai agent|agentic", "AI Agent"),
    (r"\blangchain\b", "LangChain"),
    (r"\blanggraph\b", "LangGraph"),
    (r"\brest(?:ful)? api\b", "REST API"),
    (r"(?<![a-z0-9_])java(?![a-z0-9_])", "Java"),
    (r"(?<![a-z0-9_])spring(?: boot| framework)?(?![a-z0-9_])", "Spring"),
    (r"\bkotlin\b", "Kotlin"),
    (r"\bpytorch\b", "PyTorch"),
    (r"\btensorflow\b", "TensorFlow"),
    (r"\bgrpc\b", "gRPC"),
    (r"\bc#\b|\bcsharp\b", "C#"),
    (r"\.net\b|\bdotnet\b|asp\.net", ".NET"),
    (r"\bruby\b", "Ruby"),
    (r"\brails\b|ruby on rails", "Rails"),
    (r"\bmongodb\b", "MongoDB"),
    (r"\belasticsearch\b", "Elasticsearch"),
    (r"\bgcp\b|google cloud platform", "GCP"),
    (r"\bazure\b", "Azure"),
    (r"\bterraform\b", "Terraform"),
    (r"\bairflow\b", "Airflow"),
    (r"\betl\b|\bdata pipeline\b|데이터 파이프라인", "Data Pipeline"),
    (r"\bspark\b|apache spark", "Spark"),
    (r"\bcelery\b", "Celery"),
    (r"\brabbitmq\b", "RabbitMQ"),
    (r"\bprometheus\b", "Prometheus"),
    (r"\bgrafana\b", "Grafana"),
    (r"\bdatadog\b", "Datadog"),
    (r"\bsentry\b", "Sentry"),
    (r"\bsqlalchemy\b", "SQLAlchemy"),
    (r"\bpandas\b", "Pandas"),
    (r"\bpytest\b", "pytest"),
    (r"\b(?:unit ?test|unittest)\b|단위 테스트", "Unit testing"),
    (r"\bci\s*/\s*cd\b|continuous integration", "CI/CD"),
    (r"\bgithub actions?\b", "GitHub Actions"),
    (r"\bjenkins\b", "Jenkins"),
    (r"\bargo\s*-?\s*cd\b", "Argo CD"),
    (r"\blinux\b", "Linux"),
    (r"\bncp\b|naver cloud|네이버 클라우드", "NCP"),
    (r"\brag\b|retrieval augmented generation", "RAG"),
    (r"\bfaiss\b", "FAISS"),
    (r"\bpgvector\b", "pgvector"),
    (r"\b(?:vector database|vector db)\b|벡터 데이터베이스|벡터 db", "Vector DB"),
    (GO_LANGUAGE_PATTERN.pattern, "Go"),
    (r"\bgraphql\b", "GraphQL"),
    (r"\bopencv\b", "OpenCV"),
    (r"\bcuda\b", "CUDA"),
    (r"\bnumpy\b", "NumPy"),
    (r"\bnginx\b", "NGINX"),
    (r"\bzeromq\b", "ZeroMQ"),
    (r"\bwebrtc\b", "WebRTC"),
    (r"\bceph\b", "Ceph"),
    (r"\bdbt\b", "dbt"),
    (r"\bhadoop\b", "Hadoop"),
    (r"\b(?:mariadb|maria db)\b", "MariaDB"),
    (r"\b(?:mssql|sql server)\b", "MSSQL"),
    (r"\bphp\b", "PHP"),
    (r"\brust\b", "Rust"),
    (r"(?<![a-z0-9_])express(?:\.js|js)?(?![a-z0-9_])", "Express"),
    (r"(?<![a-z0-9_])fastify(?![a-z0-9_])", "Fastify"),
    (r"\bros2?\b", "ROS"),
)

NODE_COMPANION_PATTERN = re.compile(
    r"(?<![a-z0-9_])(?:javascript|typescript|node(?:\.js|js)|nestjs|nest\.js|"
    r"express(?:\.js|js)?|fastify)(?![a-z0-9_])",
    re.IGNORECASE,
)
NODE_FALSE_CONTEXT_PATTERN = re.compile(
    r"\b(?:blockchain|validator|rpc|consensus|peer|cluster|infrastructure|network|storage)\b"
    r"|(?:dom|문서 객체|블록체인|검증자|인프라|네트워크|스토리지)\s*node"
    r"|node\s*(?:operator|운영자|검증자)",
    re.IGNORECASE,
)
BACKEND_WORK_PATTERNS = (
    r"\bback[ -]?end\b",
    r"\bserver(?:less)?\b",
    r"\b(?:rest|graphql)\s*api\b",
    r"\b(?:rdb|database|postgres(?:ql)?|mysql|redis|kafka|sqs)\b",
    r"백엔드",
    r"서버",
    r"api\s*(?:개발|설계|서버)",
    r"데이터(?:베이스)?\s*(?:모델링|설계)",
)
FRONTEND_WORK_PATTERNS = (
    r"\bfront[ -]?end\b",
    r"\b(?:react|vue|next\.js|vite)\b",
    r"\b(?:html|css|dom|ui|ux)\b",
    r"프론트엔드",
    r"화면\s*(?:개발|구현)",
    r"웹\s*퍼블리싱",
)


def _technical_product_title(title: str) -> bool:
    normalized = title.casefold()
    return any(re.search(pattern, normalized) for pattern in TECHNICAL_PRODUCT_TITLE_PATTERNS)


def _has_hands_on_product_signal(description: str) -> bool:
    description_lower = description.casefold()
    for signal in HANDS_ON_PRODUCT_SIGNALS:
        start = 0
        while (index := description_lower.find(signal, start)) >= 0:
            suffix = description_lower[index + len(signal) : index + len(signal) + 20]
            negated = any(
                suffix.lstrip().startswith(negation) for negation in HANDS_ON_NEGATION_SUFFIXES
            )
            if not negated:
                return True
            start = index + len(signal)
    return False


def is_technical_product_role(title: str, description: str = "") -> bool:
    if not _technical_product_title(title):
        return False
    description_lower = description.casefold()
    has_preferred_stack = any(signal in description_lower for signal in PREFERRED_STACK_SIGNALS)
    has_hands_on_ownership = _has_hands_on_product_signal(description)
    return has_preferred_stack and has_hands_on_ownership


def _pattern_hits(text: str, patterns: tuple[str, ...]) -> int:
    return sum(len(re.findall(pattern, text, re.IGNORECASE)) for pattern in patterns)


def estimate_backend_share(title: str, description: str = "") -> int:
    """Estimate backend responsibility share for role filtering and display."""
    title_lower = title.casefold()
    text = f"{title}\n{description}".casefold()
    if any(term in title_lower for term in ("frontend", "front-end", "프론트엔드")):
        return 10
    backend_hits = _pattern_hits(text, BACKEND_WORK_PATTERNS)
    frontend_hits = _pattern_hits(text, FRONTEND_WORK_PATTERNS)
    if any(term in title_lower for term in ("backend", "back-end", "백엔드", "server", "서버")):
        backend_hits += 5
    if not frontend_hits:
        return 90 if backend_hits else 55
    if not backend_hits:
        return 15
    return max(10, min(90, round(100 * backend_hits / (backend_hits + frontend_hits))))


def _contextual_node_technologies(text: str) -> list[str]:
    """Resolve ambiguous Node, TS and Nest spellings only with backend-tech context."""
    found: list[str] = []
    lowered = text.casefold()
    companion_exists = bool(NODE_COMPANION_PATTERN.search(lowered))

    for match in re.finditer(r"(?<![a-z0-9_.])node(?![a-z0-9_.])", lowered):
        context = lowered[max(0, match.start() - 100) : match.end() + 100]
        if companion_exists and not NODE_FALSE_CONTEXT_PATTERN.search(context):
            found.append("Node.js")
            break
    if re.search(r"(?<![a-z0-9_])ts(?![a-z0-9_])", lowered) and companion_exists:
        found.append("TypeScript")
    if re.search(r"(?<![a-z0-9_])nest(?![a-z0-9_.])", lowered) and companion_exists:
        found.append("NestJS")
    return found


def assess_relevance(
    title: str,
    description: str = "",
    experience_text: str | None = None,
    employment_type: str | None = None,
) -> RelevanceDecision:
    title_lower = title.casefold()
    full_text = f"{title}\n{description}".casefold()
    role_hits = [keyword for keyword in ROLE_KEYWORDS if keyword in title_lower]
    tech_hits = [keyword for keyword in TECH_SIGNALS if keyword in full_text]
    go_language = bool(GO_LANGUAGE_PATTERN.search(full_text))
    if go_language and "go" not in tech_hits:
        tech_hits.append("go")
    soft_excluded = any(keyword in title_lower for keyword in PURE_EXCLUDES)
    description_excluded = any(phrase in full_text for phrase in NON_DEVELOPER_DESCRIPTION_EXCLUDES)
    technical_product_role = is_technical_product_role(title, description)
    hard_excluded = (
        any(keyword in title_lower for keyword in MANAGEMENT_EXCLUDES)
        or bool(re.search(r"(?<![a-z0-9])(?:pm|po)(?![a-z0-9])", title_lower))
    ) and not technical_product_role
    overridden = any(keyword in title_lower for keyword in OVERRIDE_INCLUDES)
    java_stack = any(re.search(pattern, full_text) for pattern in JAVA_STACK_PATTERNS)
    preferred_stack = (
        any(keyword in full_text for keyword in PREFERRED_STACK_SIGNALS) or go_language
    )
    java_only = java_stack and not preferred_stack
    junior_only = is_junior_only_role(title, experience_text, employment_type)
    backend_share = estimate_backend_share(title, description)
    frontend_dominant = backend_share < 50

    included = (
        bool((role_hits and (tech_hits or overridden)) or technical_product_role)
        and not hard_excluded
        and not description_excluded
        and not (soft_excluded and not overridden)
        and not java_only
        and not junior_only
        and not frontend_dominant
    )
    reasons = tuple(
        (["role:technical_product_builder"] if technical_product_role else [])
        + [f"role:{hit}" for hit in role_hits]
        + [f"tech:{hit}" for hit in tech_hits]
    )
    if hard_excluded or description_excluded or (soft_excluded and not overridden):
        reasons += ("excluded:pure_non_target_role",)
    if java_only:
        reasons += ("excluded:java_only_stack",)
    if junior_only:
        reasons += ("excluded:junior_only",)
    if frontend_dominant:
        reasons += ("excluded:frontend_dominant",)
    return RelevanceDecision(included=included, reasons=reasons)


def is_likely_target_role(title: str) -> bool:
    """Cheap title-only prefilter used before opening expensive detail pages."""
    title_lower = title.casefold()
    role_hit = any(keyword in title_lower for keyword in ROLE_KEYWORDS)
    soft_excluded = any(keyword in title_lower for keyword in PURE_EXCLUDES)
    hard_excluded = any(keyword in title_lower for keyword in MANAGEMENT_EXCLUDES) or bool(
        re.search(r"(?<![a-z0-9])(?:pm|po)(?![a-z0-9])", title_lower)
    )
    overridden = any(keyword in title_lower for keyword in OVERRIDE_INCLUDES)
    technical_product_candidate = _technical_product_title(title)
    return technical_product_candidate or (
        role_hit and not hard_excluded and not (soft_excluded and not overridden)
    )


def extract_tech_stack(text: str) -> list[str]:
    lowered = text.casefold()
    explicit = [
        name for pattern, name in TECH_PATTERNS if re.search(pattern, lowered, re.IGNORECASE)
    ]
    return list(dict.fromkeys([*explicit, *_contextual_node_technologies(text)]))
