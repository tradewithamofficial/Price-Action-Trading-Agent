"""Local documentation/source-selection checks; no services or real credentials."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


PROJECT = Path(__file__).resolve().parents[1]


class RepositoryReleaseTests(unittest.TestCase):
    def test_documentation_relative_links_resolve_inside_source_tree(self):
        documents = [PROJECT / name for name in (
            'README.md', 'INSTALL-WITH-CHATGPT.md', 'CONTRIBUTING.md',
            'SECURITY.md', 'THIRD-PARTY-NOTICES.md')]
        documents += list((PROJECT / 'docs').glob('*.md'))
        documents += list((PROJECT / '.github').glob('*.md'))
        checked = 0
        for document in documents:
            content = document.read_text(encoding='utf-8-sig')
            content = re.sub(r'^```.*?^```\s*$', '', content, flags=re.M | re.S)
            for destination in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', content):
                parsed = urlsplit(destination.strip('<>'))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                target = (document.parent / unquote(parsed.path)).resolve()
                with self.subTest(document=document.name, target=destination):
                    self.assertTrue(target.is_relative_to(PROJECT))
                    self.assertTrue(target.is_file(), 'Broken local documentation link')
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_public_documents_contain_no_developer_specific_paths(self):
        documents = list(PROJECT.glob('*.md')) + list((PROJECT / 'docs').glob('*.md'))
        personal_path = re.compile(r'[A-Za-z]:\\Users\\[^\\\s]+|D:\\PythonProject\\', re.I)
        for document in documents:
            with self.subTest(document=document.name):
                self.assertIsNone(personal_path.search(document.read_text(encoding='utf-8-sig')))

    @unittest.skipUnless(shutil.which('git'), 'Git is required to validate its own ignore rules')
    def test_git_excludes_private_and_generated_files_but_keeps_public_sources(self):
        # Only this disposable repository is initialized; the working project is not.
        build = PROJECT / 'build'
        build.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='repository-check-', dir=build) as temporary:
            self.assertTrue(Path(temporary).resolve().is_relative_to(build.resolve()))
            subprocess.run(['git', 'init', '--quiet', '--template=', temporary], check=True,
                           capture_output=True, text=True)
            ignored = [
                'telegram_config.local.json', 'telegram_config.local.json.bak',
                'nested/telegram_config.local.json', '.env', '.env.production',
                '.codex/auth.json', 'auth.json', 'models_cache.json',
                '.idea/workspace.xml', '.venv/Lib/private.py', '__pycache__/main.pyc',
                'diagnostics/snapshot.json', 'runs/analysis.json', 'logs/output.log',
                'build/PriceActionTradingAgent.spec', 'dist/old.exe',
                'release/PriceActionTradingAgent/telegram_config.local.json',
                'release/PriceActionTradingAgent/PriceActionTradingAgent.exe',
                'browser-data/Cookies', 'user-data/Local State', 'trace.har',
                'private.pem', 'assets/TradeWithAM_Robot.png',
                'assets/Gemini_Generated_Image_h87vqsh87vqsh87v.jpg',
            ]
            public = [
                'main.py', 'sr_agent.py', 'sr_grouping.py', 'telegram_sender.py',
                'ui_dialogs.py', 'build.ps1', 'requirements.txt', 'requirements-build.txt',
                'telegram_config.example.json', 'LICENSE', 'README.md',
                'INSTALL-WITH-CHATGPT.md', '.github/CODEOWNERS',
                '.github/PULL_REQUEST_TEMPLATE.md', 'docs/TECHNICAL.md',
                'docs/RELEASE-CHECKLIST.md', 'tests/test_repository_release.py',
                'third_party_licenses/Python-LICENSE.txt',
                'assets/TradeWithAM_Robot.ico',
                'assets/Futuristic AI Robot with Breakout Chart.png',
            ]
            result = subprocess.run([
                'git', '-c', 'core.excludesFile=NUL',
                '--git-dir='+str(Path(temporary) / '.git'), '--work-tree='+str(PROJECT),
                'check-ignore', '--no-index', '--stdin', '-z',
            ], input=('\0'.join(ignored+public)+'\0').encode(), capture_output=True, check=True)
            self.assertEqual(set(result.stdout.decode().strip('\0').split('\0')), set(ignored))

    def test_install_prompt_is_copyable_and_publication_is_not_claimed(self):
        guide = (PROJECT / 'INSTALL-WITH-CHATGPT.md').read_text(encoding='utf-8-sig')
        prompt = re.search(r'```text\n(.*?)\n```', guide, flags=re.S)
        self.assertIsNotNone(prompt)
        self.assertIn('WAIT', prompt.group(1))
        self.assertIn('NEVER ask me to paste', prompt.group(1))
        self.assertIn('Verify the official repository', prompt.group(1))
        self.assertIn('Publication is pending', guide)

    def test_license_and_community_files_are_ready_for_maintainer_review(self):
        license_text = (PROJECT / 'LICENSE').read_text(encoding='utf-8')
        self.assertTrue(license_text.startswith('MIT License\n'))
        self.assertIn('Copyright (c) 2026 Trade With AM', license_text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', license_text)
        self.assertIn('* @tradewithamofficial', (PROJECT / '.github/CODEOWNERS').read_text())
        for name in ('CONTRIBUTING.md', 'SECURITY.md', '.github/PULL_REQUEST_TEMPLATE.md'):
            self.assertTrue((PROJECT / name).is_file())


if __name__ == '__main__':
    unittest.main()
