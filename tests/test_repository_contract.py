import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_public_repository_files_exist_and_cover_private_state(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for name in (
            "SILICONFLOW_API_KEY",
            "GROQ_API_KEY",
            "CLERK_PUBLISHABLE_KEY",
            "CLERK_JWKS_URL",
            "CLERK_ALLOWED_ORIGINS",
        ):
            self.assertIn(f"{name}=", env_example)

        for ignored in (
            ".env",
            ".venv/",
            "node_modules/",
            "__pycache__/",
            "*.log",
            "web_app/storage/app.sqlite3",
            "web_app/storage/chroma/",
            "data/chunks/",
            "data/indexes/",
            "data/chroma_manifests/",
            "web_app/frontend/dist/",
        ):
            self.assertIn(ignored, gitignore)

    def test_setup_builds_frontend_and_verifies_lexical_index(self):
        setup = (ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8")
        npm_ci = setup.index("npm ci")
        npm_build = setup.index("npm run build")
        rag_index = setup.index("-m scripts.RAG.indexing")

        self.assertLess(npm_ci, npm_build)
        self.assertLess(npm_build, rag_index)
        self.assertIn('Join-Path $FrontendDist "index.html"', setup)
        self.assertIn('Join-Path $IndexDir "lexical.sqlite3"', setup)
        self.assertIn('Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath', setup)


if __name__ == "__main__":
    unittest.main()
