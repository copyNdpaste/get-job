"""Shared discovery profile for backend and product-oriented engineering roles."""

PYTHON_SEARCH_TERMS = (
    "Python",
    "Django",
    "FastAPI",
    "Flask",
)

NODE_TYPESCRIPT_SEARCH_TERMS = (
    "Node.js",
    "NodeJS",
    "Node",
    "TypeScript",
    "NestJS",
    "Nest.js",
    "Nest",
    "Express",
    "Express.js",
    "Fastify",
    "TypeScript Backend",
    "Node.js Backend",
    "백엔드 TypeScript",
    "백엔드 Node.js",
    "Node 백엔드",
    "NestJS 백엔드",
    "서버 개발자",
    "플랫폼 백엔드 개발자",
    "Backend Engineer",
    "Software Engineer",
)

GO_SEARCH_TERMS = (
    "Golang",
    "Go Backend",
    "Go Server",
    "Golang Backend",
)

PRODUCT_ENGINEER_SEARCH_TERMS = (
    "Product Engineer",
    "Product-minded Engineer",
    "Product-minded Software Engineer",
    "AI Product Engineer",
    "Founding Engineer",
    "Full Stack Engineer",
    "Full-stack Engineer",
    "Fullstack Engineer",
    "프로덕트 엔지니어",
    "풀스택 엔지니어",
    "풀스택 개발자",
)

# Infrastructure roles were already part of collection and remain supported.
ADJACENT_SEARCH_TERMS = ("백엔드", "서버", "DevOps", "SRE", "인프라")

JOB_SEARCH_TERMS = tuple(
    dict.fromkeys(
        (
            *PYTHON_SEARCH_TERMS,
            *NODE_TYPESCRIPT_SEARCH_TERMS,
            *GO_SEARCH_TERMS,
            *PRODUCT_ENGINEER_SEARCH_TERMS,
            *ADJACENT_SEARCH_TERMS,
        )
    )
)

NODE_ECOSYSTEM_TECHNOLOGIES = frozenset(
    {"JavaScript", "TypeScript", "Node.js", "NestJS", "Express", "Fastify"}
)
